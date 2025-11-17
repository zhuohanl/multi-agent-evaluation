# Evaluator Type Analysis

## Question
Are the evaluators in `chef_agent.py` (lines 88-92) AI Graders or Evaluators? Are they `AzureOpenAIGrader` instances?

## Answer
**These are LOCAL EVALUATORS, NOT Azure OpenAI Graders.**

---

## The Evaluators in Question

```python
intent_resolution = IntentResolutionEvaluator(model_config=model_config)
tool_call_accuracy = ToolCallAccuracyEvaluator(model_config=model_config)
task_adherence = TaskAdherenceEvaluator(model_config=model_config)
```

---

## Class Hierarchy Analysis

### 1. **ToolCallAccuracyEvaluator**
**File:** `azure/ai/evaluation/_evaluators/_tool_call_accuracy/_tool_call_accuracy.py`

```python
class ToolCallAccuracyEvaluator(PromptyEvaluatorBase[Union[str, float]]):
```

**Inheritance Chain:**
```
ToolCallAccuracyEvaluator
    ↓ extends
PromptyEvaluatorBase[Union[str, float]]
    ↓ extends
EvaluatorBase[T]
```

---

### 2. **IntentResolutionEvaluator**
**File:** `azure/ai/evaluation/_evaluators/_intent_resolution/_intent_resolution.py`

```python
class IntentResolutionEvaluator(PromptyEvaluatorBase[Union[str, float]]):
```

**Inheritance Chain:**
```
IntentResolutionEvaluator
    ↓ extends
PromptyEvaluatorBase[Union[str, float]]
    ↓ extends
EvaluatorBase[T]
```

---

### 3. **TaskAdherenceEvaluator**
**File:** `azure/ai/evaluation/_evaluators/_task_adherence/_task_adherence.py`

```python
class TaskAdherenceEvaluator(PromptyEvaluatorBase[Union[str, float]]):
```

**Inheritance Chain:**
```
TaskAdherenceEvaluator
    ↓ extends
PromptyEvaluatorBase[Union[str, float]]
    ↓ extends
EvaluatorBase[T]
```

---

## Comparison: Evaluators vs AzureOpenAIGrader

### **AzureOpenAIGrader** (Remote Grader)
**File:** `azure/ai/evaluation/_aoai/aoai_grader.py`

```python
@experimental
class AzureOpenAIGrader:
    """Base class for Azure OpenAI grader wrappers."""
    
    def get_client(self) -> Any:
        # Returns OpenAI client (AzureOpenAI or OpenAI)
        # Used to make remote API calls to Azure OpenAI service
```

**Characteristics:**
- ❌ Does NOT inherit from `EvaluatorBase` or `PromptyEvaluatorBase`
- ✅ Has a `get_client()` method
- ✅ Makes **remote** API calls to Azure OpenAI evaluation service
- ✅ Returns evaluation runs that are executed on Azure
- ✅ Asynchronous: creates runs, then retrieves results later

### **PromptyEvaluatorBase** (Local Evaluator)
**File:** `azure/ai/evaluation/_evaluators/_common/_base_prompty_eval.py`

```python
class PromptyEvaluatorBase(EvaluatorBase[T]):
    """Base class for all evaluators that make use of context as an input."""
    
    def __init__(self, *, result_key: str, prompty_file: str, model_config: dict, ...):
        # Loads a prompty file
        self._flow = AsyncPrompty.load(source=self._prompty_file, ...)
```

**Characteristics:**
- ✅ Inherits from `EvaluatorBase`
- ✅ Uses `.prompty` files (local prompt templates)
- ✅ Executes **locally** in Python environment
- ✅ Calls Azure OpenAI for LLM responses, but evaluation logic runs locally
- ✅ Synchronous execution: immediate results

---

## Key Differences

| Feature | Local Evaluators | AzureOpenAIGrader |
|---------|------------------|-------------------|
| **Base Class** | `PromptyEvaluatorBase` → `EvaluatorBase` | `AzureOpenAIGrader` (no inheritance) |
| **Execution Location** | Local Python environment | Remote Azure OpenAI service |
| **Method** | Uses `.prompty` template files | Uses Azure OpenAI eval API |
| **get_client()** | ❌ No | ✅ Yes |
| **Execution Model** | Synchronous (immediate) | Asynchronous (create run → poll → retrieve) |
| **In evaluate() function** | Phase 5: `_run_callable_evaluators()` | Phase 4 & 6: `_begin_aoai_evaluation()` + `_get_evaluation_run_results()` |

---

## How They're Separated in `evaluate()`

In the `_evaluate()` function we analyzed earlier:

### **Step 2: Preprocessing**
```python
validated_data = _preprocess_data(...)
```

Inside `_preprocess_data()`, the function calls:
```python
evaluators, graders = _split_evaluators_and_grader_configs(evaluators_and_graders)
```

### **The Separation Logic**
**File:** `_evaluate_aoai.py`

```python
def _split_evaluators_and_grader_configs(
    evaluators: Dict[str, Union[Callable, AzureOpenAIGrader]],
) -> Tuple[Dict[str, Callable], Dict[str, AzureOpenAIGrader]]:
    """Split evaluators and graders."""
    
    evaluator_dict = {}
    grader_dict = {}
    
    for name, evaluator_or_grader in evaluators.items():
        if isinstance(evaluator_or_grader, AzureOpenAIGrader):
            grader_dict[name] = evaluator_or_grader  # Remote grader
        else:
            evaluator_dict[name] = evaluator_or_grader  # Local evaluator
    
    return evaluator_dict, grader_dict
```

**Your evaluators would be classified as:**
```python
isinstance(tool_call_accuracy, AzureOpenAIGrader)  # False → goes to evaluator_dict
isinstance(intent_resolution, AzureOpenAIGrader)   # False → goes to evaluator_dict
isinstance(task_adherence, AzureOpenAIGrader)      # False → goes to evaluator_dict
```

---

## Execution Flow for Your Evaluators

In `chef_agent.py`, when you call:
```python
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

**What happens:**

1. ✅ **Phase 2**: `_preprocess_data()` separates evaluators from graders
   - All 3 go into `evaluators` dict (not `graders`)

2. ✅ **Phase 3**: Execution path determination
   ```python
   need_oai_run = len(graders) > 0      # False (0 graders)
   need_local_run = len(evaluators) > 0  # True (3 evaluators)
   ```

3. ✅ **Phase 5**: Execute local evaluators
   ```python
   eval_result_df, eval_metrics, per_evaluator_results = _run_callable_evaluators(
       validated_data=validated_data
   )
   ```

4. ❌ **Phases 4 & 6**: Azure OpenAI grader phases are SKIPPED

---

## Conclusion

### **Your Evaluators Are:**
- ✅ **Local Evaluators** (not remote graders)
- ✅ Inherit from `PromptyEvaluatorBase`
- ✅ Execute locally using `.prompty` template files
- ✅ Call Azure OpenAI models for LLM judgments, but evaluation orchestration is local
- ❌ **NOT** `AzureOpenAIGrader` instances
- ❌ Do NOT use Azure OpenAI's remote evaluation service

### **They Are:**
Python-based evaluators that:
1. Load prompt templates from `.prompty` files
2. Execute evaluation logic locally
3. Use Azure OpenAI models to generate scores/judgments
4. Return results synchronously

This is the standard approach for most built-in evaluators in Azure AI Evaluation SDK.
