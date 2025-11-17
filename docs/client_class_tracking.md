# Tracking the `client` Class in Azure AI Evaluation

## The Question
**Line 183** in `_evaluate_aoai.py`:
```python
eval_group_info = client.evals.create(...)
```

What class is `client` and where is it defined?

---

## The Answer

The `client` is either an **`AzureOpenAI`** or **`OpenAI`** client object from the OpenAI Python SDK.

---

## The Trace

### Step 1: Where `client` is Obtained (Line 166)
**File:** `_evaluate_aoai.py`

```python
# It's expected that all graders supplied for a single eval run use the same credentials
# so grab a client from the first grader.
client = list(graders.values())[0].get_client()
```

**Explanation:**
- `graders` is a dictionary: `Dict[str, AzureOpenAIGrader]`
- Takes the first grader from the dictionary
- Calls its `get_client()` method

---

### Step 2: The `get_client()` Method
**File:** `azure/ai/evaluation/_aoai/aoai_grader.py` (lines 108-137)

```python
def get_client(self) -> Any:
    """Construct an appropriate OpenAI client using this grader's model configuration.
    Returns a slightly different client depending on whether or not this grader's model
    configuration is for Azure OpenAI or OpenAI.

    :return: The OpenAI client.
    :rtype: [~openai.OpenAI, ~openai.AzureOpenAI]
    """
    default_headers = {"User-Agent": UserAgentSingleton().value}
    model_config: Union[AzureOpenAIModelConfiguration, OpenAIModelConfiguration] = self._model_config
    api_key: Optional[str] = model_config.get("api_key")

    if self._is_azure_model_config(model_config):
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=model_config["azure_endpoint"],
            api_key=api_key,
            api_version=DEFAULT_AOAI_API_VERSION,
            azure_deployment=model_config.get("azure_deployment", ""),
            azure_ad_token_provider=self._get_token_provider(self._credential) if not api_key else None,
            default_headers=default_headers,
        )
    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        base_url=model_config.get("base_url", ""),
        organization=model_config.get("organization", ""),
        default_headers=default_headers,
    )
```

**Explanation:**
- This method constructs and returns an OpenAI client
- The type depends on the model configuration:
  - **Azure OpenAI** → returns `openai.AzureOpenAI`
  - **OpenAI** → returns `openai.OpenAI`

---

### Step 3: The Client Classes (External Library)
**Package:** `openai` (OpenAI Python SDK)

The client classes are defined in the official OpenAI Python SDK:
- **`openai.AzureOpenAI`** - Client for Azure OpenAI Service
- **`openai.OpenAI`** - Client for OpenAI API

Both clients provide the `evals` attribute which is an evaluations API client.

---

## Type Declaration

Looking at the `OAIEvalRunCreationInfo` TypedDict (lines 32-45):

```python
class OAIEvalRunCreationInfo(TypedDict, total=True):
    """Configuration for an evaluator"""

    client: Union[AzureOpenAI, OpenAI]  # ← The type annotation
    eval_group_id: str
    eval_run_id: str
    grader_name_map: Dict[str, str]
    expected_rows: int
```

The `client` field is explicitly typed as `Union[AzureOpenAI, OpenAI]`.

---

## Flow Summary

```
AzureOpenAIGrader
    ↓
    stores model_config (Azure or OpenAI configuration)
    ↓
get_client() method
    ↓
    checks if model_config is for Azure or OpenAI
    ↓
    ┌─────────────────────┬─────────────────────┐
    ↓                     ↓                     ↓
Azure Config         OpenAI Config
    ↓                     ↓
creates AzureOpenAI   creates OpenAI
    ↓                     ↓
    └─────────────────────┴─────────────────────┘
                          ↓
            Returns client: Union[AzureOpenAI, OpenAI]
                          ↓
            Used to call client.evals.create()
```

---

## The API Call (Line 183)

```python
eval_group_info = client.evals.create(
    data_source_config=data_source_config, 
    testing_criteria=grader_list, 
    metadata={"is_foundry_eval": "true"}
)
```

**What this does:**
- Uses the OpenAI SDK's evaluations API
- Creates an evaluation group with:
  - Data source configuration (where the data comes from)
  - Testing criteria (the graders/evaluators to run)
  - Metadata for tracking
- Returns evaluation group info including an ID

---

## Key Takeaway

The `client` at line 183 is an **OpenAI SDK client** (`AzureOpenAI` or `OpenAI` class) that was created by calling `get_client()` on an `AzureOpenAIGrader` instance. This client provides access to OpenAI's evaluation APIs through the `evals` attribute.
