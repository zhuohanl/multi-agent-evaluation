# Understanding the `_evaluate()` Function

## Overview
The `_evaluate()` function is the core evaluation engine in Azure AI Evaluation SDK. It orchestrates the entire evaluation process, handling both local evaluators (Python callables) and remote Azure OpenAI graders.

## Function Signature

```python
def _evaluate(
    *,
    evaluators_and_graders: Dict[str, Union[Callable, AzureOpenAIGrader]],
    evaluation_name: Optional[str] = None,
    target: Optional[Callable] = None,
    data: Union[str, os.PathLike],
    evaluator_config: Optional[Dict[str, EvaluatorConfig]] = None,
    azure_ai_project: Optional[Union[str, AzureAIProject]] = None,
    output_path: Optional[Union[str, os.PathLike]] = None,
    fail_on_evaluator_errors: bool = False,
    tags: Optional[Dict[str, str]] = None,
    **kwargs,
) -> EvaluationResult
```

## Step-by-Step Execution Flow

### **Phase 1: Initialization & Setup**

#### Step 1: Handle Error Configuration
```python
if fail_on_evaluator_errors:
    _print_fail_flag_warning()
```
- Checks if the user wants evaluations to fail immediately on errors
- Prints a warning if this flag is enabled

---

### **Phase 2: Data Preprocessing**

#### Step 2: Preprocess Input Data
```python
validated_data = _preprocess_data(
    data=data,
    evaluators_and_graders=evaluators_and_graders,
    evaluator_config=evaluator_config,
    target=target,
    output_path=output_path,
    azure_ai_project=azure_ai_project,
    evaluation_name=evaluation_name,
    fail_on_evaluator_errors=fail_on_evaluator_errors,
    tags=tags,
    **kwargs,
)
```

**What happens in `_preprocess_data()`:**
- **Validates and loads data** into a pandas DataFrame
- **Separates evaluators from graders**:
  - Evaluators: Local Python callables/built-in evaluators
  - Graders: Remote Azure OpenAI-based graders
- **Processes column mappings**: Maps input data columns to evaluator parameters
- **Validates target function** (if provided)
- **Creates batch run client** for executing evaluations

**Returns a validated data structure containing:**
- `evaluators`: Dictionary of local evaluators
- `graders`: Dictionary of Azure OpenAI graders
- `input_data_df`: Loaded DataFrame with input data
- `column_mapping`: Column name mappings for each evaluator
- `target_run`: Optional batch run for target function
- `batch_run_client`: Client to execute batch evaluations

#### Step 3: Extract Validated Components
```python
column_mapping = validated_data["column_mapping"]
evaluators = validated_data["evaluators"]
graders = validated_data["graders"]
input_data_df = validated_data["input_data_df"]
```

#### Step 4: Initialize Result Containers
```python
results_df = pd.DataFrame()
metrics: Dict[str, float] = {}
eval_run_info_list: List[OAIEvalRunCreationInfo] = []
eval_run_summary_dict = {}
```
- `results_df`: Will hold row-level evaluation results
- `metrics`: Will hold aggregated metrics
- `eval_run_info_list`: Tracks Azure OpenAI evaluation runs
- `eval_run_summary_dict`: Stores run summaries

---

### **Phase 3: Determine Execution Path**

#### Step 5: Check What Needs to Run
```python
need_oai_run = len(graders) > 0
need_local_run = len(evaluators) > 0
need_get_oai_results = False
got_local_results = False
```

Determines which evaluation paths to execute:
- **Azure OpenAI graders** (remote API calls)
- **Local evaluators** (Python callables)

---

### **Phase 4: Execute Azure OpenAI Graders (if needed)**

#### Step 6: Start Remote Azure OpenAI Evaluation Runs
```python
if need_oai_run:
    try:
        aoi_name = evaluation_name if evaluation_name else DEFAULT_OAI_EVAL_RUN_NAME
        eval_run_info_list = _begin_aoai_evaluation(
            graders, column_mapping, input_data_df, aoi_name, **kwargs
        )
        need_get_oai_results = len(eval_run_info_list) > 0
```

**What happens:**
- Initiates remote evaluation runs with Azure OpenAI graders
- Creates evaluation jobs on Azure
- Returns list of run info objects to track evaluation progress
- Sets `need_get_oai_results = True` if runs were successfully created

**Error Handling:**
```python
    except EvaluationException as e:
        if need_local_run:
            # Log warning and continue with local evaluators
            LOGGER.warning("Remote Azure Open AI grader evaluations failed during run creation.")
            LOGGER.warning(e)
        else:
            # No fallback available, re-raise exception
            raise e
```
- If Azure OpenAI graders fail but local evaluators exist: logs warning and continues
- If no local evaluators: raises exception (complete failure)

