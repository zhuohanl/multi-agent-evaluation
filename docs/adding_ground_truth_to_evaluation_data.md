# Adding Ground Truth to Evaluation Data

## Question: How do I add ground truth for evaluators like SimilarityEvaluator, F1ScoreEvaluator, and RougeScoreEvaluator?

## Understanding the Generated Data Structure

### What SKAgentConverter Provides Automatically ✅

When you use `SKAgentConverter.prepare_evaluation_data()`, it generates JSONL data with:

```json
{
  "query": [...conversation history + current user input...],
  "response": [...agent output including tool calls...],
  "tool_definitions": [...available tools/functions...]
}
```

**Included automatically:**
- ✅ **`query`**: Conversation history + system prompt + current user input
- ✅ **`response`**: Agent's actual output (messages, tool calls, tool results)
- ✅ **`tool_definitions`**: Available tools and their schemas

**NOT included:**
- ❌ **`ground_truth`**: Expected/ideal answer

### Why Ground Truth Isn't Generated Automatically

**The converter can't automatically generate ground truth because it doesn't know what the "correct" answer should be.** Ground truth requires:
- Human judgment
- Pre-defined expected outputs
- Domain expertise

## When You Need Ground Truth

### Evaluators That DON'T Need Ground Truth (Quality Assessors):
- ✅ `IntentResolutionEvaluator` - "Did the agent understand the user?"
- ✅ `ToolCallAccuracyEvaluator` - "Did it call the right tools?"
- ✅ `TaskAdherenceEvaluator` - "Did it follow instructions?"
- ✅ `CoherenceEvaluator` - "Is the response coherent?"
- ✅ `FluencyEvaluator` - "Is the language fluent?"

### Evaluators That REQUIRE Ground Truth (Correctness Comparators):
- ❌ `F1ScoreEvaluator` - Compares word overlap with expected answer
- ❌ `SimilarityEvaluator` - Compares semantic similarity
- ❌ `RougeScoreEvaluator` - Measures ROUGE scores against reference
- ❌ `BleuScoreEvaluator` - Measures BLEU scores against reference
- ❌ `MeteorScoreEvaluator` - Measures METEOR scores against reference
- ❌ `ResponseCompletenessEvaluator` - Checks completeness vs. expected answer

## How to Add Ground Truth

### Option 1: Add Ground Truth After Data Generation (Recommended)

This approach keeps data preparation and ground truth definition separate:

```python
import json

async def add_ground_truth_to_eval_data(input_file, output_file):
    """Enhance evaluation data with ground truth"""
    
    # Define expected answers for each conversation turn
    ground_truths = [
        "A friendly greeting acknowledging the user and offering menu assistance",
        "The special drink today is Chai Tea",
        "The price is $9.99",
        "A polite acknowledgment thanking the user"
    ]
    
    enhanced_data = []
    with open(input_file, 'r') as f:
        for idx, line in enumerate(f):
            data = json.loads(line)
            # Add ground truth field
            data['ground_truth'] = ground_truths[idx] if idx < len(ground_truths) else ""
            enhanced_data.append(data)
    
    # Write enhanced data back to file
    with open(output_file, 'w') as f:
        for item in enhanced_data:
            f.write(json.dumps(item) + '\n')
    
    print(f"Enhanced data saved to {output_file}")

# Usage in your workflow
async def main():
    # ... existing agent conversation code ...
    
    # First, generate base evaluation data
    base_file = "data/evaluation_data.jsonl"
    await converter.prepare_evaluation_data(
        threads=[thread], 
        filename=base_file, 
        agent=agent
    )
    
    # Then, add ground truth
    enhanced_file = "data/evaluation_data_with_ground_truth.jsonl"
    await add_ground_truth_to_eval_data(base_file, enhanced_file)
    
    # Use enhanced file for evaluation
    run_eval(data_file_name=enhanced_file)
```

### Option 2: Inline Ground Truth Addition

Add ground truth immediately after generating the base data:

