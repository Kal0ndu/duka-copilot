"""LLM client: retry, streaming, structured output, and caching."""
from typing import Dict, Any, Optional, Iterator, List
from dataclasses import dataclass
import json
import hashlib
import time
from pathlib import Path
import diskcache

from core.config import Config


@dataclass
class LLMResponse:
    text: str
    usage: Dict[str, int]
    model: str
    latency_ms: float


class LLMClient:
    """Unified LLM client with TTL cache, retry, and structured-output support."""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config
        self._cache = diskcache.Cache(self.cfg.LLM_CACHE_DIR)
        self._provider = self.cfg.LLM_PROVIDER
        self._model = self.cfg.MODEL_NAME

    # ---- cache helpers ----

    def _cache_key(self, messages: List[Dict], schema: Optional[Dict] = None) -> str:
        payload = json.dumps({"msgs": messages, "schema": schema}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _cached(self, key: str) -> Optional[LLMResponse]:
        return self._cache.get(key)

    def _store(self, key: str, resp: LLMResponse):
        self._cache.set(key, resp, expire=3600)

    # ---- internal ----

    def _call_google(self, messages: List[Dict], schema: Optional[Dict] = None,
                     stream: bool = False) -> LLMResponse:
        import google.generativeai as genai
        genai.configure(api_key=self.cfg.LLM_API_KEY)
        model = genai.GenerativeModel(self._model)

        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        user_msgs = [{"role": "user" if m["role"] != "assistant" else "model",
                       "parts": [m["content"]]}
                     for m in messages if m["role"] != "system"]

        t0 = time.monotonic()
        if schema:
            response = model.generate_content(
                user_msgs,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
                stream=stream,
            )
        else:
            response = model.generate_content(user_msgs, stream=stream)

        if stream:
            chunks = []
            for chunk in response:
                chunks.append(chunk.text or "")
            text = "".join(chunks)
        else:
            text = response.text or ""

        latency = (time.monotonic() - t0) * 1000
        return LLMResponse(
            text=text,
            usage={"total_tokens": response.usage_metadata.total_token_count if hasattr(response, "usage_metadata") else 0},
            model=self._model,
            latency_ms=latency,
        )

    def _call_openai_compat(self, messages: List[Dict], schema: Optional[Dict] = None,
                            stream: bool = False) -> LLMResponse:
        from openai import OpenAI
        client = OpenAI(api_key=self.cfg.LLM_API_KEY,
                        base_url=os.getenv("LLM_BASE_URL", None))
        kwargs = dict(model=self._model, messages=messages, temperature=0.2)
        if schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}
        t0 = time.monotonic()
        resp = client.chat.completions.create(**kwargs)
        latency = (time.monotonic() - t0) * 1000
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            usage={"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens},
            model=self._model,
            latency_ms=latency,
        )

    # ---- public ----

    def chat(self, messages: List[Dict], schema: Optional[Dict] = None,
             stream: bool = False, max_retries: int = 3) -> LLMResponse:
        key = self._cache_key(messages, schema)
        cached = self._cached(key)
        if cached:
            return cached

        last_err = None
        for attempt in range(max_retries):
            try:
                if self._provider == "google":
                    resp = self._call_google(messages, schema, stream)
                else:
                    import os
                    resp = self._call_openai_compat(messages, schema, stream)
                self._store(key, resp)
                return resp
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")

    def structured(self, messages: List[Dict], schema: Dict,
                   max_retries: int = 3) -> Dict[str, Any]:
        """Chat with structured output; returns parsed dict."""
        resp = self.chat(messages, schema=schema, max_retries=max_retries)
        try:
            return json.loads(resp.text)
        except json.JSONDecodeError:
            json_start = resp.text.find("{")
            json_end = resp.text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(resp.text[json_start:json_end])
            raise ValueError(f"Could not parse structured output: {resp.text[:200]}")

    def stream(self, messages: List[Dict]) -> Iterator[str]:
        resp = self.chat(messages, stream=True)
        yield from resp.text.splitlines(keepends=True)
