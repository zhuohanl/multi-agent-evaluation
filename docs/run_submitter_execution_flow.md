# Understanding RunSubmitterClient.run() Execution

## Overview
When `RunSubmitterClient.run()` is called, it orchestrates a complex asynchronous batch evaluation process. This document traces the complete execution flow from the initial call to the final results, explaining where compute happens and how evaluators work.

---

## High-Level Flow

```
RunSubmitterClient.run()
    ↓
Wraps data & starts async execution in ThreadPool
    ↓
RunSubmitter.submit()
    ↓
Creates Run object & validates inputs
    ↓
BatchEngine.run()
    ↓
Applies column mapping & prepares batch inputs
    ↓
BatchEngine._exec_batch()
    ↓
Creates async tasks for each input row (with concurrency control)
    ↓
BatchEngine._exec_line_async()
    ↓
**Evaluator.__call__() executes HERE** (local compute)
    ↓
Collects results & aggregates metrics
    ↓
Returns BatchResult
```

---

## Step-by-Step Execution

### **Step 1: Entry Point - RunSubmitterClient.run()**
**File:** `_run_submitter_client.py` (lines 52-92)

```python
def run(
    self,
    flow: Callable,  # The evaluator instance
    data: Union[str, PathLike, pd.DataFrame],  # Input DataFrame
    column_mapping: Optional[Dict[str, str]] = None,
    evaluator_name: Optional[str] = None,
    **kwargs: Any,
) -> BatchClientRun:
```

**What happens:**

1. **Validates data is a DataFrame**
   ```python
   if not isinstance(data, pd.DataFrame):
       raise ValueError("Data must be a pandas DataFrame")
   ```

2. **Wraps each row in a "data" envelope**
   ```python
   inputs = [{"data": input_data} for input_data in data.to_dict(orient="records")]
   ```
   
   **Example transformation:**
   ```python
   # Input DataFrame:
   # | query | context | response |
   # |-------|---------|----------|
   # | "Q1"  | "C1"    | "R1"     |
   
   # Becomes:
   [
       {"data": {"query": "Q1", "context": "C1", "response": "R1"}}
   ]
   ```

3. **Extracts previous run if provided** (for chaining evaluators)
   ```python
   run: Optional[BatchClientRun] = kwargs.pop("run", None)
   if run:
       kwargs["run"] = self._get_run(run)
   ```

4. **Gets async version of evaluator if available**
   ```python
   if isinstance(flow, HasAsyncCallable):
       flow = flow._to_async()  # Get async callable from evaluator
   ```

5. **Creates RunSubmitter and submits to ThreadPool**
   ```python
   run_submitter = RunSubmitter(self._config, self._thread_pool)
   run_future = self._thread_pool.submit(
       asyncio.run,  # Run async code in thread
       run_submitter.submit(
           dynamic_callable=flow,  # The evaluator
           inputs=inputs,  # Wrapped data
           column_mapping=column_mapping,
           name_prefix=evaluator_name,
           **kwargs,
       ),
   )
   return run_future  # Returns immediately (Future object)
   ```

**Key Point:** Execution is **asynchronous**. This returns a `Future` object immediately without waiting for completion.

---

### **Step 2: Run Submission - RunSubmitter.submit()**
**File:** `_run_submitter.py` (lines 38-86)

```python
async def submit(
    self,
    dynamic_callable: Callable,  # The evaluator
    inputs: Sequence[Mapping[str, Any]],  # Wrapped data rows
    column_mapping: Optional[Mapping[str, str]],
    **kwargs,
) -> Run:
```

**What happens:**

1. **Creates Run object** to track execution
   ```python
   run: Run = Run(
       dynamic_callable=dynamic_callable,  # The evaluator function
       name_prefix=name_prefix,
       inputs=inputs,
       column_mapping=column_mapping,
       created_on=created_on,
       run=kwargs.pop("run", None),  # Previous run for chaining
   )
   ```

2. **Starts tracing** (for telemetry/debugging)
   ```python
   start_trace(attributes=attributes, run=run, _collection=collection_for_run)
   ```

3. **Validates inputs**
   ```python
   self._validate_inputs(run=run)
   ```

