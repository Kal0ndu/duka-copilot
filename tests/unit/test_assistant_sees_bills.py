"""The assistant answers "any overdue bills?" from the owner's own data."""
import json
import sys
import types
from datetime import date, timedelta

import pytest

from core.business_setup import BusinessSetup
from tests.fixtures_duka import build_world


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    w = build_world(tmp_path_factory.mktemp("bills"))
    s = BusinessSetup(w.db)
    s.add_recurring_expense(w.amina, "rent", "Shop rent", 5_000_000, "monthly",
                            next_due=(date.today() - timedelta(days=18)).isoformat())
    s.add_recurring_expense(w.amina, "utilities", "Water", 150_000, "monthly",
                            next_due=(date.today() + timedelta(days=6)).isoformat())
    return w


def _orch(world, offline=False, reply=None):
    from agent.orchestrator import Orchestrator
    from core.config import Config
    cfg = types.SimpleNamespace(**{k: getattr(Config, k) for k in dir(Config) if k.isupper()})
    cfg.DB_PATH, cfg.LLM_API_KEY, cfg.caps_minor = world.db, "test-key", Config.caps_minor
    o = Orchestrator(cfg)
    o.offline = offline
    captured = []
    o.llm.structured = lambda msgs, schema=None: (captured.append(msgs), reply or {"final": True, "response": "ok"})[1]
    return o, captured


def test_gemini_receives_the_system_prompt_and_context(monkeypatch):
    """Regression: _call_google dropped every system message, so Gemini never
    saw the rules or the business context and said it had no access."""
    seen = {}

    class FakeModel:
        def __init__(self, name, system_instruction=None):
            seen["system"] = system_instruction

        def generate_content(self, msgs, **kw):
            seen["msgs"] = msgs
            return types.SimpleNamespace(text='{"final": true, "response": "ok"}',
                                         usage_metadata=types.SimpleNamespace(total_token_count=1))

    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda **kw: None
    fake.GenerativeModel = FakeModel
    fake.types = types.SimpleNamespace(GenerationConfig=lambda **kw: kw)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    sys.modules["google"].generativeai = fake

    from agent.llm_client import LLMClient
    from core.config import Config
    client = LLMClient(Config)
    client._call_google([
        {"role": "system", "content": "RULES + CONTEXT: Shop rent overdue 18 days"},
        {"role": "system", "content": "Available tools: ..."},
        {"role": "user", "content": "are there any overdue bills?"},
    ], schema={"type": "object"})
    assert "Shop rent overdue 18 days" in seen["system"] and "Available tools" in seen["system"]
    assert [m["role"] for m in seen["msgs"]] == ["user"]


def test_ai_prompt_contains_the_overdue_bill(world):
    o, captured = _orch(world)
    o.process("are there any over due bills?", user_id=world.amina_user, business_id=world.amina)
    system = captured[0][0]["content"]
    assert "never say you cannot access" in system.lower()
    ctx = json.loads(system.split("CURRENT BUSINESS CONTEXT (pre-computed, use this instead of querying raw data):")[1]
                     .split("\n\nOWNER'S RULES")[0])
    rent = next(b for b in ctx["obligations"] if b["label"] == "Shop rent")
    assert (rent["status"], rent["days_overdue"]) == ("overdue", 18)


def test_bills_tool_includes_recurring_expenses(world):
    o, _ = _orch(world)
    o._active_business_id = world.amina
    r = o._tool_get_payment_priorities()
    by = {b["label"]: b for b in r["recurring_expenses"]}
    assert (by["Shop rent"]["status"], by["Shop rent"]["days_overdue"]) == ("overdue", 18)
    assert by["Water"]["countdown"] == "Due in 6 days"
    assert (r["overdue_count"], r["overdue_total_kes"]) == (1, 50_000.0)


@pytest.mark.parametrize("question", ["are there any over due bills?", "Is anything overdue?",
                                      "Kuna bili zilizochelewa?"])
def test_offline_answer_lists_the_overdue_bill(world, question):
    o, captured = _orch(world, offline=True)
    r = o.process(question, user_id=world.amina_user, business_id=world.amina)
    text = r["response"]
    assert captured == []                       # answered without the AI service
    assert "Shop rent" in text and "50,000" in text
    assert "access" not in text.lower()
