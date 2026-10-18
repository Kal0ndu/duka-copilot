"""Phone number validation & normalisation for Kenyan numbers."""
import re
import hashlib


def normalise_phone(raw: str) -> str:
    """Convert Kenyan phone numbers to E.164 format (+254XXXXXXXXX).

    Accepts: 07XX XXXXXX, +2547XX XXXXXX, 2547XX XXXXXX, 7XX XXXXXX
    Returns: +254XXXXXXXXX or raises ValueError.
    """
    digits = re.sub(r'\D', '', raw)

    if len(digits) == 9 and digits.startswith('7'):
        digits = '254' + digits
    elif len(digits) == 10 and digits.startswith('07'):
        digits = '254' + digits[1:]
    elif len(digits) == 12 and digits.startswith('254'):
        pass
    elif len(digits) == 13 and digits.startswith('254'):
        # already +254 format, strip the +
        pass
    else:
        raise ValueError(f"Invalid Kenyan phone number: {raw}")

    if not digits.startswith('254') or len(digits) != 12:
        raise ValueError(f"Invalid Kenyan phone number after normalisation: {raw}")

    return '+' + digits


def hash_phone(phone: str) -> str:
    """SHA-256 hash a normalised phone for storage."""
    return hashlib.sha256(phone.encode()).hexdigest()


def hash_email(email: str) -> str:
    """SHA-256 hash a lowercased email for storage."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


def mask_phone(phone: str) -> str:
    """Return display-safe phone mask: +2547XX XXX123."""
    if len(phone) >= 12:
        return phone[:7] + ' XXX' + phone[-3:]
    return phone[:4] + '***' + phone[-3:]


def is_valid_kenyan_phone(raw: str) -> bool:
    """Check if raw input looks like a valid Kenyan mobile number."""
    try:
        normalise_phone(raw)
        return True
    except ValueError:
        return False
