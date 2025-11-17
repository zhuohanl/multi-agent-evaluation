# https://github.com/Azure-Samples/azureai-samples/blob/main/scenarios/evaluate/Supported_Evaluation_Metrics/Agent_Evaluation/Evaluate_SK_Chat_Completion_Agent.ipynb


import os
import asyncio
from typing import Annotated
import json
from pprint import pprint

from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.functions import kernel_function
from semantic_kernel.agents import ChatCompletionAgent

from azure.ai.evaluation import SKAgentConverter, evaluate
from azure.ai.evaluation import (
    ToolCallAccuracyEvaluator,
    AzureOpenAIModelConfiguration,
    IntentResolutionEvaluator,
    TaskAdherenceEvaluator,
)

from dotenv import load_dotenv
load_dotenv()


def _create_azure_chat_completion():
    return AzureChatCompletion(
        service_id=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"), 
        deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"), 
        api_key=os.getenv("AZURE_OPENAI_API_KEY"), 
    )


# This is a sample plugin that provides tools
class MenuPlugin:
    """A sample Menu Plugin used for the concept sample."""

    @kernel_function(description="Provides a list of specials from the menu.")
    def get_specials(self) -> Annotated[str, "Returns the specials from the menu."]:
        return """
        Special Soup: Clam Chowder
        Special Salad: Cobb Salad
        Special Drink: Chai Tea
        """

    @kernel_function(description="Provides the price of the requested menu item.")
    def get_item_price(
        self, menu_item: Annotated[str, "The name of the menu item."]
    ) -> Annotated[str, "Returns the price of the menu item."]:
        _ = menu_item  # This is just to simulate a function that uses the input.
        return "$9.99"


async def prepare_eval_data(agent, thread, turn_index, output_file):

    # Get the avaiable turn indices for the thread,
    # useful for selecting a specific turn for evaluation
    turn_indices = await SKAgentConverter._get_thread_turn_indices(thread=thread)
    print(f"Available turn indices: {turn_indices}")

    converter = SKAgentConverter()

    # Get a single agent run data
    evaluation_data_single_run = await converter.convert(
        thread=thread,
        turn_index=turn_index,  # Specify the turn index you want to evaluate
        agent=agent,  # Pass it to include the instructions and plugins in the evaluation data
    )

    file_name = output_file
    # Save the agent thread data to a JSONL file (all turns)
    evaluation_data = await converter.prepare_evaluation_data(threads=[thread], filename=file_name, agent=agent)
    # print(json.dumps(evaluation_data, indent=4))
    len(evaluation_data)  # number of turns in the thread


def run_eval(data_file_name):

    # Set up evaluators
    model_config = AzureOpenAIModelConfiguration(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )

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

    pprint(f'AI Foundary URL: {response.get("studio_url")}')


async def main():
    # Create the agent by directly providing the chat completion service
    agent = ChatCompletionAgent(
        service=_create_azure_chat_completion(),
        name="Chef",
        instructions="Answer questions about the menu.",
        plugins=[MenuPlugin()],
    )

    thread = None

    user_inputs = [
        "Hello",
        "What is the special drink today?",
        "What does that cost?",
        "Thank you",
    ]

    for user_input in user_inputs:
        response = await agent.get_response(messages=user_input, thread=thread)
        print(f"## User: {user_input}")
        print(f"## {response.name}: {response}\n")
        thread = response.thread
    
    # Ensure the data directory exists
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    output_file = os.path.join(data_dir, "evaluation_data.jsonl")
    
    await prepare_eval_data(
        agent=agent,
        thread=thread,
        turn_index=2,  # Specify the turn index you want to evaluate
        output_file=output_file,
    )

    # run_eval(data_file_name=output_file)


if __name__ == "__main__":
    asyncio.run(main())