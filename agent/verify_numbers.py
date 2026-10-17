"""Number verification: check LLM outputs against deterministic tool results."""
from typing import Dict, List, Tuple, Any
import re


def extract_numbers(text: str) -> List[Tuple[str, float]]:
    """Extract KES amounts from LLM text. Returns (raw_match, value_in_kes)."""
    patterns = [
        (r'KES\s*([\d,]+(?:\.\d{1,2})?)', 1.0),
        (r'KSh\s*([\d,]+(?:\.\d{1,2})?)', 1.0),
        (r'([\d,]+(?:\.\d{1,2})?)\s*(?:KES|KSh|shillings?)', 1.0),
        (r'([\d,]+(?:\.\d{1,2})?)%', 0.01),  # percentage
    ]
    found = []
    for pattern, multiplier in patterns:
        for m in re.finditer(pattern, text):
            val_str = m.group(1).replace(",", "")
            try:
                found.append((m.group(0), round(float(val_str) * multiplier, 6)))
            except ValueError:
                pass
    return found


def verify_numbers(llm_response: str, tool_results: Dict[str, Any]) -> Dict:
    """Verify that numbers in the LLM response match tool results.

    Returns dict with: passed (bool), violations (list), checked_count (int)
    """
    violations = []
    llm_numbers = extract_numbers(llm_response)

    # Build a set of known-good values from tool results
    known_values = _flatten_values(tool_results)

    for raw_match, value in llm_numbers:
        # Check if this value appears in any tool result (within 1% tolerance)
        is_verified = False
        for known in known_values:
            if known > 0 and abs(value - known) / known < 0.01:
                is_verified = True
                break
            elif known == 0 and value == 0:
                is_verified = True
                break

        if not is_verified:
            violations.append({
                "raw_match": raw_match,
                "value": value,
                "reason": "value not found in tool results",
            })

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "checked_count": len(llm_numbers),
    }


def _flatten_values(obj: Any, prefix: str = "") -> List[float]:
    """Recursively extract all numeric values from tool results."""
    values = []
    if isinstance(obj, (int, float)):
        values.append(float(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            values.extend(_flatten_values(v, f"{prefix}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            values.extend(_flatten_values(v, f"{prefix}[{i}]"))
    return values
