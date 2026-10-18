"""Main agent orchestrator: tool dispatch, LLM loop, and response synthesis."""
from typing import Dict, Any, List, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
import json
import time

from core.config import Config
from agent.llm_client import LLMClient
from agent.policy_guard import PolicyGuard, PolicyViolation
from agent.tools import TOOL_REGISTRY, get_tool_schemas_for_llm
from agent.verify_numbers import verify_numbers
from auth.user_context import UserContext, invalidate_user_cache, invalidate_session_context, refresh_context_if_stale


@dataclass
class AgentTurn:
    role: str
    content: str
    tool_calls: Optional[List[Dict]] = None
    latency_ms: float = 0.0


@dataclass
class AgentState:
    turns: List[AgentTurn] = field(default_factory=list)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    redacted: bool = False


SYSTEM_PROMPT = """You are Duka, a financial assistant for Kenyan micro-entrepreneurs. Your role:

1. Help users understand their business finances — revenue, costs, margins, trends.
2. Analyse transaction statements and categorise income vs expenses.
3. Forecast cash flow and detect upcoming shortfalls.
4. Compare financing options using effective cost (EAR, TCC).
5. Draft loan-application packs with evidence-backed numbers.

Rules:
- ALL amounts in KES. Always show both the raw number and a short interpretation.
- Never invent numbers. Use tool results. When uncertain, say so.
- Redact PII before any external call — phone numbers, names, account numbers.
- Respect regulatory caps: KES 250,000 per transaction, KES 500,000 daily.
- Keep language simple — Grade 5 English level.
- Cite which tool you used for each number you report.
"""

SYSTEM_PROMPT_WITH_CONTEXT = """You are Duka, a financial assistant for Kenyan micro-entrepreneurs. Your role:

1. Help users understand their business finances — revenue, costs, margins, trends.
2. Analyse transaction statements and categorise income vs expenses.
3. Forecast cash flow and detect upcoming shortfalls.
4. Compare financing options using effective cost (EAR, TCC).
5. Draft loan-application packs with evidence-backed numbers.

Rules:
- ALL amounts in KES. Always show both the raw number and a short interpretation.
- Never invent numbers. Use tool results. When uncertain, say so.
- Redact PII before any external call — phone numbers, names, account numbers.
- Respect regulatory caps: KES 250,000 per transaction, KES 500,000 daily.
- Keep language simple — Grade 5 English level.
- Cite which tool you used for each number you report.

CURRENT BUSINESS CONTEXT (pre-computed, use this instead of querying raw data):
{business_context}
"""


