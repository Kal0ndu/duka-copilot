"""LLM client: retry, streaming, structured output, and caching with smart rate limiting."""
from typing import Dict, Any, Optional, Iterator, List
from dataclasses import dataclass
import json
import hashlib
import time
import os
from pathlib import Path
import diskcache

from core.config import Config
from agent.rate_limiter import RateLimiter, PerMinuteRateLimitError, DailyRateLimitError


@dataclass
class LLMResponse:
    text: str
    usage: Dict[str, int]
    model: str
    latency_ms: float


class LLMClient:
    """Unified LLM client with TTL cache, smart rate limiting, and structured-output support.
    
    Features:
    - Automatic per-minute rate limit spacing (Gemini free tier: ~1 req/sec)
    - Per-minute vs daily limit detection
    - Exponential backoff for per-minute limits
    - Daily limit detection (unrecoverable for free tier)
    - Disk caching to reduce API calls
    """

    MAX_RATE_LIMIT_WAIT = float(os.getenv("LLM_MAX_RATE_LIMIT_WAIT", "20"))

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config
        self._cache = diskcache.Cache(self.cfg.LLM_CACHE_DIR)
        self._provider = self.cfg.LLM_PROVIDER
        self._model = self.cfg.MODEL_NAME
        self.rate_limiter = RateLimiter()  # Smart rate limiting

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
        
        try:
            genai.configure(api_key=self.cfg.LLM_API_KEY)
            # Every system message (rules, the owner's business context, the
            # tool list) goes to Gemini as its system instruction. Without it
            # the model only sees the question and answers that it has no
            # access to the owner's records.
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
            model = genai.GenerativeModel(self._model, system_instruction=system)

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
        except Exception as e:
            # Turn Gemini's 429 / RESOURCE_EXHAUSTED into our typed errors so
            # chat() can tell a short per-minute wait from a used-up day.
            classified = self.rate_limiter.classify(e)
            if classified is not None:
                raise classified from e
            raise

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
        """Chat with intelligent rate limit handling.
        
        For per-minute limits: spaces requests and retries with exponential backoff.
        For daily limits: raises immediately with helpful message.
        
        Args:
            messages: Conversation messages
            schema: Optional JSON schema for structured output
            stream: Enable streaming
            max_retries: Max attempts (per-minute limit retries don't count against this)
        
        Returns:
            LLMResponse with text, usage, model, and latency
        
        Raises:
            DailyRateLimitError: If daily quota exceeded
            RuntimeError: If all retries exhausted
        """
        key = self._cache_key(messages, schema)
        cached = self._cached(key)
        if cached:
            return cached

        last_err = None
        attempt = 0
        rate_limit_waits = 0
        
        while attempt < max_retries:
            try:
                # Space out requests to respect per-minute limits
                self.rate_limiter.wait_before_request()
                
                # Make the API call
                if self._provider == "google":
                    resp = self._call_google(messages, schema, stream)
                else:
                    resp = self._call_openai_compat(messages, schema, stream)
                
                # Record success for quota tracking
                self.rate_limiter.record_success()
                self._store(key, resp)
                return resp
                
            except (DailyRateLimitError, PerMinuteRateLimitError) as e:
                # Rate limit error: classify and handle intelligently
                if isinstance(e, DailyRateLimitError):
                    # Daily limit: not recoverable, raise immediately
                    raise
                
                # Per-minute limit: wait once if the server's wait is short;
                # otherwise give up now so the chat can answer offline instead
                # of freezing the page for a minute.
                wait_time = self.rate_limiter.handle_rate_limit_error(e) or 0
                if rate_limit_waits >= 1 or wait_time > self.MAX_RATE_LIMIT_WAIT:
                    raise
                rate_limit_waits += 1
                print(f"Rate limited. Waiting {wait_time:.0f}s before retry...")
                time.sleep(wait_time)
                continue
            
            except Exception as e:
                # Other errors: use exponential backoff
                last_err = e
                attempt += 1
                if attempt < max_retries:
                    backoff = 2 ** (attempt - 1)
                    print(f"LLM call failed (attempt {attempt}/{max_retries}). Retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    break
        
        # All retries exhausted
        raise RuntimeError(
            f"LLM call failed after {max_retries} attempts. "
            f"Last error: {last_err}\n\n"
            f"Rate limit status: {self.rate_limiter.get_status()}"
        )

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