4. **Creates storage** (for logging/persistence)
   ```python
   local_storage = storage_creator(run) if storage_creator else NoOpRunStorage()
   ```

5. **Calls _submit_bulk_run** to actually execute
   ```python
   await self._submit_bulk_run(run=run, local_storage=local_storage, **kwargs)
   ```

---

### **Step 3: Bulk Run Setup - RunSubmitter._submit_bulk_run()**
**File:** `_run_submitter.py` (lines 88-177)

**What happens:**

1. **Handles previous run outputs** (if chaining evaluators)
   ```python
   if run.previous_run:
       # Merge previous outputs with current inputs
       run.inputs = [
           {
               "run.outputs": previous.outputs[i],
               "run.inputs": previous.inputs[i],
               **run.inputs[i]
           }
           for i in range(len(run.inputs))
       ]
   ```

2. **Validates column mapping**
   ```python
   self._validate_column_mapping(run.column_mapping)
   ```

3. **Sets run status and start time**
   ```python
   run._status = RunStatus.RUNNING
   run._start_time = datetime.now(timezone.utc)
   ```

4. **Creates BatchEngine and executes**
   ```python
   batch_engine = BatchEngine(
       run.dynamic_callable,  # The evaluator
       config=self._config,
       storage=local_storage,
       executor=self._executor,  # ThreadPool for sync functions
   )
   
   batch_result = await batch_engine.run(
       data=run.inputs,
       column_mapping=run.column_mapping,
       id=run.name
   )
   ```

5. **Updates run status based on result**
   ```python
   run._status = RunStatus.from_batch_result_status(batch_result.status)
   ```

---

### **Step 4: Batch Execution - BatchEngine.run()**
**File:** `_engine.py` (lines 95-114)

```python
async def run(
    self,
    data: Sequence[Mapping[str, Any]],  # Input rows
    column_mapping: Optional[Mapping[str, str]],
    *,
    id: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> BatchResult:
```

**What happens:**

1. **Validates data is not empty**
   ```python
   if not data:
       raise BatchEngineValidationError("Please provide a non-empty data mapping.")
   ```

2. **Applies column mapping to transform data**
   ```python
   batch_inputs = self._apply_column_mapping(data, column_mapping, max_lines)
   ```
   
   **Column mapping transformation:**
   ```python
   # Input: {"data": {"query": "Q1", "context": "C1"}}
   # Mapping: {"query": "${data.query}", "context": "${data.context}"}
   # Output: {"query": "Q1", "context": "C1"}  # Ready for evaluator
   ```

3. **Executes batch in task**
   ```python
   result: BatchResult = await self._exec_in_task(id, batch_inputs, start_time)
   ```

---

### **Step 5: Column Mapping Application**
**File:** `_engine.py` (lines 116-211)

**Key Functions:**

#### **5a. _resolve_column_mapping()**
Creates default mappings for evaluator parameters:
```python
parameters = inspect.signature(self._func).parameters
default_column_mapping: Dict[str, str] = {
    name: f"${{data.{name}}}"
    for name, value in parameters.items()
    if name not in ["self", "cls", "args", "kwargs"]
}
```

**Example:**
```python
# For IntentResolutionEvaluator with params: query, response, tool_definitions
# Creates:
{
    "query": "${data.query}",
    "response": "${data.response}",
    "tool_definitions": "${data.tool_definitions}"
}
```

#### **5b. _apply_column_mapping_to_lines()**
Extracts values from input data using mapping expressions:

```python
for key, value in column_mapping.items():
    if value.startswith("${") and value.endswith("}"):
        dict_path = value[2:-1]  # Extract "data.query" from "${data.query}"
        found, mapped_value = get_value_from_path(dict_path, input)
        if found:
            mapped[key] = mapped_value
```

**Result:** Each input row is transformed into arguments for the evaluator function.

---

### **Step 6: Task Orchestration - BatchEngine._exec_in_task()**
**File:** `_engine.py` (lines 213-295)

**What happens:**

1. **Creates async task for batch execution**
   ```python
   task = asyncio.create_task(self._exec_batch(run_id, batch_inputs, start_time, results))
   ```

