"""What actually reaches Gemini: no response_schema (Gemini rejects the empty
"args" object), tool results come back on the user side, and GEMINI_API_KEY works."""
import importlib
import json
import sys
import types

import pytest


class _Resp:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = types.SimpleNamespace(total_token_count=0)


def _fake_genai(script, seen):
    class Model:
        def __init__(self, name, system_instruction=None):
            self.system = system_instruction

        def generate_content(self, contents, generation_config=None, stream=False):
            seen.append({"contents": contents, "config": generation_config, "system": self.system})
            return _Resp(script.pop(0))

    class GenerationConfig:
        def __init__(self, **kw):
            if "response_schema" in kw:
                raise AssertionError("response_schema must not be sent to Gemini")
            self.kw = kw

    return types.SimpleNamespace(configure=lambda **k: None, GenerativeModel=Model,
                                 types=types.SimpleNamespace(GenerationConfig=GenerationConfig))


def test_gemini_api_key_name_is_accepted(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    import core.config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.Config.LLM_API_KEY == "abc"
    finally:
        monkeypatch.delenv("GEMINI_API_KEY")
        importlib.reload(cfg)


def test_tool_results_go_back_as_user_turn_without_schema(monkeypatch, tmp_path):
    seen = []
    script = [json.dumps({"tool_calls": [{"name": "get_cached_context", "args": {}}]}),
              json.dumps({"final": True, "response": "Done."})]
    fake = _fake_genai(script, seen)
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "generativeai", fake, raising=False)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)

    from agent.orchestrator import Orchestrator
    from core.config import Config

    class Cfg(Config):
        LLM_API_KEY = "test"
        LLM_PROVIDER = "google"
        LLM_CACHE_DIR = str(tmp_path / "llm")

    o = Orchestrator(Cfg)
    if hasattr(o.llm, "rate_limiter"):
        monkeypatch.setattr(o.llm.rate_limiter, "wait_if_needed", lambda *a, **k: None, raising=False)
    out = o.process("How is my business doing?")
    assert out["response"] == "Done.", out["response"]
    second = seen[1]["contents"]
    assert second[-1]["role"] == "user" and "Tool results" in second[-1]["parts"][0]
