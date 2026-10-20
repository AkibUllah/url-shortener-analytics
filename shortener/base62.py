"""Base62 encoding used for generated short codes.

Codes are derived from the database sequence, so they are guaranteed unique
without a lookup. To avoid trivially guessable sequential codes the id is run
through a fixed affine permutation before encoding (a bijection modulo 2**40),
which keeps codes short while making consecutive ids look unrelated.
"""

from __future__ import annotations

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE = len(ALPHABET)
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}

# Affine permutation parameters. MODULUS is a power of two, MULTIPLIER is odd,
# so x -> (x * MULTIPLIER + OFFSET) % MODULUS is a bijection on [0, MODULUS).
_MODULUS = 1 << 40
_MULTIPLIER = 0x5DEECE66D | 1
_OFFSET = 0x2545F491


def encode(number: int, min_length: int = 1) -> str:
    """Encode a non-negative integer to a base62 string, left-padded to ``min_length``."""
    if number < 0:
        raise ValueError("number must be non-negative")
    if number == 0:
        return ALPHABET[0].rjust(min_length, ALPHABET[0])
    digits: list[str] = []
    while number:
        number, rem = divmod(number, _BASE)
        digits.append(ALPHABET[rem])
    return "".join(reversed(digits)).rjust(min_length, ALPHABET[0])


def decode(code: str) -> int:
    """Decode a base62 string back to an integer. Raises ``ValueError`` on bad input."""
    if not code:
        raise ValueError("code must not be empty")
    value = 0
    for ch in code:
        try:
            value = value * _BASE + _INDEX[ch]
        except KeyError as exc:
            raise ValueError(f"invalid base62 character: {ch!r}") from exc
    return value


def permute(number: int) -> int:
    """Scramble a sequence id so that consecutive ids produce unrelated codes."""
    if number < 0 or number >= _MODULUS:
        raise ValueError("number out of range for permutation")
    return (number * _MULTIPLIER + _OFFSET) % _MODULUS


def code_for_id(sequence_id: int, min_length: int = 6) -> str:
    """Return the short code for a database sequence id."""
    return encode(permute(sequence_id), min_length=min_length)