---

### **Phase 5: Execute Local Evaluators (if needed)**

#### Step 7: Run Local Python Evaluators
```python
if need_local_run:
    try:
        eval_result_df, eval_metrics, per_evaluator_results = _run_callable_evaluators(
            validated_data=validated_data, 
            fail_on_evaluator_errors=fail_on_evaluator_errors
        )
```

**What happens in `_run_callable_evaluators()`:**
- Uses the `batch_run_client` to execute each evaluator
- For each evaluator:
  - Runs it against the input data
  - Applies column mappings
  - Collects row-level results
  - Calculates aggregated metrics
  - Generates run summary
- Returns:
  - `eval_result_df`: DataFrame with per-row evaluation results
  - `eval_metrics`: Dictionary of aggregated metrics
  - `per_evaluator_results`: Detailed results per evaluator

#### Step 8: Store Local Results
```python
        results_df = eval_result_df
        metrics = eval_metrics
        got_local_results = True
```

#### Step 9: Print Summary
```python
        _print_summary(per_evaluator_results)
        eval_run_summary_dict = {
            name: result["run_summary"] 
            for name, result in per_evaluator_results.items()
        }
        LOGGER.info(f"run_summary: \r\n{json.dumps(eval_run_summary_dict, indent=4)}")
```
- Displays summary of evaluation results to console
- Logs detailed run summary as JSON

**Error Handling:**
```python
    except EvaluationException as e:
        if need_get_oai_results:
            # Log warning and continue with remote graders
            LOGGER.warning("Local evaluations failed. Will still attempt to retrieve online grader results.")
            LOGGER.warning(e)
        else:
            # No fallback available, re-raise exception
            raise e
```
- If local evaluators fail but Azure OpenAI graders exist: logs warning and continues
- If no Azure OpenAI graders: raises exception

---

### **Phase 6: Retrieve Azure OpenAI Results (if needed)**

#### Step 10: Get Remote Evaluation Results
```python
if need_get_oai_results:
    try:
        aoai_results, aoai_metrics = _get_evaluation_run_results(eval_run_info_list)
```

**What happens:**
- Polls Azure OpenAI evaluation runs until completion
- Retrieves row-level results and aggregated metrics
- Returns:
  - `aoai_results`: DataFrame with Azure OpenAI grader results
  - `aoai_metrics`: Aggregated metrics from graders

#### Step 11: Combine Results
```python
        if len(evaluators) > 0:
            # Both local and remote results exist - merge them
            results_df = pd.concat([results_df, aoai_results], axis=1)
            metrics.update(aoai_metrics)
        else:
            # Only remote results - combine with input data
            results_df = pd.concat([input_data_df, aoai_results], axis=1)
            metrics = aoai_metrics
```

**Merging Logic:**
- If **both local and remote** results: Concatenates columns side-by-side, merges metrics
- If **only remote** results: Combines Azure OpenAI results with original input data

**Error Handling:**
```python
    except EvaluationException as e:
        if got_local_results:
            # Log warning but still return local results
            LOGGER.warning("Remote Azure Open AI grader evaluations failed. Still returning local results.")
            LOGGER.warning(e)
        else:
            # No results available, re-raise exception
            raise e
```

---

### **Phase 7: Logging & Finalization**

#### Step 12: Map Names to Built-in Evaluators
```python
name_map = _map_names_to_builtins(evaluators, graders)
```
- Creates mapping between custom names and built-in evaluator types
- Used for proper logging and display

#### Step 13: Log to Azure AI Studio (if applicable)
```python
if is_onedp_project(azure_ai_project):
    studio_url = _log_metrics_and_instance_results_onedp(
        metrics, results_df, azure_ai_project, evaluation_name, name_map, tags=tags, **kwargs
    )
else:
    trace_destination = _trace_destination_from_project_scope(azure_ai_project) if azure_ai_project else None
    studio_url = None
    if trace_destination:
        studio_url = _log_metrics_and_instance_results(
            metrics, results_df, trace_destination, None, evaluation_name, name_map, tags=tags, **kwargs
        )
```

**What happens:**
- **For OneDLP projects**: Uses specialized logging for OneDP platform
- **For standard projects**: 
  - Creates trace destination from Azure AI project
  - Logs metrics and instance-level results
  - Returns studio URL for viewing results
- **No Azure project**: `studio_url` remains `None`

#### Step 14: Format Results
```python
result_df_dict = results_df.to_dict("records")
result: EvaluationResult = {
    "rows": result_df_dict, 
    "metrics": metrics, 
    "studio_url": studio_url
}
```

Converts results to final format:
- `rows`: List of dictionaries (one per input row)
- `metrics`: Dictionary of aggregated metrics
- `studio_url`: URL to view results in Azure AI Studio

