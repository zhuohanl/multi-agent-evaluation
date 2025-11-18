# High-Level: What Happens When You Call `evaluate()`

## The Simple Picture

```python
response = evaluate(
    data=data_file_name,              # Your test data
    evaluators={                       # Your evaluators
        "tool_call_accuracy": tool_call_accuracy,
        "intent_resolution": intent_resolution,
        "task_adherence": task_adherence,
    },
    azure_ai_project=project
)
```

**You provide:** Test data + Evaluators  
**You get back:** Scores + Metrics + Azure Studio URL

---

## What Happens Behind the Scenes (5 Main Steps)

### **Step 1: Load Your Test Data** 📊

```
Your JSONL file:
┌─────────────────────────────────────────────┐
│ {"query": "...", "response": "...", ...}    │
│ {"query": "...", "response": "...", ...}    │
│ {"query": "...", "response": "...", ...}    │
└─────────────────────────────────────────────┘
         ↓
Loaded into DataFrame (like an Excel table)
```

---

### **Step 2: Match Data Columns to Evaluator Inputs** 🔗

Each evaluator expects specific inputs. The framework automatically matches:

```
Your Data Columns          →    Evaluator Needs
─────────────────────           ───────────────
"query"                    →    query ✓
"response"                 →    response ✓
"tool_definitions"         →    tool_definitions ✓
"grounded_truth"           →    (not used by this evaluator)
```

**The evaluator's function signature determines what it needs:**
```python
IntentResolutionEvaluator(query, response, tool_definitions)
# ↑ Only looks at these 3 things
```

**This is automatic column mapping** - the framework inspects what each evaluator expects and pulls the right columns from your data.

---

### **Step 3: Run Each Row Through Each Evaluator** 🔄

For each row in your data, the framework:

```
Row 1: {"query": "Q1", "response": "R1", ...}
   ↓
   ├─→ IntentResolutionEvaluator(query="Q1", response="R1")
   │       ↓ Calls Azure OpenAI
   │       ↓ Returns: {score: 5, reason: "..."}
   │
   ├─→ ToolCallAccuracyEvaluator(query="Q1", tool_calls="...", tool_definitions="...")
   │       ↓ Calls Azure OpenAI
   │       ↓ Returns: {score: 4, reason: "..."}
   │
   └─→ TaskAdherenceEvaluator(query="Q1", response="R1")
           ↓ Calls Azure OpenAI
           ↓ Returns: {flagged: False, reason: "..."}

Row 2: {"query": "Q2", "response": "R2", ...}
   ↓ (same process)

... (continues for all rows)
```

**Runs in parallel** (default: 4 rows at once) for speed.

---

### **Step 4: What Each Evaluator Actually Does** 🤖

Inside each evaluator (e.g., `IntentResolutionEvaluator`):

```
1. Load a prompt template (intent_resolution.prompty)
   
2. Fill in the template with your data:
   ┌─────────────────────────────────────────┐
   │ You are an expert evaluator.            │
   │                                         │
   │ User Query: "What's the weather?"       │
   │ Agent Response: "The weather is sunny." │
   │                                         │
   │ Did the agent resolve the user's intent?│
   │ Rate from 1-5 and explain why.         │
   └─────────────────────────────────────────┘

3. Send this to Azure OpenAI (GPT-4, etc.)

4. LLM reads the query + response and judges:
   {
     "score": 5,
     "explanation": "The agent directly answered..."
   }

5. Return formatted result
```

**The LLM acts as an expert judge** that reads your data and scores it based on the evaluation criteria defined in the prompt template.

---

### **Step 5: Aggregate Results** 📈

After all rows are evaluated:

```
Per-Row Results:
┌────────┬─────────────────┬─────────────────┐
│ Row    │ Intent Score    │ Tool Accuracy   │
├────────┼─────────────────┼─────────────────┤
│ 0      │ 5               │ 4               │
│ 1      │ 4               │ 5               │
│ 2      │ 5               │ 3               │
└────────┴─────────────────┴─────────────────┘
         ↓
Aggregate Metrics (averaged):
{
  "intent_resolution": 4.67,
  "tool_call_accuracy": 4.00
}
```

Results are logged to Azure AI Studio for viewing.

---

## Your Key Questions Answered

### **Q1: How does the LLM know what to compare?**

