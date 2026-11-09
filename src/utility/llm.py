import json
import sys
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
FIREWORKS_MODEL_PREFIX = "accounts/fireworks/models/"
SUPPORTED_MODELS = ["nemotron-lightning-3p5-30b-a3b", "deepseek-v4p1-flash"]
REASONING_EFFORTS = ["none", "low", "medium", "high", "max"]

REQUEST_TIMEOUT_SECONDS = 180
MAX_RETRIES = 5
# Reasoning models spend output tokens on the trace before the final answer.
MAX_OUTPUT_TOKENS = 16384


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    raw_content: str
    reasoning_content: Optional[str]
    finish_reason: Optional[str]


def strip_reasoning(text: str) -> str:
    """
    Remove a reasoning trace from model output, leaving the final answer.
    A response cut off before </think> has no final answer and yields "".
    """
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    elif "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def complete(
    api_key: str,
    model_name: str,
    messages: List[Dict[str, str]],
    temperature: float,
    reasoning_effort: Optional[str] = None,
) -> Completion:
    """
    Run a chat completion on Fireworks.
    :return: The final answer, billed token counts and raw reply details
    """
    model = (
        model_name
        if model_name.startswith("accounts/")
        else FIREWORKS_MODEL_PREFIX + model_name
    )
    client = OpenAI(
        api_key=api_key,
        base_url=FIREWORKS_BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )
    extra_body = {}
    if reasoning_effort is not None:
        extra_body["reasoning_effort"] = reasoning_effort
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=MAX_OUTPUT_TOKENS,
        extra_body=extra_body,
    )
    choice = response.choices[0]
    raw_content = choice.message.content or ""
    usage = response.usage
    return Completion(
        text=strip_reasoning(raw_content),
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        raw_content=raw_content,
        reasoning_content=getattr(choice.message, "reasoning_content", None),
        finish_reason=choice.finish_reason,
    )


class LLM:
    """
    An online inference model served by Fireworks
    """

    def __init__(
        self,
        online_model_name: str,
        api_key: str,
        temperature: float,
        system_role="",
    ) -> None:
        """
        Initialize the LLM with model name, Fireworks key, and temperature.
        :param online_model_name: Name of the online model to use
        :param api_key: API key for Fireworks
        :param temperature: Temperature setting for the model
        """
        self.online_model_name = online_model_name
        self.api_key = api_key
        self.temperature = temperature
        self.systemRole = system_role
        self.trace_file: Optional[str] = None
        self.trace_label = ""
        self.reasoning_effort: Optional[str] = None

    def _trace(self, record: dict) -> None:
        if self.trace_file:
            record = {"agent": self.trace_label, **record}
            with open(self.trace_file, "a") as f:
                f.write(json.dumps(record) + "\n")

    def infer(self, message: str, is_measure_cost: bool = True) -> Tuple[str, int, int]:
        """
        Perform inference using the specified online model.

        Transient failures that outlast the client's retries yield an empty
        output for this call. Configuration errors (bad key, unavailable
        model, invalid request) are raised.
        :param message: The input message for the model
        :param is_measure_cost: Flag to measure token cost
        :return: Tuple containing the output, input token cost, and output token cost
        """
        model_input = [
            {"role": "system", "content": self.systemRole},
            {"role": "user", "content": message},
        ]
        try:
            completion = complete(
                self.api_key,
                self.online_model_name,
                model_input,
                self.temperature,
                self.reasoning_effort,
            )
        except (APIConnectionError, InternalServerError, RateLimitError) as error:
            print(f"Inference failed after retries: {error}", file=sys.stderr)
            self._trace({"prompt": message, "error": str(error)})
            return "", 0, 0

        self._trace({"prompt": message, **asdict(completion)})
        if not is_measure_cost:
            return completion.text, 0, 0
        return completion.text, completion.input_tokens, completion.output_tokens