#### Step 15: Handle Special Result Conversions (Optional)
```python
eval_id: Optional[str] = kwargs.get("_eval_id")
eval_run_id: Optional[str] = kwargs.get("_eval_run_id")
eval_meta_data: Optional[Dict[str, Any]] = kwargs.get("_eval_meta_data")

if kwargs.get("_convert_to_aoai_evaluation_result", False):
    _convert_results_to_aoai_evaluation_results(
        result, LOGGER, eval_id, eval_run_id, evaluators_and_graders, 
        eval_run_summary_dict, eval_meta_data
    )
```
- If internal flag is set, converts to Azure OpenAI evaluation result format
- Adds additional metadata for evaluation tracking

#### Step 16: Emit Telemetry (Optional)
```python
    if app_insights_configuration := kwargs.get("_app_insights_configuration"):
        emit_eval_result_events_to_app_insights(
            app_insights_configuration, result["_evaluation_results_list"], evaluator_config
        )
```
- If Application Insights configuration exists, sends telemetry events
- Helps track evaluation usage and performance

#### Step 17: Write Output to File (if specified)
```python
if output_path:
    _write_output(output_path, result)
```
- Writes evaluation results to specified output path
- Typically saves as JSON file

#### Step 18: Return Final Results
```python
return result
```

Returns `EvaluationResult` dictionary containing:
- **rows**: Per-input evaluation results
- **metrics**: Aggregated metrics across all inputs
- **studio_url**: Link to Azure AI Studio (if available)

---

## Key Concepts

### Dual Execution Paths
The function handles two types of evaluators:

1. **Local Evaluators** (Python callables):
   - Execute locally in the Python environment
   - Built-in evaluators (relevance, coherence, etc.)
   - Custom user-defined functions
   - Fast and synchronous

2. **Azure OpenAI Graders**:
   - Execute remotely via Azure OpenAI API
   - Use advanced AI models for evaluation
   - Asynchronous (runs are created, then results retrieved)
   - More powerful but requires Azure connection

### Resilient Error Handling
The function implements graceful degradation:
- If one type fails, it continues with the other
- Only fails completely if all evaluation paths fail
- Logs warnings for partial failures

### Batch Processing
- Uses `batch_run_client` to efficiently process multiple inputs
- Applies evaluators to entire dataset at once
- Returns row-level and aggregated results

### Column Mapping
- Flexibly maps dataset columns to evaluator parameters
- Allows evaluators to work with differently named columns
- Uses default mapping when not specified

### Azure Integration
- Optionally logs results to Azure AI Studio
- Provides URLs for viewing results in cloud
- Supports both standard and OneDP Azure projects

---

## Common Use Cases

### Case 1: Local Evaluators Only
```python
result = evaluate(
    data="data.jsonl",
    evaluators={
        "relevance": RelevanceEvaluator(),
        "coherence": CoherenceEvaluator()
    }
)
```
- Executes only Phase 5 (local evaluators)
- Skips Azure OpenAI grader phases

### Case 2: Azure OpenAI Graders Only
```python
result = evaluate(
    data="data.jsonl",
    evaluators={"custom_grader": AzureOpenAIGrader(...)},
    azure_ai_project=project
)
```
- Executes Phases 4 & 6 (Azure OpenAI graders)
- Skips local evaluator phase

### Case 3: Mixed Evaluation
```python
result = evaluate(
    data="data.jsonl",
    evaluators={
        "relevance": RelevanceEvaluator(),  # local
        "custom_grader": AzureOpenAIGrader(...)  # remote
    },
    azure_ai_project=project
)
```
- Executes both evaluation paths in parallel
- Combines results from both sources

---

## Result Structure

The returned `EvaluationResult` contains:

```python
{
    "rows": [
        {
            # Original input columns
            "question": "What is AI?",
            "answer": "Artificial Intelligence...",
            # Evaluation results
            "relevance": 4.5,
            "coherence": 5.0,
            "custom_metric": 0.85
        },
        # ... more rows
    ],
    "metrics": {
        "relevance": 4.2,  # Averaged across all rows
        "coherence": 4.8,
        "custom_metric": 0.82
    },
    "studio_url": "https://ai.azure.com/..."  # Optional
}
```

---

## Summary

The `_evaluate()` function orchestrates a sophisticated evaluation pipeline:

1. **Preprocesses** data and separates evaluators by type
2. **Executes** both local and remote evaluators (with error resilience)
3. **Combines** results from multiple sources
4. **Logs** to Azure AI Studio for tracking
5. **Returns** structured results with row-level and aggregate metrics

This design provides flexibility, resilience, and powerful evaluation capabilities for AI applications.
