# Batch Client Types in Azure AI Evaluation

## Overview
When you call `evaluate()` in Azure AI Evaluation SDK, the framework uses one of three batch client types to execute your evaluators. The client type determines how evaluations are executed and orchestrated.

---

## The Three Client Types

### 1. **`run_submitter`** (Default)
**Class:** `RunSubmitterClient`

**Characteristics:**
- ✅ **Default client** when no flags are specified
- ✅ Uses `ThreadPoolExecutor` for concurrent execution
- ✅ Runs evaluators asynchronously via `asyncio.run()`
- ✅ Works with **pandas DataFrames**
- ✅ Part of legacy batch engine infrastructure
- ✅ Configurable concurrency and timeouts via environment variables

**When it's used:**
```python
# Both flags unset or None (default behavior)
evaluate(
    data=data_file,
    evaluators={...}
)
```

**Configuration:**
Can be controlled via environment variables:
- `PF_BATCH_TIMEOUT_SEC` - Overall batch timeout
- `PF_LINE_TIMEOUT_SEC` - Per-line timeout
- `PF_WORKER_COUNT` - Max concurrency (worker threads)

**Internal execution:**
```python
batch_run_client = RunSubmitterClient(raise_on_errors=fail_on_evaluator_errors)
batch_run_data = input_data_df  # Uses DataFrame directly
```

---

### 2. **`pf_client`** (PromptFlow Client)
**Class:** `ProxyClient`

**Characteristics:**
- ✅ Uses PromptFlow infrastructure
- ✅ Works with **file paths** (JSONL files)
- ✅ Provides compatibility with PromptFlow tooling
- ✅ Requires absolute file paths

**When it's used:**
```python
# Explicitly set _use_pf_client=True
evaluate(
    data=data_file,
    evaluators={...},
    _use_pf_client=True
)
```

**Internal execution:**
```python
batch_run_client = ProxyClient(user_agent=UserAgentSingleton().value)
batch_run_data = os.path.abspath(data)  # Uses absolute file path
```

**Special handling:**
- When used with target functions, creates temporary JSONL files
- Ensures evaluators get all rows (including failed ones with NaN values)
- Modifies column mappings to use data references instead of run outputs

---

### 3. **`code_client`** (Direct Code Execution)
**Class:** `CodeClient`

**Characteristics:**
- ✅ Direct code execution client
- ✅ Works with **pandas DataFrames**
- ✅ Simpler execution model

**When it's used:**
```python
# Both flags explicitly set to False
evaluate(
    data=data_file,
    evaluators={...},
    _use_run_submitter_client=False,
    _use_pf_client=False
)
```

**Internal execution:**
```python
batch_run_client = CodeClient()
batch_run_data = input_data_df  # Uses DataFrame directly
```

---

## Client Selection Logic

The `get_client_type()` function determines which client to use:

```python
def get_client_type(evaluate_kwargs: Dict[str, Any]) -> Literal["run_submitter", "pf_client", "code_client"]:
    _use_run_submitter_client = kwargs.pop("_use_run_submitter_client", None)
    _use_pf_client = kwargs.pop("_use_pf_client", None)
    
    # DEFAULT: Both None → run_submitter
    if _use_run_submitter_client is None and _use_pf_client is None:
        return "run_submitter"
    
    # ERROR: Both True
    if _use_run_submitter_client and _use_pf_client:
        raise EvaluationException("Only one should be True")
    
    # BOTH FALSE: code_client
    if _use_run_submitter_client == False and _use_pf_client == False:
        return "code_client"
    
    # ONE TRUE: Use the one that's True
    if _use_run_submitter_client:
        return "run_submitter"
    if _use_pf_client:
        return "pf_client"
    
    # MIXED None and False
    if _use_run_submitter_client is None and _use_pf_client == False:
        return "run_submitter"
    if _use_run_submitter_client == False and _use_pf_client is None:
        return "pf_client"
```

---

## Decision Tree

```
Are _use_run_submitter_client and _use_pf_client both None?
    YES → run_submitter (DEFAULT)
    NO ↓

Are both set to True?
    YES → ERROR (Invalid configuration)
    NO ↓

Are both set to False?
    YES → code_client
    NO ↓

Is _use_run_submitter_client = True?
    YES → run_submitter
    NO ↓

Is _use_pf_client = True?
    YES → pf_client
    NO ↓

Is _use_run_submitter_client = None and _use_pf_client = False?
    YES → run_submitter
    NO ↓

Is _use_run_submitter_client = False and _use_pf_client = None?
    YES → pf_client
```

---

## Comparison Table

| Feature | run_submitter | pf_client | code_client |
|---------|---------------|-----------|-------------|
| **Default** | ✅ Yes | ❌ No | ❌ No |
| **Data Format** | DataFrame | File path (JSONL) | DataFrame |
| **Concurrency** | ThreadPoolExecutor | PromptFlow engine | Direct execution |
| **Async Support** | ✅ Yes (asyncio) | ✅ Yes | Depends on impl |
| **Configuration** | Env variables | User agent | Minimal |
| **PromptFlow Integration** | ❌ No | ✅ Yes | ❌ No |
| **Recommended For** | General use | PF compatibility | Simple cases |