2. **Monitors task with timeout and cancellation**
   ```python
   while not task.done():
       await asyncio.sleep(1)
       if self._is_canceled:
           task.cancel()
           status = BatchStatus.Canceled
       elif self._batch_timeout_expired(start_time):
           task.cancel()
           status = BatchStatus.Failed
   ```

3. **Collects results and handles missing/failed lines**
   ```python
   result_details = [
       results[i] if i in results
       else BatchRunDetails(
           status=BatchStatus.Failed,
           error=BatchRunError("The line run is not completed.", None)
       )
       for i in range(len(batch_inputs))
   ]
   ```

4. **Aggregates metrics and status**
   ```python
   for line_result in result_details:
       status = max(status, line_result.status)
       if BatchStatus.is_failed(line_result.status):
           failed_lines += 1
       if line_result.tokens:
           metrics.prompt_tokens += line_result.tokens.prompt_tokens
           # ...
   ```

5. **Returns BatchResult**

---

### **Step 7: Batch Execution - BatchEngine._exec_batch()**
**File:** `_engine.py` (lines 297-340)

**This is where concurrency happens!**

```python
async def _exec_batch(
    self,
    run_id: str,
    batch_inputs: Sequence[Mapping[str, Any]],
    start_time: datetime,
    results: MutableMapping[int, BatchRunDetails],
) -> None:
```

**What happens:**

1. **Creates semaphore for concurrency control**
   ```python
   semaphore: Semaphore = Semaphore(self._max_worker_count)
   # Default max_worker_count = 4 (or from PF_WORKER_COUNT env var)
   ```

2. **Creates async task for EACH input row**
   ```python
   async def create_under_semaphore(index: int, inputs: Mapping[str, Any]):
       async with semaphore:  # Only N tasks run concurrently
           return await self._exec_line_async(run_id, inputs, index)
   
   pending = [
       asyncio.create_task(create_under_semaphore(index, inputs))
       for index, inputs in enumerate(batch_inputs)
   ]
   ```

3. **Waits for tasks to complete** (as they finish)
   ```python
   while completed_lines < total_lines:
       # Wait for ANY task to complete
       done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
       completed_line_results = [task.result() for task in done]
       
       # Persist results
       self._persist_run_info([result for _, result in completed_line_results])
       results.update({index: result for index, result in completed_line_results})
       
       # Update progress
       completed_lines += len(completed_line_results)
       log_progress(...)
   ```

**Key Point:** Multiple rows are processed **in parallel** (up to `max_worker_count` at once).

---

### **Step 8: Line Execution - BatchEngine._exec_line_async()**
**File:** `_engine.py` (lines 355-410)

**THIS IS WHERE THE EVALUATOR ACTUALLY RUNS!**

```python
async def _exec_line_async(
    self,
    run_id: str,
    inputs: Mapping[str, Any],  # Single row's mapped inputs
    index: int,
) -> Tuple[int, BatchRunDetails]:
```

**What happens:**

1. **Creates BatchRunDetails to track this line**
   ```python
   details: BatchRunDetails = BatchRunDetails(
       id=f"{run_id}_{index}",
       status=BatchStatus.NotStarted,
       result=None,
       start_time=datetime.now(timezone.utc),
       tokens=TokenMetrics(0, 0, 0),
       error=None,
       index=index,
   )
   ```

2. **Captures OpenAI token usage**
   ```python
   with CaptureOpenAITokenUsage() as captured_tokens:
   ```

3. **Preprocesses inputs** (filters to only params evaluator accepts)
   ```python
   processed_inputs = self.__preprocess_inputs(inputs)
   ```

4. **EXECUTES THE EVALUATOR** ⚡
   ```python
   if is_async_callable(self._func):
       # Async evaluators: await directly
       output = await self._func(**processed_inputs)
   else:
       # Sync evaluators: run in thread to avoid blocking
       output = await asyncio.get_event_loop().run_in_executor(
           self._executor,  # ThreadPoolExecutor
           partial(self._func, **processed_inputs)
       )
   
   # Extra safety: await if output is awaitable
   if inspect.isawaitable(output):
       output = await output
   ```
   
   **This is where:**
   - `IntentResolutionEvaluator.__call__()` executes
   - `ToolCallAccuracyEvaluator.__call__()` executes  
   - `TaskAdherenceEvaluator.__call__()` executes
   
   **Compute happens:** 
   - ✅ **Locally** on your machine
   - ✅ In the **Python process**
   - ✅ Async evaluators run in event loop
   - ✅ Sync evaluators run in ThreadPool
   - ✅ Multiple rows processed concurrently (up to `max_worker_count`)