**A: The evaluator's prompt template tells it exactly what to look at.**

Each evaluator has a `.prompty` file that contains instructions:

```
IntentResolutionEvaluator:
├─ Prompt says: "Look at the query and response. Did the agent resolve the user's intent?"
├─ Inputs: query, response, tool_definitions
└─ Ignores: grounded_truth (not in the prompt)

ToolCallAccuracyEvaluator:
├─ Prompt says: "Look at tool calls and tool definitions. Are they correct?"
├─ Inputs: query, tool_calls, tool_definitions
└─ Ignores: response, grounded_truth
```

### **Q2: How does it pick up if it needs grounded_truth?**

**A: By the evaluator's function signature (its parameters).**

```python
# Example: If you use GroundednessEvaluator
GroundednessEvaluator(query, response, context)
# ↑ Looks for columns: "query", "response", "context"

# If your data has "grounded_truth" instead of "context":
evaluate(
    data=data,
    evaluators={
        "groundedness": GroundednessEvaluator(...)
    },
    evaluator_config={
        "groundedness": {
            "column_mapping": {
                "context": "${data.grounded_truth}"  # Map it!
            }
        }
    }
)
```

**The evaluators you're using DON'T need grounded_truth:**
- `IntentResolutionEvaluator` - Only needs query + response
- `ToolCallAccuracyEvaluator` - Only needs tool calls + definitions
- `TaskAdherenceEvaluator` - Only needs query + response

**Other evaluators that DO need grounded_truth:**
- `GroundednessEvaluator` - Compares response against ground truth
- `RelevanceEvaluator` - Checks if response is relevant to expected answer

### **Q3: Does the LLM see the expected answer?**

**A: Only if the evaluator is designed to use it.**

Your current evaluators:
- ❌ **Don't look at expected answers**
- ✅ **Judge based on the response itself**:
  - Is the intent resolved?
  - Are tool calls correct?
  - Does it follow task requirements?

If you want comparison with expected answers, use:
```python
from azure.ai.evaluation import F1ScoreEvaluator, SimilarityEvaluator

f1_score = F1ScoreEvaluator()
# ↑ Compares response vs ground_truth word overlap

similarity = SimilarityEvaluator(model_config=model_config)
# ↑ LLM compares semantic similarity with ground_truth
```

---

## The Complete Flow (Visual)

```
YOU PROVIDE:
┌────────────────┐
│  Test Data     │ (JSONL with query, response, etc.)
│  +             │
│  Evaluators    │ (What to measure)
│  +             │
│  AI Project    │ (Where to log)
└────────────────┘
        ↓
┌─────────────────────────────────────────┐
│         evaluate() Magic Function        │
├─────────────────────────────────────────┤
│  1. Load data into DataFrame            │
│  2. Match columns to evaluator inputs   │
│  3. For each row:                       │
│     - Extract needed columns            │
│     - Call each evaluator               │
│       └─> Evaluator fills prompt        │
│           └─> Sends to Azure OpenAI     │
│               └─> LLM judges & scores   │
│  4. Collect all scores                  │
│  5. Calculate averages                  │
│  6. Log to Azure AI Studio              │
└─────────────────────────────────────────┘
        ↓
YOU GET BACK:
{
  "rows": [
    {"intent_resolution": 5, "tool_call_accuracy": 4, ...},
    {"intent_resolution": 4, "tool_call_accuracy": 5, ...}
  ],
  "metrics": {
    "intent_resolution": 4.67,
    "tool_call_accuracy": 4.00
  },
  "studio_url": "https://..."
}
```

---

## What's Really Happening with LLMs

Each evaluator is essentially asking an LLM to be a judge:

### **IntentResolutionEvaluator (Simplified)**

```
Human Equivalent:
"Hey GPT-4, here's a conversation. The user asked a question, 
and the agent responded. Did the agent understand what the user 
wanted and address it properly? Rate 1-5 and explain."

LLM Response:
"Score: 5. The agent correctly identified the user wanted weather 
information and provided a direct answer about sunny weather."
```

### **ToolCallAccuracyEvaluator (Simplified)**

```
Human Equivalent:
"Hey GPT-4, look at these tool definitions and the tool calls 
the agent made. Did it call the right tools with the right 
parameters? Rate 1-5."

LLM Response:
"Score: 4. The agent called the correct tool 'get_weather' with 
the right location parameter, but the format was slightly off."
```

