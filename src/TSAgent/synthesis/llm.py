from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from utility.llm import complete


class LLM(ABC):
    def __init__(self, api_key: str, temperature: float = 0, log_file: Path = None):
        self.log_file = log_file
        self.api_key = api_key
        self.temperature = temperature
        self.conversation = []
        self.index = 0

    def reset_cost(self):
        self.input_token_cost = 0
        self.output_token_cost = 0

    def set_system_role(self, role: str):
        self.conversation = [{"role": "system", "content": role}] + self.conversation

    @staticmethod
    def build_message(prompt: str, role: Literal["user", "assistant"] = "user") -> dict:
        return {
            "role": role,
            "content": prompt,
        }

    def __copy__(self):
        """
        Fork the conversation.
        """
        fork = FireworksLLM(self.api_key, self.model, self.temperature, self.log_file)
        fork.conversation = self.conversation.copy()
        fork.index = self.index
        return fork

    def log(self, message: str):
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(message + "\n")

    def query(self, prompt: str, with_history=False) -> str:
        self.index += 1
        self.conversation.append(self.build_message(prompt, role="user"))
        self.log(f"*****************Prompt Start {self.index}*****************")
        self.log(prompt)
        self.log(f"*****************Prompt End {self.index}*******************")
        text = self._query_model(with_history)
        self.log(f"*****************Response Start {self.index}*****************")
        self.log(text)
        self.log(f"*****************Response End {self.index}*******************")
        self.conversation.append(self.build_message(text, role="assistant"))
        return text

    @abstractmethod
    def _query_model(self, with_history=False) -> str:
        pass


class FireworksLLM(LLM):
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0,
        log_file: Path = None,
    ):
        super().__init__(api_key, temperature, log_file)
        self.model = model
        self.input_token_cost = 0
        self.output_token_cost = 0

    def _query_model(self, with_history=False) -> str:
        input_messages = self.conversation if with_history else [self.conversation[-1]]
        completion = complete(
            self.api_key, self.model, input_messages, self.temperature
        )
        self.input_token_cost += completion.input_tokens
        self.output_token_cost += completion.output_tokens
        return completion.text