5. **Stores result and metrics**
   ```python
   details.status = BatchStatus.Completed
   details.result = convert_eager_flow_output_to_dict(output)
   details.tokens.update(captured_tokens)
   ```

6. **Handles errors**
   ```python
   except Exception as ex:
       details.status = BatchStatus.Failed
       details.error = BatchRunError(
           f"Error while evaluating single input: {ex.__class__.__name__}: {str(ex)}", 
           ex
       )
   ```

7. **Returns index and details**
   ```python
   return index, details
   ```

---

## Where Does Compute Happen?

### **Location: LOCAL Machine**

```
Your Python Process
    ↓
RunSubmitterClient Thread Pool
    ↓
AsyncIO Event Loop (per thread)
    ↓
Evaluator.__call__() executes
    ↓
Makes API call to Azure OpenAI (for LLM judgment)
    ↓
Returns result locally
```

### **Compute Breakdown:**

| Component | Where | How |
|-----------|-------|-----|
| **Data preprocessing** | Local Python | Synchronous |
| **Column mapping** | Local Python | Synchronous |
| **Task orchestration** | Local Python | AsyncIO event loop |
| **Evaluator execution** | Local Python | Async (event loop) or Sync (ThreadPool) |
| **LLM calls** | Azure OpenAI API | HTTP requests from evaluator |
| **Result aggregation** | Local Python | Synchronous |
| **Metric calculation** | Local Python | Synchronous |

### **NOT Remote Compute**
Unlike `AzureOpenAIGrader` which submits jobs to Azure's evaluation service:
- ✅ Evaluator code runs **locally**
- ✅ Only LLM inference calls go to Azure
- ✅ All orchestration is **local**
- ✅ Results are computed **locally**

---

## Concurrency Model

### **Multi-Level Parallelism:**

```
Main Thread
    ↓
ThreadPoolExecutor (max_workers = PF_WORKER_COUNT)
    ↓
    ├─ Thread 1: AsyncIO Event Loop
    │     ↓
    │     ├─ Task 1: _exec_line_async(row 0)
    │     ├─ Task 2: _exec_line_async(row 1)
    │     └─ Task N: _exec_line_async(row N)
    │
    ├─ Thread 2: Runs sync evaluators (if needed)
    ├─ Thread 3: Runs sync evaluators (if needed)
    └─ Thread 4: Runs sync evaluators (if needed)
```

### **Concurrency Control:**

1. **Semaphore limits concurrent executions**
   ```python
   semaphore: Semaphore = Semaphore(self._max_worker_count)
   # Default: 4 concurrent evaluations
   ```

2. **Environment variable control**
   ```bash
   export PF_WORKER_COUNT=8  # Increase to 8 concurrent workers
   ```

3. **Async vs Sync handling**
   - **Async evaluators:** Run in event loop (non-blocking)
   - **Sync evaluators:** Run in ThreadPool (parallel threads)

---

## Example Execution Timeline

### **Scenario:** Evaluating 10 rows with 3 evaluators, max_worker_count=4

```
Time    | Action
--------|--------------------------------------------------------
T0      | RunSubmitterClient.run() called
T0+1ms  | Submit to ThreadPool, return Future immediately
T0+2ms  | Thread starts AsyncIO event loop
T0+3ms  | RunSubmitter creates Run object
T0+5ms  | BatchEngine.run() called
T0+10ms | Column mapping applied to 10 rows
T0+15ms | Create 10 async tasks (one per row)
T0+20ms | Semaphore allows first 4 tasks to start
        |
        | --- CONCURRENT EVALUATION PHASE ---
        |
T0+50ms | Task 0 (row 0): IntentResolutionEvaluator running
T0+50ms | Task 1 (row 1): ToolCallAccuracyEvaluator running
T0+50ms | Task 2 (row 2): TaskAdherenceEvaluator running
T0+50ms | Task 3 (row 3): IntentResolutionEvaluator running
        |
T0+2s   | Task 0 completes, Task 4 starts
T0+2.5s | Task 1 completes, Task 5 starts
T0+3s   | Task 2 completes, Task 6 starts
        | ... (tasks complete and new ones start)
        |
T0+15s  | All 10 tasks complete
T0+15s  | Aggregate metrics calculated
T0+15s  | BatchResult returned
T0+15s  | Run status set to COMPLETED
T0+15s  | Future resolves with results
```