class Orchestrator:
    """Main agent orchestrator. Wires LLM, tools, guards, and verification."""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config
        self.llm = LLMClient(self.cfg)
        self.guard = PolicyGuard()
        self.state = AgentState()
        self._active_context: Optional[Dict[str, Any]] = None
        self._active_user_id: Optional[int] = None
        self._active_business_id: Optional[int] = None

    def _build_messages(self, user_input: str) -> List[Dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in self.state.turns:
            msgs.append({"role": turn.role, "content": turn.content})
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def _build_messages_with_context(self, user_input: str, context: Dict[str, Any]) -> List[Dict]:
        """Build messages with pre-computed business context injected into the system prompt."""
        ctx_text = json.dumps(context, indent=2, default=str)
        system = SYSTEM_PROMPT_WITH_CONTEXT.format(business_context=ctx_text)
        msgs = [{"role": "system", "content": system}]
        for turn in self.state.turns:
            msgs.append({"role": turn.role, "content": turn.content})
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def _execute_tool(self, name: str, args: Dict) -> Dict:
        """Execute a registered tool and return its result.

        Internal tools (get_cached_context, search_transactions_scoped) are
        handled directly; other tools dispatch through the registry."""
        # Internal orchestrator-level tools
        if name == "get_cached_context":
            return self._tool_get_cached_context()
        if name == "search_transactions_scoped":
            return self._tool_search_transactions_scoped(args)

        spec = TOOL_REGISTRY.get(name)
        if not spec:
            return {"error": f"Unknown tool: {name}"}

        try:
            parsed = spec.schema(**args)
            result = self._dispatch_registered_tool(spec, parsed)
            self.state.tool_results[name] = result

            # Invalidate context cache on write/mutating operations
            _WRITE_TOOLS = {
                "ingest_statement", "categorise_transactions",
                "propose_supplier_payment", "propose_loan_request",
            }
            if name in _WRITE_TOOLS and self._active_user_id is not None:
                invalidate_user_cache(
                    self._active_user_id, self._active_business_id,
                )

            return result
        except Exception as e:
            return {"error": str(e), "tool": name}

    def _dispatch_registered_tool(self, spec: Any, parsed_args: Any) -> Dict:
        """Dispatch to a registered tool's implementation.

        Tools are expected to be importable callables keyed by name.
        Falls back gracefully when no implementation is wired."""
        import importlib

        # Map of tool implementations — loaded lazily
        _TOOL_IMPLS: Dict[str, str] = {
            "ingest_statement": "core.expense_tracker.ingest_statement",
            "categorise_transactions": "core.categoriser.categorise_transactions",
            "get_ledger_summary": "core.expense_tracker.get_ledger_summary",
            "compute_business_health": "core.financial_health.compute_business_health",
            "forecast_balance": "core.forecaster.forecast_balance",
            "detect_shortfalls": "core.forecaster.detect_shortfalls",
            "compare_financing": "core.cost_engine.compare_financing",
            "check_affordability": "core.cost_engine.check_affordability",
            "search_knowledge": "core.config.search_knowledge",
            "draft_application_pack": "core.cost_engine.draft_application_pack",
            "build_chart": "core.charts.build_chart",
            "propose_supplier_payment": "sandbox.account.propose_supplier_payment",
            "propose_loan_request": "sandbox.mock_lender.propose_loan_request",
        }

        mod_path = _TOOL_IMPLS.get(spec.name)
        if not mod_path:
            return {"error": f"No implementation wired for tool: {spec.name}"}

        try:
            module_name, func_name = mod_path.rsplit(".", 1)
            mod = importlib.import_module(module_name)
            fn = getattr(mod, func_name, None)
            if fn is None:
                return {"error": f"Function {func_name} not found in {module_name}"}
            result = fn(parsed_args)
            return result
        except Exception as e:
            return {"error": str(e), "tool": spec.name}

    def _tool_get_cached_context(self) -> Dict[str, Any]:
        """Return the pre-loaded business context (from process inject)."""
        if self._active_context is None:
            return {"error": "No business context loaded. Provide user_id and business_id to process()."}
        return {"context": self._active_context}

    def _tool_search_transactions_scoped(self, args: Dict) -> Dict[str, Any]:
        """Search recent transactions scoped to the current user/business."""
        if self._active_context is None:
            return {"error": "No business context loaded. Provide user_id and business_id to process()."}

        query = (args.get("query", "") or "").lower()
        category = args.get("category")
        limit = args.get("limit", 10)

        txs = self._active_context.get("recent_transactions", [])
        matched = []
        for tx in txs:
            if category and tx.get("category") != category:
                continue
            if query:
                haystack = f"{tx.get('type','')} {tx.get('category','')} {tx.get('direction','')}"
                if query not in haystack.lower():
                    continue
            matched.append(tx)
            if len(matched) >= limit:
                break

        return {"transactions": matched, "total_available": len(txs), "matched": len(matched)}

    def _tool_decision_loop(self, messages: List[Dict], max_steps: int = 5) -> str:
        """ReAct-style loop: LLM decides tool calls, we execute, repeat."""
        for step in range(max_steps):
            tool_schemas = get_tool_schemas_for_llm()
            tool_prompt = (
                "\n\nAvailable tools:\n" +
                json.dumps(tool_schemas, indent=2) +
                "\n\nRespond with JSON: {\"tool_calls\": [{\"name\": \"...\", \"args\": {...}}]} "
                "OR {\"final\": true, \"response\": \"...\"} if you're done."
            )
            msgs_with_tools = messages + [{"role": "system", "content": tool_prompt}]

            t0 = time.monotonic()
            try:
                decision = self.llm.structured(
                    msgs_with_tools,
                    schema={
                        "type": "object",
                        "properties": {
                            "final": {"type": "boolean"},
                            "response": {"type": "string"},
                            "tool_calls": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "args": {"type": "object"},
                                    },
                                    "required": ["name", "args"],
                                },
                            },
                        },
                        "required": [],
                    },
                )
            except Exception as e:
                return f"I encountered an error processing your request: {e}"

            latency = (time.monotonic() - t0) * 1000

            if decision.get("final"):
                response = decision.get("response", "")
                self.state.turns.append(AgentTurn(role="assistant", content=response, latency_ms=latency))
                return response

            tool_calls = decision.get("tool_calls", [])
            if not tool_calls:
                response = decision.get("response", "I couldn't determine the next action.")
                self.state.turns.append(AgentTurn(role="assistant", content=response, latency_ms=latency))
                return response

            results = []
            for tc in tool_calls:
                res = self._execute_tool(tc["name"], tc.get("args", {}))
                results.append({"tool": tc["name"], "result": res})

            messages.append({
                "role": "assistant",
                "content": f"Tool results: {json.dumps(results, default=str)}",
            })

        return "I've run several checks but need more direction. Could you clarify what you'd like me to focus on?"

    # ---- public API ----

    def process(
        self,
        user_input: str,
        user_id: Optional[int] = None,
        business_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Main entry: guard -> LLM loop -> verify -> guard -> return.

        When user_id and business_id are provided, pre-loads a cached
        business context and injects it into the system prompt so the
        LLM works with pre-aggregated data.
        """
        try:
            sanitised, input_warnings = self.guard.guard_input(user_input)
        except PolicyViolation as e:
            return {"response": "I cannot process that request.", "error": str(e), "blocked": True}

        # Load user context if identifiers provided
        if user_id is not None and business_id is not None:
            self._active_user_id = user_id
            self._active_business_id = business_id
            try:
                ctx = UserContext(user_id=user_id, business_id=business_id)
                self._active_context = ctx.get()
            except Exception:
                self._active_context = None
        else:
            self._active_user_id = None
            self._active_business_id = None
            self._active_context = None

        # Build messages — with context if available
        if self._active_context:
            messages = self._build_messages_with_context(sanitised, self._active_context)
        else:
            messages = self._build_messages(sanitised)

        self.state.turns.append(AgentTurn(role="user", content=sanitised))

        response = self._tool_decision_loop(messages)

        caps = self.cfg.caps_minor()
        output_warnings = self.guard.guard_output(response, caps=caps)

        verification = verify_numbers(response, self.state.tool_results)

        return {
            "response": response,
            "input_warnings": input_warnings,
            "output_warnings": output_warnings,
            "verification": verification,
            "tool_results": dict(self.state.tool_results),
            "context_used": self._active_context is not None,
        }

    def reset(self):
        """Clear conversation state."""
        self.state = AgentState()
        self._active_context = None
        self._active_user_id = None
        self._active_business_id = None
