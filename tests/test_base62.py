import pytest

from shortener import base62


def test_encode_known_values():
    assert base62.encode(0) == "0"
    assert base62.encode(61) == "Z"
    assert base62.encode(62) == "10"
    assert base62.encode(3843) == "ZZ"


def test_encode_pads_to_min_length():
    assert base62.encode(1, min_length=6) == "000001"
    assert len(base62.encode(10**12, min_length=6)) > 6


@pytest.mark.parametrize("value", [0, 1, 61, 62, 12345, 2**40 - 1, 10**15])
def test_roundtrip(value: int):
    assert base62.decode(base62.encode(value)) == value


def test_decode_rejects_invalid_characters():
    with pytest.raises(ValueError):
        base62.decode("abc$")
    with pytest.raises(ValueError):
        base62.decode("")


def test_encode_rejects_negative():
    with pytest.raises(ValueError):
        base62.encode(-1)


def test_permutation_is_bijective_on_sample():
    seen = {base62.permute(i) for i in range(10_000)}
    assert len(seen) == 10_000


def test_consecutive_ids_produce_unrelated_codes():
    codes = [base62.code_for_id(i) for i in range(1, 6)]
    assert len(set(codes)) == 5
    assert all(len(c) >= 6 for c in codes)
    # Sequential ids must not yield sequential-looking codes.
    assert codes[1] != base62.encode(base62.decode(codes[0]) + 1, 6)
