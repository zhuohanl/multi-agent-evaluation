import argparse
import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from azure.ai.evaluation import (
    AzureOpenAIModelConfiguration,
    CoherenceEvaluator,
    Conversation,
    Message,
    TaskAdherenceEvaluator,
)
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent

from step3a_group_chat_human_in_the_loop import (
    create_group_chat_orchestration,
    get_agents,
)

DEFAULT_DATASET_PATH = Path(__file__).parent / "data" / "group_chat_eval_dataset.jsonl"


@dataclass
class EvaluationScenario:
    name: str
    task: str
    human_replies: list[str] = field(default_factory=list)
    acceptance_criteria: str | None = None
    max_rounds: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvaluationScenario":
        return cls(
            name=raw.get("name") or raw["task"][:50],
            task=raw["task"],
            human_replies=list(raw.get("human_replies", [])),
            acceptance_criteria=raw.get("acceptance_criteria"),
            max_rounds=int(raw.get("max_rounds", 5)),
            metadata={k: v for k, v in raw.items() if k not in {"name", "task", "human_replies", "acceptance_criteria", "max_rounds"}},
        )


@dataclass
class ScenarioEvaluation:
    scenario: EvaluationScenario
    transcript: list[Message]
    metrics: dict[str, Any]
    raw_results: dict[str, Any]


def _ensure_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable '{name}' must be set for evaluation.")
    return value


def build_model_config() -> AzureOpenAIModelConfiguration:
    endpoint = _ensure_env_var("AZURE_OPENAI_ENDPOINT")
    api_key = _ensure_env_var("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_EVAL_DEPLOYMENT_NAME") or _ensure_env_var("AZURE_OPENAI_DEPLOYMENT_NAME")
    api_version = _ensure_env_var("AZURE_OPENAI_API_VERSION")
    return AzureOpenAIModelConfiguration(
        azure_endpoint=endpoint,
        api_key=api_key,
        azure_deployment=deployment,
        api_version=api_version,
    )


def load_scenarios(path: Path) -> list[EvaluationScenario]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    scenarios: list[EvaluationScenario] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            scenarios.append(EvaluationScenario.from_dict(data))
    if not scenarios:
        raise ValueError(f"No scenarios were found in {path}")
    return scenarios


def _chat_message_to_text(message: ChatMessageContent) -> str:
    content = message.content
    if content:
        return content
    items = getattr(message, "items", None)
    if items:
        parts: list[str] = []
        for item in items:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
    return ""


def _transcript_to_messages(transcript: Iterable[ChatMessageContent]) -> list[Message]:
    messages: list[Message] = []
    for entry in transcript:
        text = _chat_message_to_text(entry).strip()
        if not text:
            continue
        role = entry.role if isinstance(entry.role, str) else entry.role.value
        if role.lower() == "user":
            mapped_role = "user"
        elif role.lower() == "system":
            mapped_role = "system"
        else:
            mapped_role = "assistant"
        name = entry.name or ("User" if mapped_role == "user" else "Agent")
        prefix = f"[{name}] " if name and name not in {"User", "System"} else ""
        messages.append({"role": mapped_role, "content": prefix + text})
    return messages


def _format_conversation_for_prompt(messages: Sequence[Message]) -> str:
    lines: list[str] = []
    for msg in messages:
        speaker = msg.get("role", "assistant").upper()
        lines.append(f"{speaker}: {msg.get('content', '')}")
    return "\n".join(lines)


class GroupChatEvaluationRunner:
    def __init__(self, model_config: AzureOpenAIModelConfiguration) -> None:
        self._task_adherence = TaskAdherenceEvaluator(model_config=model_config)
        self._coherence = CoherenceEvaluator(model_config=model_config)
        self._task_adherence_async = self._task_adherence._to_async()
        self._coherence_async = self._coherence._to_async()

    async def evaluate(self, scenario: EvaluationScenario) -> ScenarioEvaluation:
        transcript: list[ChatMessageContent] = []
        initial_user_message = ChatMessageContent(role=AuthorRole.USER, content=scenario.task, name="User")
        transcript.append(initial_user_message)

        replies = iter(scenario.human_replies)

        async def scripted_human(_: ChatHistory) -> ChatMessageContent:
            try:
                reply = next(replies)
            except StopIteration:
                reply = scenario.human_replies[-1] if scenario.human_replies else ""
            message = ChatMessageContent(role=AuthorRole.USER, content=reply, name="User")
            transcript.append(message)
            return message

        def capture_agent(message: ChatMessageContent) -> None:
            transcript.append(message)

        orchestration = create_group_chat_orchestration(
            agents=get_agents(),
            human_response_fn=scripted_human,
            agent_response_fn=capture_agent,
            max_rounds=scenario.max_rounds,
        )

        runtime = InProcessRuntime()
        runtime.start()
        try:
            result = await orchestration.invoke(task=scenario.task, runtime=runtime)
            await result.get()
        finally:
            await runtime.stop_when_idle()

        messages = _transcript_to_messages(transcript)
        if not messages:
            raise RuntimeError("No conversation messages were captured during evaluation run.")
        formatted_query = _format_conversation_for_prompt(messages)
        final_response = messages[-1]["content"]

        task_adherence_result = await self._task_adherence_async(query=formatted_query, response=final_response)
        coherence_result = await self._coherence_async(conversation=Conversation(messages=messages))

        metrics = {
            "task_adherence": task_adherence_result.get("task_adherence"),
            "coherence": coherence_result.get("coherence"),
        }

        raw_results = {
            "task_adherence": task_adherence_result,
            "coherence": coherence_result,
        }

        return ScenarioEvaluation(
            scenario=scenario,
            transcript=messages,
            metrics=metrics,
            raw_results=raw_results,
        )


def _summarize(result: ScenarioEvaluation) -> str:
    task_score = result.metrics.get("task_adherence")
    coherence_score = result.metrics.get("coherence")
    parts = [f"scenario={result.scenario.name}"]
    if task_score is not None:
        parts.append(f"task_adherence={task_score}")
    if coherence_score is not None:
        parts.append(f"coherence={coherence_score}")
    return ", ".join(parts)


async def run_cli(dataset_path: Path, output_path: Path | None, limit: int | None) -> list[ScenarioEvaluation]:
    scenarios = load_scenarios(dataset_path)
    if limit is not None:
        scenarios = scenarios[:limit]
    runner = GroupChatEvaluationRunner(build_model_config())
    results: list[ScenarioEvaluation] = []
    for scenario in scenarios:
        print(f"Running scenario: {scenario.name}")
        evaluation = await runner.evaluate(scenario)
        print(f"  -> { _summarize(evaluation) }")
        results.append(evaluation)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for evaluation in results:
                record = {
                    "scenario": evaluation.scenario.name,
                    "task": evaluation.scenario.task,
                    "acceptance_criteria": evaluation.scenario.acceptance_criteria,
                    "transcript": evaluation.transcript,
                    "metrics": evaluation.metrics,
                    "raw_results": evaluation.raw_results,
                }
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
        print(f"Saved evaluation details to {output_path}")

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the Step 3a multi-agent orchestration.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help=f"Path to JSONL dataset (default: {DEFAULT_DATASET_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write per-scenario evaluation details as JSONL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optionally limit the number of scenarios to evaluate.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_cli(dataset_path=args.dataset, output_path=args.output, limit=args.limit))


if __name__ == "__main__":
    main()