```python
async def prepare_eval_data_with_ground_truth(agent, thread, output_file):
    """Generate evaluation data and add ground truth in one step"""
    
    converter = SKAgentConverter()
    
    # Step 1: Generate base evaluation data
    await converter.prepare_evaluation_data(
        threads=[thread], 
        filename=output_file, 
        agent=agent
    )
    
    # Step 2: Define expected answers for each turn
    # Map turn index to ground truth
    ground_truths = {
        0: "A friendly greeting acknowledging the user and offering menu assistance",
        1: "The special drink today is Chai Tea",
        2: "The price of Chai Tea is $9.99",
        3: "A polite acknowledgment thanking the user"
    }
    
    # Step 3: Load, enhance, and save
    enhanced_data = []
    with open(output_file, 'r') as f:
        for idx, line in enumerate(f):
            data = json.loads(line)
            data['ground_truth'] = ground_truths.get(idx, "")
            enhanced_data.append(data)
    
    # Overwrite with enhanced data
    with open(output_file, 'w') as f:
        for item in enhanced_data:
            f.write(json.dumps(item) + '\n')
    
    print(f"Evaluation data with ground truth saved to {output_file}")
```

### Option 3: Use a Separate Ground Truth File

Keep ground truth definitions in a separate JSON file for reusability:

**ground_truth_definitions.json:**
```json
{
    "greeting": "A friendly greeting acknowledging the user and offering menu assistance",
    "special_drink": "The special drink today is Chai Tea",
    "price": "$9.99",
    "thank_you": "A polite acknowledgment thanking the user"
}
```

**Load and merge:**
```python
import json

def add_ground_truth_from_file(eval_data_file, ground_truth_file, output_file, mapping):
    """
    Merge ground truth from separate file
    
    Args:
        eval_data_file: Path to evaluation JSONL file
        ground_truth_file: Path to ground truth JSON file
        output_file: Path to output enhanced JSONL file
        mapping: List mapping turn index to ground truth key
                 e.g., [0: "greeting", 1: "special_drink", ...]
    """
    # Load ground truth definitions
    with open(ground_truth_file, 'r') as f:
        ground_truths = json.load(f)
    
    # Enhance evaluation data
    enhanced_data = []
    with open(eval_data_file, 'r') as f:
        for idx, line in enumerate(f):
            data = json.loads(line)
            gt_key = mapping.get(idx)
            data['ground_truth'] = ground_truths.get(gt_key, "") if gt_key else ""
            enhanced_data.append(data)
    
    # Save enhanced data
    with open(output_file, 'w') as f:
        for item in enhanced_data:
            f.write(json.dumps(item) + '\n')

# Usage
mapping = {
    0: "greeting",
    1: "special_drink", 
    2: "price",
    3: "thank_you"
}

add_ground_truth_from_file(
    "data/evaluation_data.jsonl",
    "data/ground_truth_definitions.json",
    "data/evaluation_data_enhanced.jsonl",
    mapping
)
```

## Using Ground Truth Evaluators

Once you have ground truth in your data, use evaluators that compare responses:

```python
from azure.ai.evaluation import (
    F1ScoreEvaluator,
    SimilarityEvaluator,
    RougeScoreEvaluator,
    BleuScoreEvaluator,
    IntentResolutionEvaluator,
    ToolCallAccuracyEvaluator,
    AzureOpenAIModelConfiguration
)

def run_eval_with_ground_truth(data_file_name):
    """Run evaluation with both quality and correctness evaluators"""
    
    # Model config for AI-assisted evaluators
    model_config = AzureOpenAIModelConfiguration(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )
    
    # Quality evaluators (don't need ground truth)
    intent_resolution = IntentResolutionEvaluator(model_config=model_config)
    tool_call_accuracy = ToolCallAccuracyEvaluator(model_config=model_config)
    
    # Correctness evaluators (need ground truth)
    f1_score = F1ScoreEvaluator()
    similarity = SimilarityEvaluator(model_config=model_config)
    rouge = RougeScoreEvaluator()
    bleu = BleuScoreEvaluator()
    
    response = evaluate(
        data=data_file_name,
        evaluators={
            # Quality assessors
            "intent_resolution": intent_resolution,
            "tool_call_accuracy": tool_call_accuracy,
            # Correctness comparators
            "f1_score": f1_score,
            "similarity": similarity,
            "rouge": rouge,
            "bleu": bleu,
        },
        evaluator_config={
            # Map columns for ground truth evaluators
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
            },
            "rouge": {
                "column_mapping": {
                    "answer": "${data.response}",
                    "ground_truth": "${data.ground_truth}"
                }
            },
            "bleu": {
                "column_mapping": {
                    "answer": "${data.response}",
                    "ground_truth": "${data.ground_truth}"
                }
            }
        },
        azure_ai_project=os.environ["AZURE_AI_PROJECT"]
    )
    
    print(f"Evaluation complete!")
    print(f"View results: {response.get('studio_url')}")
    return response
```

## Complete Working Example

Here's a full example integrating ground truth into your chef agent evaluation:

