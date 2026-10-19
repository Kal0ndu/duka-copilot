"""Tool registry: definitions, schemas, and tier assignments."""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


# ---- Pydantic argument schemas for each tool ----

class StrictArgs(BaseModel):
    """Unknown fields are an error, not silently dropped: a model that adds
    e.g. "approved": true to a call gets the call refused."""
    model_config = ConfigDict(extra="forbid")


class IngestStatementArgs(StrictArgs):
    file_id: int = Field(ge=1)

class CategoriseTransactionsArgs(StrictArgs):
    file_id: int = Field(ge=1)

class GetLedgerSummaryArgs(StrictArgs):
    period: str = Field(default="month", pattern=r"^(day|week|month|quarter)$")

class ComputeBusinessHealthArgs(StrictArgs):
    period: str = Field(default="month", pattern=r"^(day|week|month|quarter)$")

class ForecastBalanceArgs(StrictArgs):
    horizon_days: int = Field(default=14, ge=1, le=90)

class DetectShortfallsArgs(StrictArgs):
    forecast_run_id: int = Field(ge=1)

class CompareFinancingArgs(StrictArgs):
    amount_minor: int = Field(ge=1)
    term_days: int = Field(ge=1, le=365)
    purpose: str = Field(default="stock", pattern=r"^(stock|equipment|other)$")

class CheckAffordabilityArgs(StrictArgs):
    offer_id: int = Field(ge=1)

class SearchKnowledgeArgs(StrictArgs):
    query: str = Field(min_length=1, max_length=500)

class DraftApplicationPackArgs(StrictArgs):
    offer_id: int = Field(ge=1)

class BuildChartArgs(StrictArgs):
    chart_id: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)

class ProposeSupplierPaymentArgs(StrictArgs):
    payee_id: Optional[int] = Field(default=None, ge=1)
    payee_name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    amount_minor: int = Field(ge=1)
    scheduled_for: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def _one_payee(self):
        if self.payee_id is None and not self.payee_name:
            raise ValueError("give payee_id or payee_name (a verified payee)")
        return self

class ProposeLoanRequestArgs(StrictArgs):
    offer_id: int = Field(ge=1)

class RecommendLoanArgs(StrictArgs):
    amount_minor: Optional[int] = Field(default=None, ge=100_000, le=100_000_000)
    term_days: int = Field(default=180, ge=30, le=365)
    language: str = Field(default="en", pattern=r"^(en|sw)$")

class ForecastBacktestArgs(StrictArgs):
    horizon_days: int = Field(default=14, ge=7, le=30)



class GetCachedContextArgs(StrictArgs):
    pass  # no args needed — context is injected by the orchestrator

class GetPaymentPrioritiesArgs(StrictArgs):
    pass  # scoped to the active business by the orchestrator

class SearchTransactionsScopedArgs(StrictArgs):
    query: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, pattern=r"^(sales|expense|transfer|fee|other)?$")
    limit: int = Field(default=10, ge=1, le=100)

@dataclass
class ToolSpec:
    name: str
    tier: str
    description: str
    schema: type[BaseModel]
    exposed_to_llm: bool = True
    enabled: bool = True
    returns: str = ""


