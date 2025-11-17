# Understanding `client.evals.runs.create()`

## Overview
The call to `client.evals.runs.create()` at **line 935** initiates a remote evaluation run on Azure OpenAI's evaluation service. This is part of the asynchronous evaluation workflow for Azure OpenAI graders.

---

## Location in Code
**File:** `_evaluate_aoai.py`  
**Function:** `_begin_eval_run()`  
**Line:** 935

```python
eval_run = client.evals.runs.create(
    eval_id=eval_group_id,
    data_source=cast(Any, data_source),
    name=run_name,
    metadata={"sample_generation": "off", "file_format": "jsonl", "is_foundry_eval": "true"},
)
```

---

## What Happens Step-by-Step

### **Step 1: Function Entry**
The `_begin_eval_run()` function is called with:
- `client`: OpenAI or AzureOpenAI client instance
- `eval_group_id`: ID of the evaluation group (created earlier via `client.evals.create()`)
- `run_name`: Name for this evaluation run
- `input_data_df`: Pandas DataFrame with evaluation data
- `column_mapping`: Dictionary mapping columns to expected schema
- `data_source_params`: Optional additional data source parameters

### **Step 2: Prepare Data Source**
```python
data_source = _get_data_source(input_data_df, column_mapping)
```

**What `_get_data_source()` does:**

1. **Processes column mappings** to understand data structure
   - Parses mapping expressions like `${data.item.context.query}`
   - Extracts nested path specifications

2. **Iterates through DataFrame rows** and for each row:
   - Creates a nested dictionary structure matching the schema
   - Converts all values to strings (or keeps as list if already list)
   - Handles mapped columns (from column_mapping)
   - Includes unmapped columns directly at root level

3. **Wraps each row** in an `item` wrapper:
   ```python
   content.append({WRAPPER_KEY: item_root})  # WRAPPER_KEY = "item"
   ```

4. **Returns data source dictionary**:
   ```python
   {
       "type": "jsonl",
       "source": {
           "type": "file_content",
           "content": [
               {"item": {...}},  # Row 1
               {"item": {...}},  # Row 2
               # ... more rows
           ]
       }
   }
   ```

**Example transformation:**

**Input DataFrame:**
| query | context | response |
|-------|---------|----------|
| "What is AI?" | "Tech article" | "AI is..." |

**Column Mapping:**
```python
{
    "question": "${data.item.query}",
    "context": "${data.item.context}",
    "answer": "${data.item.response}"
}
```

**Output data_source:**
```json
{
    "type": "jsonl",
    "source": {
        "type": "file_content",
        "content": [
            {
                "item": {
                    "query": "What is AI?",
                    "context": "Tech article",
                    "response": "AI is..."
                }
            }
        ]
    }
}
```

### **Step 3: Apply Additional Parameters (Optional)**
```python
if data_source_params is not None:
    data_source.update(data_source_params)
```
Merges any additional data source configuration passed in kwargs.

### **Step 4: Create Evaluation Run**
```python
eval_run = client.evals.runs.create(
    eval_id=eval_group_id,
    data_source=cast(Any, data_source),
    name=run_name,
    metadata={"sample_generation": "off", "file_format": "jsonl", "is_foundry_eval": "true"},
)
```

**Parameters explained:**

| Parameter | Description |
|-----------|-------------|
| `eval_id` | The evaluation group ID (contains grader definitions) |
| `data_source` | The formatted data to evaluate (from Step 2) |
| `name` | User-friendly name for this run |
| `metadata` | Additional metadata flags:<br>- `sample_generation: "off"` - Don't generate samples<br>- `file_format: "jsonl"` - Data format<br>- `is_foundry_eval: "true"` - Marker for Foundry evals |

**What happens on the Azure OpenAI service:**

1. ✅ **Receives the request** with evaluation group ID and data
2. ✅ **Queues the evaluation job** for processing
3. ✅ **Returns an eval run object** with:
   - `eval_run.id` - Unique identifier for this run
   - `eval_run.status` - Initial status (typically "queued")
4. ✅ **Processes the evaluation asynchronously**:
   - Applies each grader to each row in the data
   - Executes the testing criteria defined in the eval group
   - Stores results on the server

### **Step 5: Return Run ID**
```python
LOGGER.info(f"AOAI: Eval run created successfully with ID: {eval_run.id}")
return eval_run.id
```

Returns the evaluation run ID to track this job later.

---

## Complete Context: Before and After

### **Before: Creating the Evaluation Group**
**Function:** `_begin_single_aoai_evaluation()` (line ~183)