---

## Key Insights

### **1. Evaluators are Specialized Judges**
Each evaluator has a specific job:
- `IntentResolutionEvaluator` → "Did you understand the user?"
- `ToolCallAccuracyEvaluator` → "Did you use tools correctly?"
- `TaskAdherenceEvaluator` → "Did you follow the rules?"

### **2. They Only Look at What They Need**
```
Your Data:
├─ query
├─ response
├─ tool_calls
├─ tool_definitions
├─ grounded_truth        ← Not used (unless you add an evaluator that needs it)
└─ context               ← Not used
```

Each evaluator's function signature = what columns it needs.

### **3. LLMs are the "Expert Evaluators"**
- You could manually review each response (slow!)
- Instead: LLMs read your data and judge it automatically
- They follow instructions in the prompt templates
- They provide scores + explanations

### **4. No Expected Answer Needed (For Your Evaluators)**
Your evaluators judge **quality** not **correctness**:
- ✓ "Did the agent understand the request?"
- ✓ "Did it use tools properly?"
- ✓ "Did it follow instructions?"

vs. evaluators that need expected answers:
- ✓ "Does the response match the ground truth?"
- ✓ "How similar is it to the expected answer?"

---

## Simple Mental Model

Think of `evaluate()` as:

```
1. A loop through your test data
2. For each row, show it to multiple expert judges (evaluators)
3. Each judge looks at specific parts and gives a score
4. Collect all scores and calculate averages
5. Save results to Azure AI Studio
```

**The "magic" is:**
- Automatic column matching (framework figures out what each evaluator needs)
- Parallel execution (runs multiple evaluations at once)
- LLM-as-a-judge (uses GPT-4 to evaluate responses)
- Structured prompts (each evaluator has a specific evaluation template)

---

## To Use Ground Truth (If Needed)

If you want to compare against expected answers:

```python
from azure.ai.evaluation import F1ScoreEvaluator

# Add to your evaluators
f1_score = F1ScoreEvaluator()

response = evaluate(
    data=data_file_name,
    evaluators={
        "tool_call_accuracy": tool_call_accuracy,
        "intent_resolution": intent_resolution,
        "f1_score": f1_score,  # ← Compares response vs grounded_truth
    },
    evaluator_config={
        "f1_score": {
            "column_mapping": {
                "answer": "${data.response}",
                "ground_truth": "${data.grounded_truth}"  # ← Tell it where to find expected answer
            }
        }
    }
)
```

---

## Bottom Line

**What you provide:**
- Test data (query, response, etc.)
- Evaluators (what to measure)

**What happens:**
- Framework loops through your data
- Each evaluator gets the columns it needs (automatic)
- LLM judges each row based on evaluation criteria
- Results are aggregated and logged

**How it picks columns:**
- Reads evaluator's function signature
- Matches parameter names to data columns
- Uses column_mapping if names don't match

**Ground truth comparison:**
- Only happens if you use evaluators designed for it
- Your current evaluators don't need it
- They judge response quality, not correctness vs. expected answer

---

## Official Microsoft Documentation

For comprehensive information about Azure AI Evaluation SDK evaluators:

### **📚 Main Evaluation Documentation**
- **[Evaluate with Azure AI Evaluation SDK](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/evaluate-sdk)**
  - Complete guide to using the evaluation SDK
  - Data requirements for different evaluator types
  - Setup instructions and examples

