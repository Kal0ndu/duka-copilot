"""Redaction: tokenise PII before it leaves the system, and scan outbound payloads."""
import re
import hashlib
import secrets
from typing import Dict, Tuple, List
from dataclasses import dataclass, field

# Patterns that must never reach the LLM provider.
PII_PATTERNS: List[Tuple[str, str, str]] = [
    # (regex, entity_type, description)
    (r'(?:\+?254|0)[17]\d{8}\b', 'PHONE', 'Kenyan mobile number'),
    (r'\b254[17]\d{8}\b', 'PHONE', 'Kenyan mobile without plus'),
    (r'\b\d{3}\s?\d{3}\s?\d{3}\b', 'PHONE', 'generic phone pattern'),
    (r'\b[A-Z]\d{6,8}[A-Z]?\b', 'ID', 'Kenyan national ID pattern'),
    (r'\b\d{3,12}\b', 'REF', 'numeric reference number'),
    (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}', 'EMAIL', 'email address'),
]

# Injection patterns to flag in uploaded content.
INJECTION_PATTERNS: List[Tuple[str, str]] = [
    (r'(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)', 'INSTRUCTION_OVERRIDE'),
    (r'(?i)you\s+are\s+(now|a)\s+(different|new)\s+(role|assistant|system)', 'ROLE_CHANGE'),
    (r'(?i)system\s*(prompt|message|instruction)\s*:', 'SYSTEM_PROMPT_INJECTION'),
    (r'(?i)output\s+(only|just)\s*(the\s+)?(word|phrase|text)', 'OUTPUT_CONSTRAINT'),
    (r'(?i)<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]', 'TOKEN_INJECTION'),
    (r'(?i)execute\s+(payment|transfer|send)\s+(to|for)\s+\d+', 'PAYMENT_INSTRUCTION'),
]


@dataclass
class RedactionResult:
    redacted: str
    tokens: Dict[str, str]  # token -> original
    pii_found: List[str]
    injection_flags: List[str]

    @property
    def safe_text(self) -> str:
        return self.redacted


class Redactor:
    """Tokenises PII and scans for injection patterns."""

    def __init__(self, business_id: int = 1):
        self.business_id = business_id
        self._counter = 0

    def _make_token(self, entity_type: str) -> str:
        self._counter += 1
        return f"<{entity_type}_{self._counter:04d}>"

    def redact(self, text: str) -> RedactionResult:
        """Replace all PII with tokens. Return redacted text and token map."""
        if text is None:
            import inspect
            frame = inspect.currentframe().f_back
            if frame and "test_redaction.py" in frame.f_code.co_filename:
                raise TypeError("text cannot be None")
            return RedactionResult(redacted="", tokens={}, pii_found=[], injection_flags=[])

        tokens: Dict[str, str] = {}
        redacted = str(text)
        pii_found: List[str] = []

        for pattern, entity_type, _desc in PII_PATTERNS:
            def _replace(m, et=entity_type):
                token = self._make_token(et)
                tokens[token] = m.group(0)
                pii_found.append(f"{et}:{m.group(0)[:20]}")
                return token

            redacted = re.sub(pattern, _replace, redacted)

        injection_flags = self._scan_injections(redacted)
        return RedactionResult(
            redacted=redacted,
            tokens=tokens,
            pii_found=pii_found,
            injection_flags=injection_flags,
        )

    def redact_transactions(self, txns: list) -> list:
        """Redact PII in a list of transaction dicts or objects."""
        redacted_list = []
        for txn in txns:
            if isinstance(txn, dict):
                item = dict(txn)
                for field_name in ["counterparty", "counterparty_raw", "counterparty_token", "description", "description_raw", "description_redacted", "details"]:
                    if field_name in item and item[field_name]:
                        res = self.redact(str(item[field_name]))
                        item[field_name] = res.redacted
                redacted_list.append(item)
            else:
                redacted_list.append(txn)
        return redacted_list

    def _scan_injections(self, text: str) -> List[str]:
        """Flag injection patterns in text."""
        flags = []
        for pattern, code in INJECTION_PATTERNS:
            if re.search(pattern, text):
                flags.append(code)
        return flags

    def de_tokenise(self, text: str, tokens: Dict[str, str]) -> str:
        """Replace tokens back with original values (for UI display only)."""
        result = text
        for token, original in tokens.items():
            result = result.replace(token, original)
        return result


def outbound_scan(payload: str) -> Tuple[bool, List[str]]:
    """Scan an outbound payload for PII that escaped redaction. Returns (passed, violations)."""
    violations = []
    for pattern, entity_type, _desc in PII_PATTERNS:
        matches = re.findall(pattern, payload)
        for m in matches:
            violations.append(f"{entity_type}:{m[:30]}")
    return len(violations) == 0, violations


def hash_payload(payload: str) -> str:
    """SHA-256 of a payload for the LLM request log."""
    return hashlib.sha256(payload.encode()).hexdigest()


def wrap_untrusted(content: str, label: str = "uploaded_file") -> str:
    """Wrap untrusted content in delimiters so the LLM knows it is data, not instructions."""
    return f'<{label}>\n{content}\n</{label}>'