---

## Your Evaluators Example

Given this code:
```python
intent_resolution = IntentResolutionEvaluator(model_config=model_config)
tool_call_accuracy = ToolCallAccuracyEvaluator(model_config=model_config)
task_adherence = TaskAdherenceEvaluator(model_config=model_config)

response = evaluate(
    data=data_file_name,
    evaluators={
        "tool_call_accuracy": tool_call_accuracy,
        "intent_resolution": intent_resolution,
        "task_adherence": task_adherence,
    },
    azure_ai_project=os.environ["AZURE_AI_PROJECT"]
)
```

**Client Type Used:** `run_submitter` (default)

**Why:**
- No `_use_run_submitter_client` parameter → defaults to `None`
- No `_use_pf_client` parameter → defaults to `None`
- Both `None` → defaults to `"run_submitter"`

---

## How to Override

### Use PromptFlow Client
```python
response = evaluate(
    data=data_file_name,
    evaluators={...},
    _use_pf_client=True
)
```

### Use Code Client
```python
response = evaluate(
    data=data_file_name,
    evaluators={...},
    _use_run_submitter_client=False,
    _use_pf_client=False
)
```

### Explicitly Use Run Submitter
```python
response = evaluate(
    data=data_file_name,
    evaluators={...},
    _use_run_submitter_client=True
)
```

---

## Implementation Details

### RunSubmitterClient Initialization
```python
if client_type == "run_submitter":
    batch_run_client = RunSubmitterClient(raise_on_errors=fail_on_evaluator_errors)
    batch_run_data = input_data_df
```

**What it does:**
- Creates thread pool with configurable workers
- Sets up batch engine config
- Enables async execution of evaluators
- Passes DataFrame directly as data

### ProxyClient Initialization
```python
elif client_type == "pf_client":
    batch_run_client = ProxyClient(user_agent=UserAgentSingleton().value)
    batch_run_data = os.path.abspath(data)
```

**What it does:**
- Creates PromptFlow proxy client
- Converts data path to absolute path
- Integrates with PF infrastructure
- May create temp files for target function outputs

### CodeClient Initialization
```python
elif client_type == "code_client":
    batch_run_client = CodeClient()
    batch_run_data = input_data_df
```

**What it does:**
- Creates simple code execution client
- Passes DataFrame directly
- Minimal overhead

---

## Environment Variables (for run_submitter)

Configure RunSubmitterClient behavior:

```bash
# Overall batch timeout (seconds)
export PF_BATCH_TIMEOUT_SEC=3600

# Per-line/row timeout (seconds)
export PF_LINE_TIMEOUT_SEC=60

# Number of concurrent workers
export PF_WORKER_COUNT=4
```

In PowerShell:
```powershell
$env:PF_BATCH_TIMEOUT_SEC = "3600"
$env:PF_LINE_TIMEOUT_SEC = "60"
$env:PF_WORKER_COUNT = "4"
```

---

## Execution Flow

### 1. Client Type Determination
```
evaluate() called
    ↓
_preprocess_data()
    ↓
get_client_type(kwargs)
    ↓
Returns: "run_submitter" | "pf_client" | "code_client"
```

### 2. Client Instantiation
```
Based on client_type:
    ↓
Create appropriate BatchClient instance
    ↓
Prepare batch_run_data (DataFrame or file path)
```

### 3. Evaluation Execution
```
_run_callable_evaluators()
    ↓
For each evaluator:
    batch_run_client.run(evaluator, data, column_mapping)
    ↓
Client executes evaluator on data
    ↓
Returns results
```

---

## Key Takeaways

1. **Default is `run_submitter`** - Most users get this automatically
2. **Explicit flags override defaults** - Use `_use_pf_client` or `_use_run_submitter_client`
3. **DataFrame vs File Path** - `run_submitter` and `code_client` use DataFrames; `pf_client` uses file paths
4. **Concurrency** - `run_submitter` provides configurable concurrent execution
5. **PromptFlow compatibility** - Use `pf_client` when integrating with PromptFlow tooling

---

## Recommendations

- **General use cases**: Stick with default (`run_submitter`)
- **PromptFlow integration**: Use `_use_pf_client=True`
- **Simple/testing scenarios**: Consider `code_client` with both flags set to `False`
- **Performance tuning**: Adjust `PF_WORKER_COUNT` environment variable

---

## Related Components

| Component | Purpose |
|-----------|---------|
| `BatchClient` | Abstract base class for all clients |
| `RunSubmitterClient` | Default concurrent batch executor |
| `ProxyClient` | PromptFlow integration client |
| `CodeClient` | Simple direct execution client |
| `BatchClientRun` | Represents a running batch job |
| `RunSubmitter` | Underlying async execution engine |

---

## Code Location

**File:** `azure/ai/evaluation/_evaluate/_evaluate.py`  
**Function:** `_preprocess_data()`  
**Lines:** 1390-1460

**Related Files:**
- `_batch_run/_run_submitter_client.py` - RunSubmitterClient implementation
- `_batch_run/proxy_client.py` - ProxyClient implementation
- `_batch_run/code_client.py` - CodeClient implementation
- `_batch_run/batch_clients.py` - Base BatchClient class
