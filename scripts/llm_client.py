"""LLM provider abstraction layer.

This module provides a thin wrapper so that other services can be swapped in
without touching the rest of the pipeline. Currently supports OpenAI by
default, and allows future providers (e.g. Anthropic) to be added easily.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class LLMClientError(RuntimeError):
    """Raised when an LLM provider is misconfigured."""


@dataclass
class BaseLLMClient:
    model: str

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:  # pragma: no cover - interface only
        raise NotImplementedError


class OpenAIClient(BaseLLMClient):
    def __post_init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMClientError(
                "OPENAI_API_KEY is not set. Run the setup script or export the key manually."
            )
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(
                "openai パッケージが見つかりません。requirements.txt の依存関係をインストールしてください。"
            ) from exc

        self._client = OpenAI()

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""


class AnthropicClient(BaseLLMClient):
    def __post_init__(self) -> None:
        try:
            from anthropic import Anthropic  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(
                "anthropic パッケージが見つかりません。`pip install anthropic` を実行してください。"
            ) from exc

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMClientError("ANTHROPIC_API_KEY is not set.")

        self._client = Anthropic()

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        # Anthropic は system prompt を.messagesに含める必要がある
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # 応答は list[str|dict] の場合があるため safe join
        parts = []
        for block in resp.content:
            if isinstance(block, str):
                parts.append(block)
            else:
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip()


class GeminiClient(BaseLLMClient):
    def __post_init__(self) -> None:
        try:
        import google.generativeai as genai  # type: ignore
        from google.generativeai.types import GenerationConfig  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(
                "google-generativeai パッケージが見つかりません。`pip install google-generativeai` を実行してください。"
            ) from exc

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise LLMClientError("GEMINI_API_KEY (または GOOGLE_API_KEY) が設定されていません。")

        genai.configure(api_key=api_key)
        self._genai = genai
        self._GenerationConfig = GenerationConfig
        self._model = genai.GenerativeModel(self.model)

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        generation_config = self._GenerationConfig(max_output_tokens=max_tokens)
        response = self._model.generate_content(
            prompt,
            generation_config=generation_config,
        )
        # google-generativeai exposes convenience property .text
        return (response.text or "").strip()


def create_llm_client(provider: str, model: str) -> BaseLLMClient:
    provider = provider.lower().strip()
    if provider in {"openai", "gpt"}:
        client = OpenAIClient(model=model)
    elif provider in {"anthropic", "claude"}:
        client = AnthropicClient(model=model)
    elif provider in {"gemini", "google"}:
        client = GeminiClient(model=model)
    else:
        raise LLMClientError(
            f"Unsupported LLM provider '{provider}'. 対応している値: openai, anthropic, gemini"
        )
    return client
