import json
import re
import sys
from pathlib import Path
from typing import Optional

from utility.function import *

MAX_VERDICT_ATTEMPTS = 3

ANSWER_PATTERN = re.compile(r"answer[\s*_`\"':]*\b(yes|no)\b", re.IGNORECASE)
BARE_VERDICT_PATTERN = re.compile(r"^[\s*_`\"':.]*(yes|no)[\s*_`\"':.]*$", re.IGNORECASE)


class LMAgent:
    """
    LMAgent class for neuro-based analysis
    """

    def __init__(self) -> None:
        self.total_input_token_cost = 0
        self.total_output_token_cost = 0
        self.time_cost = 0
        self.unresolved_verdicts = 0
        self.last_verdict_response = ""
        self.prompt_config_file_base = (
            Path(__file__).resolve().parent.parent.absolute() / "prompt"
        )

    def construct_general_prompt(
        self, config_file_path: str, is_propagation: bool
    ) -> Tuple[str, str]:
        """
        Construct the prompt according to prompt config file
        """
        with open(self.prompt_config_file_base / config_file_path, "r") as read_file:
            dump_config_dict = json.load(read_file)
        system_role = dump_config_dict["system_role"]
        prompt = dump_config_dict["task"]
        prompt += "\n" + "\n".join(dump_config_dict["analysis_rules"])
        prompt += "\n" + "\n".join(dump_config_dict["analysis_examples"])
        prompt += "\n" + "".join(dump_config_dict["meta_prompts"])
        prompt += "\n" + "".join(dump_config_dict["output_constraints"])
        prompt += "\n" + "\n".join(dump_config_dict["output_examples"])
        prompt += "\n" + "Here is the program:"
        return system_role, prompt

    @staticmethod
    def process_response_item_lines(
        response: str, v_type: ValueType
    ) -> List[LocalValue]:
        """
        Process the response of the model.
        """
        response_lines = response.split("\n")
        items = []
        for line in response_lines:
            comma_index = line.find(",")
            name_seg = line[:comma_index]
            line_seg = line[comma_index + 1 :]
            ind = name_seg.find(":")
            val_name = name_seg[ind + 1 :].strip()
            val_line = line_seg.split(" ")[-1]
            if val_line.isdigit():
                items.append(LocalValue(val_name, int(val_line), v_type))
        return items

    @staticmethod
    def parse_text_verdict(response: str) -> Optional[bool]:
        """
        Read the final answer from a text reply: the last `Answer:` marker,
        otherwise a last line holding only Yes or No. Yes/No words inside the
        explanation are ignored.
        """
        answers = ANSWER_PATTERN.findall(response)
        if answers:
            return answers[-1].lower() == "yes"
        lines = [line for line in response.splitlines() if line.strip()]
        if lines:
            bare = BARE_VERDICT_PATTERN.match(lines[-1])
            if bare:
                return bare.group(1).lower() == "yes"
        return None

    def query_verdict(self, message: str) -> Optional[bool]:
        """
        Ask a yes/no question, retrying unreadable replies a bounded number of times.
        :return: The verdict, or None if no readable answer was obtained
        """
        for _ in range(MAX_VERDICT_ATTEMPTS):
            response, input_token_cost, output_token_cost = self.model.infer(
                message, True
            )
            self.total_input_token_cost += input_token_cost
            self.total_output_token_cost += output_token_cost
            self.last_verdict_response = response
            verdict = self.parse_text_verdict(response)
            if verdict is not None:
                return verdict

        self.unresolved_verdicts += 1
        print(
            f"No readable verdict after {MAX_VERDICT_ATTEMPTS} attempts",
            file=sys.stderr,
        )
        return None
