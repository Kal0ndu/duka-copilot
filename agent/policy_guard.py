"""Policy guard: block dangerous LLM outputs before they reach the user."""
from typing import Dict, Any, List, Optional, Tuple
import re


# ---- blocked patterns ----

BLOCKED_FIELDS_IN_OUTPUT = [
    "api_key", "apikey", "api_secret", "password", "access_token",
    "bearer_token", "private_key", "secret_key",
]

DANGEROUS_PHRASES = [
    "ignore previous instructions",
    "ignore all instructions",
    "you are now DAN",
    "pretend you are",
    "bypass",
    "jailbreak",
]

SENSITIVE_PII_PATTERNS = [
    r'\b\d{3}-\d{2}-\d{4}\b',       # SSN-like
    r'\b\d{16}\b',                   # card number
    r'\b4\d{15}\b',                  # Visa
    r'\b5[1-5]\d{14}\b',             # Mastercard
]


class PolicyViolation(Exception):
    def __init__(self, rule: str, detail: str):
        self.rule = rule
        self.detail = detail
        super().__init__(f"Policy violation [{rule}]: {detail}")


class PolicyGuard:
    """Pre-flight and post-flight guardrails for LLM interactions."""

    # ---- input guards ----

    @staticmethod
    def sanitise_prompt(prompt: str, redact_fn=None) -> Tuple[str, List[str]]:
        """Remove PII from user prompts. Returns (sanitised, warnings)."""
        warnings = []
        for pattern in SENSITIVE_PII_PATTERNS:
            if re.search(pattern, prompt):
                warnings.append(f"Potential PII matched pattern: {pattern}")
        if redact_fn:
            prompt = redact_fn(prompt)
        return prompt, warnings

    @staticmethod
    def check_jailbreak(prompt: str) -> bool:
        """Return True if the prompt contains known jailbreak attempts."""
        lowered = prompt.lower()
        return any(phrase in lowered for phrase in DANGEROUS_PHRASES)

    # ---- output guards ----

    @staticmethod
    def validate_structured_output(output: Dict[str, Any],
                                    blocked_fields: Optional[List[str]] = None) -> List[str]:
        """Check structured LLM output for prohibited keys. Returns violations list."""
        fields = blocked_fields or BLOCKED_FIELDS_IN_OUTPUT
        violations = []
        for key in output:
            if any(f in key.lower() for f in fields):
                violations.append(f"Key '{key}' matches blocked field pattern")
        return violations

    @staticmethod
    def check_output_pii(text: str) -> List[str]:
        """Scan output for PII that should not have been leaked. Returns findings."""
        findings = []
        for pattern in SENSITIVE_PII_PATTERNS:
            for m in re.finditer(pattern, text):
                findings.append(f"PII found: {m.group()}")
        return findings

    @staticmethod
    def check_financial_claims(text: str, caps: Dict[str, int]) -> List[str]:
        """Verify that financial claims in output don't exceed regulatory caps."""
        warnings = []
        per_txn = caps.get("per_txn", 0)
        daily = caps.get("daily", 0)
        amounts = re.findall(r'KES\s*([\d,]+(?:\.\d{1,2})?)', text)
        for amt_str in amounts:
            amt = float(amt_str.replace(",", ""))
            if amt > per_txn:
                warnings.append(f"Claimed amount KES {amt:,.0f} exceeds per-txn cap KES {per_txn:,.0f}")
            if amt > daily:
                warnings.append(f"Claimed amount KES {amt:,.0f} exceeds daily cap KES {daily:,.0f}")
        return warnings

    # ---- combined pipeline ----

    def guard_input(self, prompt: str, redact_fn=None) -> Tuple[str, List[str]]:
        """Run all input guardrails. Raises PolicyViolation on hard blocks."""
        if self.check_jailbreak(prompt):
            raise PolicyViolation("jailbreak", "Prompt contains jailbreak attempt")
        sanitised, warnings = self.sanitise_prompt(prompt, redact_fn=redact_fn)
        return sanitised, warnings

    def guard_output(self, text: str, structured: Optional[Dict] = None,
                     caps: Optional[Dict] = None) -> List[str]:
        """Run all output guardrails. Returns list of warnings."""
        warnings = []
        warnings.extend(self.check_output_pii(text))
        if structured:
            warnings.extend(self.validate_structured_output(structured))
        if caps:
            warnings.extend(self.check_financial_claims(text, caps))
        return warnings