```python
# Create eval group with grader definitions
eval_group_info = client.evals.create(
    data_source_config=data_source_config,
    testing_criteria=grader_list,  # List of grader configs
    metadata={"is_foundry_eval": "true"}
)
```

This creates the **evaluation template** with:
- Schema for expected data structure
- Testing criteria (graders) to apply
- Returns `eval_group_info.id`

### **During: Creating the Evaluation Run** (line 935)
```python
eval_run = client.evals.runs.create(
    eval_id=eval_group_id,  # Reference to eval group
    data_source=data_source,  # Actual data to evaluate
    name=run_name,
    metadata={...}
)
```

This **starts the actual evaluation job** using:
- The evaluation group template
- The specific data to evaluate
- Returns `eval_run.id`

### **After: Polling for Completion**
**Function:** `_wait_for_run_conclusion()` (line ~948)

```python
# Poll until evaluation completes
while True:
    sleep(wait_interval)
    response = client.evals.runs.retrieve(
        eval_id=eval_group_id,
        run_id=eval_run_id
    )
    if response.status not in ["queued", "in_progress"]:
        return response  # Evaluation complete!
```

---

## The Two-Phase Process

### **Phase 1: Create Evaluation Group** (Template)
```
client.evals.create()
    ↓
Creates evaluation "template" with:
- Data schema definition
- Grader configurations (testing criteria)
    ↓
Returns eval_group_id
```

**Analogy:** Creating a test template (defines what tests to run)

### **Phase 2: Create Evaluation Run** (Execution)
```
client.evals.runs.create()
    ↓
Starts evaluation job with:
- Reference to evaluation group (template)
- Actual data to evaluate
    ↓
Returns eval_run_id
    ↓
Job runs asynchronously on Azure
```

**Analogy:** Running the test on specific data

---

## Return Value

The `eval_run` object returned by `client.evals.runs.create()` contains:

```python
{
    "id": "run_abc123xyz",           # Unique run identifier
    "status": "queued",              # Initial status
    "eval_id": "eval_group_xyz",     # Reference to eval group
    "created_at": 1234567890,        # Timestamp
    # ... other metadata
}
```

The function extracts and returns just the ID:
```python
return eval_run.id
```

---

## Data Flow Diagram

```
Input DataFrame
    ↓
_get_data_source()
    ↓
Converts to nested JSON structure
    ↓
{
    "type": "jsonl",
    "source": {
        "type": "file_content",
        "content": [{"item": {...}}, ...]
    }
}
    ↓
client.evals.runs.create()
    ↓
Azure OpenAI Service receives:
    - Evaluation group ID (template)
    - Data source (formatted data)
    - Metadata
    ↓
Service queues evaluation job
    ↓
Returns eval_run object with:
    - run_id
    - status: "queued"
    ↓
Job executes asynchronously:
    - Applies graders to each row
    - Stores results
    ↓
Status changes: "queued" → "in_progress" → "completed"
    ↓
Client polls with client.evals.runs.retrieve()
    ↓
Eventually retrieves results
```

---

## Key Points

1. **Asynchronous Operation**: The API call returns immediately; actual evaluation happens in the background

2. **Data Transformation**: Raw DataFrame is transformed into nested JSON matching the evaluation schema

3. **Two-Step Process**: 
   - First: Create eval group (template) with `client.evals.create()`
   - Second: Create eval run (execution) with `client.evals.runs.create()`

4. **Polling Required**: After creation, must poll `client.evals.runs.retrieve()` to get results

5. **Remote Execution**: Evaluation runs on Azure OpenAI servers, not locally

6. **Status Lifecycle**: 
   - `"queued"` → Waiting to start
   - `"in_progress"` → Currently evaluating
   - `"completed"` → Finished successfully
   - `"failed"` → Error occurred

---

## Related Functions

| Function | Purpose |
|----------|---------|
| `_begin_single_aoai_evaluation()` | Creates eval group and starts eval run |
| `_get_data_source()` | Formats DataFrame into JSONL data source |
| `_begin_eval_run()` | Wraps the `client.evals.runs.create()` call |
| `_wait_for_run_conclusion()` | Polls until run completes |
| `_get_evaluation_run_results()` | Retrieves final results after completion |

---

## Summary

**`client.evals.runs.create()` initiates a remote evaluation job** on Azure OpenAI's service by:

1. ✅ Sending formatted evaluation data
2. ✅ Referencing a previously created evaluation group (template)
3. ✅ Receiving a run ID to track the job
4. ✅ Allowing asynchronous processing on the server
5. ✅ Requiring later polling to retrieve results

This is fundamentally different from local evaluators, which execute immediately and synchronously in your Python environment.