---

## How Evaluators Work

### **Evaluator Execution Sequence:**

```
1. BatchEngine calls evaluator with mapped inputs
       ↓
2. Evaluator.__call__() invoked
       ↓
3. For PromptyEvaluatorBase evaluators:
       ↓
   a. Load prompty template
   b. Fill template with inputs
   c. Call Azure OpenAI API (via model_config)
   d. Parse LLM response
   e. Extract scores/metrics
   f. Return dictionary result
       ↓
4. BatchEngine captures result
       ↓
5. Token usage tracked
       ↓
6. Result stored in BatchRunDetails
```

### **Example: IntentResolutionEvaluator**

```python
# Input (after column mapping):
{
    "query": "What is the weather?",
    "response": "The weather is sunny.",
    "tool_definitions": [...]
}

# Evaluator processes:
1. Loads intent_resolution.prompty template
2. Inserts query and response into prompt
3. Calls Azure OpenAI with filled prompt
4. Gets LLM judgment: {"score": 5, "explanation": "..."}
5. Formats output:
{
    "intent_resolution": 5.0,
    "intent_resolution_result": "pass",
    "intent_resolution_reason": "...",
    "intent_resolution_prompt_tokens": 150,
    "intent_resolution_completion_tokens": 50,
    # ...
}

# BatchEngine receives and stores this result
```

---

## Key Takeaways

### **1. Compute Location**
- ✅ **All orchestration:** Local Python process
- ✅ **Evaluator execution:** Local Python process
- ✅ **LLM inference:** Azure OpenAI API (remote)
- ✅ **Result aggregation:** Local Python process

### **2. Execution Model**
- ✅ **Asynchronous:** Uses AsyncIO for concurrency
- ✅ **Parallel:** Multiple rows processed simultaneously
- ✅ **Non-blocking:** Returns Future immediately
- ✅ **Configurable:** Worker count via environment variable

### **3. Data Flow**
```
DataFrame → Wrapped → Column Mapped → Evaluator → Result → Aggregated
```

### **4. Concurrency**
- Default: 4 concurrent workers
- Configurable: `PF_WORKER_COUNT` environment variable
- Async evaluators: Run in event loop
- Sync evaluators: Run in ThreadPool

### **5. Error Handling**
- Per-line error tracking
- Failed lines don't stop batch
- Aggregated error reporting
- Optional raise_on_error mode

---

## Configuration

### **Environment Variables:**

```bash
# Maximum concurrent workers (default: 4)
export PF_WORKER_COUNT=8

# Overall batch timeout in seconds (default: unlimited)
export PF_BATCH_TIMEOUT_SEC=3600

# Per-line timeout in seconds (default: unlimited)
export PF_LINE_TIMEOUT_SEC=60
```

### **Code Configuration:**

```python
# In RunSubmitterClient.__init__():
config = BatchEngineConfig(logger, use_async=True)
config.batch_timeout_seconds = get_int("PF_BATCH_TIMEOUT_SEC")
config.line_timeout_seconds = get_int("PF_LINE_TIMEOUT_SEC")
config.max_concurrency = get_int("PF_WORKER_COUNT")
config.raise_on_error = fail_on_evaluator_errors
```

---

## Summary

**`RunSubmitterClient.run()`** orchestrates a sophisticated local batch evaluation system:

1. ✅ Wraps data and submits to ThreadPool
2. ✅ Creates async tasks for each input row
3. ✅ Controls concurrency with semaphores
4. ✅ Executes evaluators **locally** with parallelism
5. ✅ Handles async and sync evaluators differently
6. ✅ Tracks progress, errors, and metrics per-line
7. ✅ Aggregates results and returns BatchResult

**Compute happens entirely locally** except for LLM API calls, making it fast and efficient for evaluating large datasets with multiple evaluators in parallel.
