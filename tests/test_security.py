from shortener.security import hash_ip, hash_password, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-pass")
    assert stored.startswith("pbkdf2$")
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong", stored)


def test_password_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


def test_verify_rejects_malformed_hash():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "")


def test_hash_ip_is_keyed_and_stable():
    a = hash_ip("103.108.140.5", "k1")
    assert a == hash_ip("103.108.140.5", "k1")
    assert a != hash_ip("103.108.140.5", "k2")
    assert hash_ip(None, "k1") is None