### **📊 Complete Evaluator Catalog**
- **[Observability in Generative AI - What are Evaluators?](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/observability#what-are-evaluators)**
  - Complete table of all available evaluators with input requirements
  - Shows which evaluators need query, response, context, ground truth, etc.

### **🎯 Evaluators by Category**

#### **Your Current Evaluators (Agentic - No Ground Truth Required):**
- **IntentResolutionEvaluator** - Requires: `query`, `response`
- **ToolCallAccuracyEvaluator** - Requires: `query`, `tool_calls` (or `response`), `tool_definitions`
- **TaskAdherenceEvaluator** - Requires: `query`, `response`, optional `tool_definitions`

**Reference:** [Agent Evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/agent-evaluators)

#### **Evaluators That REQUIRE Ground Truth:**
- **F1ScoreEvaluator** - Requires: `response`, `ground_truth`
- **SimilarityEvaluator** - Requires: `query`, `context`, `ground_truth`
- **RougeScoreEvaluator** - Requires: `response`, `ground_truth`
- **BleuScoreEvaluator** - Requires: `response`, `ground_truth`
- **GleuScoreEvaluator** - Requires: `response`, `ground_truth`
- **MeteorScoreEvaluator** - Requires: `response`, `ground_truth`
- **DocumentRetrievalEvaluator** - Requires: `ground_truth`, `retrieved_documents`
- **ResponseCompletenessEvaluator** - Requires: `response`, `ground_truth`
- **QAEvaluator** (composite) - Requires: `query`, `context`, `response`, `ground_truth`

**Reference:** [Textual Similarity Evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/textual-similarity-evaluators)

#### **RAG Evaluators (Context-Based, No Ground Truth):**
- **GroundednessEvaluator** - Requires: `query`, `context`, `response`
- **RelevanceEvaluator** - Requires: `query`, `response`
- **RetrievalEvaluator** - Requires: `query`, `context`

**Reference:** [RAG Evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators)

#### **General Quality Evaluators (No Ground Truth):**
- **CoherenceEvaluator** - Requires: `query`, `response`
- **FluencyEvaluator** - Requires: `response`

**Reference:** [General Purpose Evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/general-purpose-evaluators)

### **📋 Quick Reference: Data Requirements Table**

From the [official documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/evaluate-sdk#data-requirements-for-built-in-evaluators):

| Evaluator Category | Example Evaluators | Required Inputs |
|-------------------|-------------------|----------------|
| **Agentic** | IntentResolution, ToolCallAccuracy, TaskAdherence | query, response, (optional: tool_definitions) |
| **Textual Similarity** | F1Score, ROUGE, BLEU, GLEU, METEOR, Similarity | response, **ground_truth** |
| **RAG Quality** | Groundedness, Relevance, Retrieval | query, response, context |
| **General Quality** | Coherence, Fluency | query, response |
| **Safety** | Violence, Sexual, SelfHarm, HateUnfairness | query, response |

**Key Distinction:**
- **With Ground Truth** → Measures correctness (how close to expected answer)
- **Without Ground Truth** → Measures quality (how good is the response itself)

---

## Understanding Ground Truth Requirements

### **Your Situation:**
✅ **Your evaluators DON'T need ground truth** because they assess:
- Intent understanding (did the agent get what the user wanted?)
- Tool usage correctness (were the right tools called?)
- Task adherence (did the agent follow instructions?)

These are **quality assessments** that don't require comparing against an expected answer.

### **When You WOULD Need Ground Truth:**
If you wanted to measure:
- ❓ "How similar is the response to the expected answer?" → Use `SimilarityEvaluator`
- ❓ "What's the word overlap with the correct answer?" → Use `F1ScoreEvaluator`
- ❓ "Is the response complete compared to the ideal answer?" → Use `ResponseCompletenessEvaluator`

### **How to Use Ground Truth (If Needed):**

```python
# Your data would need a "grounded_truth" or "ground_truth" column
{"query": "What's 2+2?", "response": "4", "ground_truth": "The answer is 4"}

# Then use evaluators that compare responses
from azure.ai.evaluation import F1ScoreEvaluator, SimilarityEvaluator

f1_eval = F1ScoreEvaluator()
similarity_eval = SimilarityEvaluator(model_config=model_config)

response = evaluate(
    data=data,
    evaluators={
        "f1_score": f1_eval,
        "similarity": similarity_eval
    },
    evaluator_config={
        "f1_score": {
            "column_mapping": {
                "answer": "${data.response}",
                "ground_truth": "${data.ground_truth}"
            }
        },
        "similarity": {
            "column_mapping": {
                "query": "${data.query}",
                "response": "${data.response}",
                "ground_truth": "${data.ground_truth}"
            }
        }
    }
)
```

---

## Additional Resources

- **[Azure AI Evaluation Python SDK Reference](https://aka.ms/azureaieval-python-ref)** - API documentation
- **[Troubleshooting Guide](https://aka.ms/azureaieval-tsg)** - Common issues and solutions
- **[Evaluation Samples](https://aka.ms/aistudio/eval-samples)** - Code examples and notebooks
- **[Custom Evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/custom-evaluators)** - Build your own evaluators
