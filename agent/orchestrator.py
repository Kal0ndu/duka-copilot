"""Main agent orchestrator: tool dispatch, LLM loop, and response synthesis."""
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
import json
import time

from core.config import Config
from agent.llm_client import LLMClient
from agent.policy_guard import PolicyGuard, PolicyViolation
from agent.tools import TOOL_REGISTRY, get_tool_schemas_for_llm
from agent.verify_numbers import verify_numbers


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


class Orchestrator:
    """Main agent orchestrator. Wires LLM, tools, guards, and verification."""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config
        self.llm = LLMClient(self.cfg)
        self.guard = PolicyGuard()
        self.state = AgentState()

    def _build_messages(self, user_input: str) -> List[Dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in self.state.turns:
            msgs.append({"role": turn.role, "content": turn.content})
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def _execute_tool(self, name: str, args: Dict) -> Dict:
        """Execute a registered tool and return its result."""
        tool = TOOL_REGISTRY.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        try:
            schema = tool.get("args_schema")
            if schema:
                parsed = schema(**args)
                result = tool["fn"](parsed)
            else:
                result = tool["fn"](**args)
            self.state.tool_results[name] = result
            return result
        except Exception as e:
            return {"error": str(e), "tool": name}

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

    def process(self, user_input: str) -> Dict[str, Any]:
        """Main entry: guard -> LLM loop -> verify -> guard -> return."""
        try:
            sanitised, input_warnings = self.guard.guard_input(user_input)
        except PolicyViolation as e:
            return {"response": "I cannot process that request.", "error": str(e), "blocked": True}

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
        }

    def reset(self):
        """Clear conversation state."""
        self.state = AgentState()
