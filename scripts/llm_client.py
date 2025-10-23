"""LLM provider abstraction layer.

This module provides a thin wrapper so that other services can be swapped in
without touching the rest of the pipeline. Currently supports OpenAI by
default, and allows future providers (e.g. Anthropic) to be added easily.
"""

from __future__ import annotations

import os


class LLMClientError(RuntimeError):
    """Raised when an LLM provider is misconfigured."""


class BaseLLMClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:  # pragma: no cover - interface only
        """Return the assistant response given system and user prompts."""
        raise NotImplementedError


class OpenAIClient(BaseLLMClient):
    def __init__(self, model: str) -> None:
        super().__init__(model)
        """Initialise the OpenAI client."""
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
        """Request a chat completion from OpenAI."""
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
    def __init__(self, model: str) -> None:
        super().__init__(model)
        """Initialise the Anthropic Claude client."""
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
        """Request a Claude response and return plain text."""
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


GEMINI_DEFAULT_MAX_OUTPUT_TOKENS = 250_000


class GeminiClient(BaseLLMClient):
    def __init__(self, model: str) -> None:
        super().__init__(model)
        """Initialise the Google Gemini client."""
        self._default_max_output_tokens = GEMINI_DEFAULT_MAX_OUTPUT_TOKENS
        self._generation_config_builder = lambda max_tokens: {"max_output_tokens": max(self._default_max_output_tokens, max_tokens or 0)}
        try:
            import google.generativeai as genai  # type: ignore
            try:
                from google.generativeai.types import GenerationConfig as _GenerationConfig  # type: ignore
            except Exception:  # noqa: BLE001
                _GenerationConfig = None
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(
                "google-generativeai パッケージが見つかりません。`pip install google-generativeai` を実行してください。"
            ) from exc

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise LLMClientError("GEMINI_API_KEY (または GOOGLE_API_KEY) が設定されていません。")

        genai.configure(api_key=api_key)
        self._genai = genai
        def resolve_tokens(max_tokens: int | None) -> int:
            if not max_tokens or max_tokens <= 0:
                return self._default_max_output_tokens
            return max(max_tokens, self._default_max_output_tokens)

        if _GenerationConfig is not None:
            def builder(max_tokens: int | None) -> object:
                return _GenerationConfig(max_output_tokens=resolve_tokens(max_tokens))  # type: ignore[arg-type]
        else:
            def builder(max_tokens: int | None) -> object:
                return {"max_output_tokens": resolve_tokens(max_tokens)}
        self._generation_config_builder = builder
        actual_model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"
        self._model = genai.GenerativeModel(actual_model_name)

    def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        """Request a Gemini response and return plain text."""
        prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        generation_config = self._generation_config_builder(max_tokens)
        response = self._model.generate_content(prompt, generation_config=generation_config)
        texts: list[str] = []
        finish_reason = None
        for candidate in getattr(response, "candidates", []) or []:
            finish_reason = getattr(candidate, "finish_reason", None) or finish_reason
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)
        if not texts:
            raise LLMClientError(
                f"Gemini 応答が空でした (finish_reason={finish_reason}). 出力トークン数を減らすか、短く要約してください。"
            )
        return "\n".join(texts).strip()

    def raw_generate(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call Gemini with raw prompt text using generate_content directly."""
        generation_config = self._generation_config_builder(max_tokens)
        response = self._model.generate_content(prompt, generation_config=generation_config)
        texts: list[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)
        if not texts:
            raise LLMClientError("Gemini 応答が空でした (raw_generate).")
        return "\n".join(texts).strip()


def create_llm_client(provider: str, model: str) -> BaseLLMClient:
    """Factory helper that returns an LLM client for the given provider."""
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
