"""
ZenGuard is a class that represents the ZenGuard object. It is used to connect to ZenGuard AI API and its services.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx
from openai import OpenAI
from tqdm import tqdm

from zenguard.ai_clients.openai import ChatWithZenguard
from zenguard.pentest.prompt_injections import (config, prompting, run,
                                                scoring, visualization)


class SupportedLLMs:
    CHATGPT = "chatgpt"


@dataclass
class Credentials:
    api_key: str
    llm_api_key: Optional[str] = None


@dataclass
class ZenGuardConfig:
    credentials: Credentials
    ai_client: Optional[OpenAI] = None
    llm: Optional[SupportedLLMs] = None


class Detector(str, Enum):
    ALLOWED_TOPICS = "allowed_subjects"
    BANNED_TOPICS = "banned_subjects"
    PROMPT_INJECTION = "prompt_injection"
    KEYWORDS = "keywords"
    PII = "pii"
    SECRETS = "secrets"
    TOXICITY = "toxicity"


class Endpoint(Enum):
    ZENGUARD = "zenguard"
    OPENAI = "openai"

class ZenGuard:
    """
    ZenGuard is a class that represents the ZenGuard object.
    It is used to connect to ZenGuard AI API and its services.
    """

    def __init__(self, config: ZenGuardConfig):
        api_key = config.credentials.api_key
        if type(api_key) != str or api_key == '':
            raise ValueError("The API key must be a string type and not empty.")
        self._api_key = api_key
        self._backend = "https://api.zenguard.ai/"

        if config.llm == SupportedLLMs.CHATGPT:
            self.chat = ChatWithZenguard(
                client=config.ai_client,
                zenguard=self,
                openai_key=config.credentials.llm_api_key
            )
        elif config.llm is not None:
            raise ValueError(f"LLM {config.llm} is not supported")

    def detect(self, detectors: list[Detector], prompt: str):
        try:
            response = httpx.post(
                self._backend + "v1/detect",
                json={"messages": [prompt], "in_parallel": True, "detectors": detectors},
                headers={"x-api-key": self._api_key},
                timeout=5,
            )
        except httpx.RequestError as e:
            return {"error": str(e)}

        if response.status_code != 200:
            return {"error": str(response.json())}

        return response.json()

    def _attack_zenguard(self, detector: Detector, attacks: list[str]):
        attacks = tqdm(attacks)
        for attack in attacks:
            response = self.detect(detectors=[detector], prompt=attack["prompt"])
            if response.get("is_detected"):
                attack["result"] = "ZenGuard detected the attack"
                continue

            attack["result"] = attack["settings"]["attack_rogue_string"]

    def pentest(self, endpoint: Endpoint, detector: Detector = None):
        base_prompts = config.default_attack_config
        attack_prompts = prompting.build_prompts(base_prompts)

        if endpoint == Endpoint.ZENGUARD:
            print("\nRunning attack on ZenGuard endpoint:")
            assert (
                detector == Detector.PROMPT_INJECTION
            ), "Only prompt injection pentesting is currently supported"
            self._attack_zenguard(Detector.PROMPT_INJECTION, attack_prompts)
        elif endpoint == Endpoint.OPENAI:
            print("\nRunning attack on OpenAI endpoint:")
            run.run_prompts_api(attack_prompts, self.chat._client)

        scoring.score_attacks(attack_prompts)
        df = visualization.build_dataframe(attack_prompts)
        print(scoring.get_metrics(df, "Attack Instruction"))

    def update_detectors(self, detectors: list[Detector]):
        if len(detectors) == 0:
            return {"error": "No detectors were provided"}

        try:
            response = httpx.put(
                self._backend + "v1/detectors/update/",
                params={"detectors": [detector.value for detector in detectors]},
                headers={"x-api-key": self._api_key},
                timeout=3,
            )
        except httpx.RequestError as e:
            return {"error": str(e)}

        if response.status_code != 200:
            return {"error": str(response.json())}