# ---- Registry ----
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "ingest_statement": ToolSpec(
        name="ingest_statement", tier="T0",
        description="Parse and validate an uploaded statement file.",
        schema=IngestStatementArgs,
        returns="Row count, validation report, risk flag",
    ),
    "categorise_transactions": ToolSpec(
        name="categorise_transactions", tier="T0",
        description="Categorise transactions from a file using rules first, then LLM fallback.",
        schema=CategoriseTransactionsArgs,
        returns="Counts per category, review-queue size",
    ),
    "get_ledger_summary": ToolSpec(
        name="get_ledger_summary", tier="T0",
        description="Get totals by category and period.",
        schema=GetLedgerSummaryArgs,
        returns="Totals by category and month",
    ),
    "compute_business_health": ToolSpec(
        name="compute_business_health", tier="T0",
        description="Compute revenue, costs, margin, best/worst days, personal-mix ratio.",
        schema=ComputeBusinessHealthArgs,
        returns="Revenue, costs, margin, best/worst days, personal mix",
    ),
    "forecast_balance": ToolSpec(
        name="forecast_balance", tier="T0",
        description="Forecast daily balance with p10/p50/p90 band.",
        schema=ForecastBalanceArgs,
        returns="Daily p10/p50/p90 balance, obligations list",
    ),
    "detect_shortfalls": ToolSpec(
        name="detect_shortfalls", tier="T1",
        description="Detect dates where the forecast balance drops below the safety buffer.",
        schema=DetectShortfallsArgs,
        returns="Alert: date, gap, probability, suggested actions",
    ),
    "compare_financing": ToolSpec(
        name="compare_financing", tier="T1",
        description="Rank credit options for a requested amount and term by total cost.",
        schema=CompareFinancingArgs,
        returns="Ranked options with EAR, TCC, repayment total, fit flag",
    ),
    "check_affordability": ToolSpec(
        name="check_affordability", tier="T0",
        description="Test a financing offer against the forecast and safety buffer.",
        schema=CheckAffordabilityArgs,
        returns="Feasibility result and minimum margin over buffer",
    ),
    "search_knowledge": ToolSpec(
        name="search_knowledge", tier="T0",
        description="Search the knowledge base for relevant information.",
        schema=SearchKnowledgeArgs,
        returns="Top chunks with ids and scores",
    ),
    "draft_application_pack": ToolSpec(
        name="draft_application_pack", tier="T1",
        description="Draft a loan application pack in Markdown.",
        schema=DraftApplicationPackArgs,
        returns="Document draft (Markdown)",
    ),
    "build_chart": ToolSpec(
        name="build_chart", tier="T0",
        description="Return a chart specification and underlying data.",
        schema=BuildChartArgs,
        returns="Chart specification and data frame",
    ),
    "recommend_loan": ToolSpec(
        name="recommend_loan", tier="T1",
        description=(
            "Loan fit check. Runs every loan option through the cash-flow forecast for the whole "
            "loan, checks the low estimate stays above the owner's safety buffer, and finds the "
            "weekly personal-spending limit that would make each option fit. Recommends the "
            "cheapest option that fits, never above the owner's loan cap. Leave amount_minor out "
            "to use the amount the forecast says is needed. Returns plain-language advice in "
            "'en' or 'sw'."
        ),
        schema=RecommendLoanArgs,
        returns="Options with fits_now and max weekly personal money, best option, advice text",
    ),
    "forecast_backtest": ToolSpec(
        name="forecast_backtest", tier="T0",
        description="How accurate is the forecast? Hides the last N days of history, forecasts them, "
                    "and reports the error against what really happened.",
        schema=ForecastBacktestArgs,
        returns="Balance error, days inside the low-high range, sales error %",
    ),
    "propose_supplier_payment": ToolSpec(
        name="propose_supplier_payment", tier="T2",
        description=("Create a payment REQUEST to one of the owner's verified payees (by payee_id or "
                     "exact payee_name). It is NOT paid: the owner must approve it with their PIN on the "
                     "Approvals page. Requests that break the owner's rules come back BLOCKED with a reason."),
        schema=ProposeSupplierPaymentArgs,
        returns="action_id with status PENDING_APPROVAL",
    ),
    "propose_loan_request": ToolSpec(
        name="propose_loan_request", tier="T2",
        description=("Create a loan REQUEST for an offer_id from compare_financing or recommend_loan. "
                     "It is NOT taken: the owner must approve it with their PIN on the Approvals page."),
        schema=ProposeLoanRequestArgs,
        returns="action_id with status PENDING_APPROVAL",
    ),
    # Not exposed to LLM:
    "execute_approved_action": ToolSpec(
        name="execute_approved_action", tier="T2",
        description="Execute an approved action in the sandbox. UI only, never exposed to LLM.",
        schema=BaseModel,
        exposed_to_llm=False,
        returns="Sandbox receipt",
    ),
    "authorize_scheduled_payment": ToolSpec(
        name="authorize_scheduled_payment", tier="T2",
        description="Owner taps Authorize: send an M-Pesa STK prompt for a scheduled payment. UI only, never exposed to LLM.",
        schema=BaseModel,
        exposed_to_llm=False,
        returns="STK prompt sent to the owner's phone",
    ),
    "get_payment_priorities": ToolSpec(
        name="get_payment_priorities", tier="T0",
        description=(
            "List upcoming standing-order payments ranked by priority (score, band, reasons, status). "
            "Read-only: use it to explain what to pay first. You cannot pay or authorize anything; "
            "the owner authorizes each payment on the Standing Orders page and confirms with their M-Pesa PIN."
        ),
        schema=GetPaymentPrioritiesArgs,
        returns="Ranked list of open payments with priority reasons",
    ),
    "get_cached_context": ToolSpec(
        name="get_cached_context", tier="T0",
        description="Load pre-computed business context (revenue, expenses, health, obligations, forecast). Use this first for any business overview query.",
        schema=GetCachedContextArgs,
        returns="Full business context dict with summary, health, obligations, forecast, risks, recent transactions",
    ),
    "search_transactions_scoped": ToolSpec(
        name="search_transactions_scoped", tier="T0",
        description="Search recent transactions by keyword in category or channel. Scoped to current user/business only.",
        schema=SearchTransactionsScopedArgs,
        returns="Filtered list of transaction summaries (date, type, amount, category, direction)",
    ),
}


def get_tool_spec(name: str) -> Optional[ToolSpec]:
    return TOOL_REGISTRY.get(name)


def validate_args(tool_name: str, args: dict) -> tuple[bool, Optional[dict], Optional[str]]:
    """Validate tool arguments against the pydantic schema. Returns (valid, parsed, error)."""
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return False, None, f"unknown tool: {tool_name}"
    try:
        parsed = spec.schema(**args)
        return True, parsed.model_dump(), None
    except ValidationError as e:
        return False, None, str(e)


def get_tool_schemas_for_llm() -> List[dict]:
    """Return the tool list for the LLM provider (Gemini format)."""
    tools = []
    for name, spec in TOOL_REGISTRY.items():
        if not spec.exposed_to_llm or not spec.enabled:
            continue
        tools.append({
            "name": name,
            "description": spec.description,
            "parameters": spec.schema.model_json_schema(),
        })
    return tools


# Alias for backward compatibility
get_llm_tools = get_tool_schemas_for_llm