```python
import os
import asyncio
import json
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.agents import ChatCompletionAgent
from azure.ai.evaluation import SKAgentConverter, evaluate
from azure.ai.evaluation import (
    IntentResolutionEvaluator,
    ToolCallAccuracyEvaluator,
    F1ScoreEvaluator,
    SimilarityEvaluator,
    AzureOpenAIModelConfiguration,
)

async def prepare_eval_data_with_ground_truth(agent, thread, output_file):
    """Generate evaluation data with ground truth"""
    
    converter = SKAgentConverter()
    
    # Generate base data
    await converter.prepare_evaluation_data(
        threads=[thread],
        filename=output_file,
        agent=agent
    )
    
    # Define ground truths for each turn
    ground_truths = {
        0: "A friendly greeting acknowledging the user",
        1: "The special drink is Chai Tea",
        2: "The price is $9.99",
        3: "You're welcome"
    }
    
    # Add ground truth to each row
    enhanced_data = []
    with open(output_file, 'r') as f:
        for idx, line in enumerate(f):
            data = json.loads(line)
            data['ground_truth'] = ground_truths.get(idx, "")
            enhanced_data.append(data)
    
    # Save enhanced data
    with open(output_file, 'w') as f:
        for item in enhanced_data:
            f.write(json.dumps(item) + '\n')
    
    print(f"✅ Created evaluation data with ground truth: {output_file}")
    return output_file


def run_eval_with_all_metrics(data_file):
    """Run both quality and correctness evaluations"""
    
    model_config = AzureOpenAIModelConfiguration(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )
    
    # Initialize all evaluators
    intent_resolution = IntentResolutionEvaluator(model_config=model_config)
    tool_call_accuracy = ToolCallAccuracyEvaluator(model_config=model_config)
    f1_score = F1ScoreEvaluator()
    similarity = SimilarityEvaluator(model_config=model_config)
    
    response = evaluate(
        data=data_file,
        evaluators={
            "intent_resolution": intent_resolution,
            "tool_call_accuracy": tool_call_accuracy,
            "f1_score": f1_score,
            "similarity": similarity,
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
        },
        azure_ai_project=os.environ["AZURE_AI_PROJECT"]
    )
    
    print(f"\n✅ Evaluation Complete!")
    print(f"📊 View results in Azure AI Studio: {response.get('studio_url')}")
    return response


async def main():
    # Create agent
    agent = ChatCompletionAgent(
        service=AzureChatCompletion(...),
        name="Chef",
        instructions="Answer questions about the menu.",
        plugins=[MenuPlugin()],
    )
    
    # Run conversation
    thread = None
    user_inputs = [
        "Hello",
        "What is the special drink today?",
        "What does that cost?",
        "Thank you",
    ]
    
    for user_input in user_inputs:
        response = await agent.get_response(messages=user_input, thread=thread)
        print(f"User: {user_input}")
        print(f"{response.name}: {response}\n")
        thread = response.thread
    
    # Prepare evaluation data WITH ground truth
    output_file = "data/evaluation_data_with_ground_truth.jsonl"
    await prepare_eval_data_with_ground_truth(agent, thread, output_file)
    
    # Run evaluation with all metrics
    run_eval_with_all_metrics(output_file)


if __name__ == "__main__":
    asyncio.run(main())
```

## Summary

| What | Source | Required For |
|------|--------|-------------|
| `query` | ✅ Auto-generated by SKAgentConverter | All evaluators |
| `response` | ✅ Auto-generated by SKAgentConverter | All evaluators |
| `tool_definitions` | ✅ Auto-generated by SKAgentConverter | Tool-related evaluators |
| `ground_truth` | ❌ **Must add manually** | F1Score, Similarity, ROUGE, BLEU, METEOR, ResponseCompleteness |

**Key Takeaway:** SKAgentConverter gives you `query` and `response`, but you must manually add `ground_truth` if you want to use evaluators that compare responses against expected answers.

## Best Practices

1. **Keep ground truth definitions separate** - Use a JSON file for reusability
2. **Be specific with ground truth** - More detailed expected answers = better evaluation
3. **Match ground truth granularity** - Match the level of detail in your agent's responses
4. **Version your ground truth** - Track changes to expected answers over time
5. **Use both evaluator types** - Combine quality assessors (no ground truth) with correctness comparators (with ground truth) for comprehensive evaluation

## See Also

- [Official Evaluation SDK Documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/evaluate-sdk)
- [Understanding Evaluator Types](./evaluate_high_level_overview.md)
- [Complete Evaluator Catalog](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/observability#what-are-evaluators)
