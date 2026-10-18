"""Security: the LLM can read payment priorities but can never authorize or execute a payment."""
from agent.orchestrator import Orchestrator
from agent.tools import TOOL_REGISTRY, get_tool_schemas_for_llm


def test_authorize_tool_hidden_from_llm():
    names = {t["name"] for t in get_tool_schemas_for_llm()}
    assert "authorize_scheduled_payment" not in names
    assert "execute_approved_action" not in names
    assert "get_payment_priorities" in names


def test_orchestrator_refuses_authorize_tool():
    orch = Orchestrator()
    orch._log_audit = lambda *a, **k: None
    result = orch._execute_tool("authorize_scheduled_payment", {"payment_id": 1})
    assert result.get("blocked") is True


def test_only_ui_only_tools_are_t2_without_llm_exposure():
    for name, spec in TOOL_REGISTRY.items():
        if "authorize" in name or name.startswith("execute"):
            assert spec.exposed_to_llm is False, name
