from app.core.security import hash_password, verify_password

PASSWORD = "PruebaSegura123!"


def test_hash_returns_string():
    assert isinstance(hash_password(PASSWORD), str)


def test_hash_differs_from_plaintext():
    assert hash_password(PASSWORD) != PASSWORD


def test_hash_uses_argon2():
    assert hash_password(PASSWORD).startswith("$argon2")


def test_verify_correct_password():
    hashed = hash_password(PASSWORD)
    assert verify_password(PASSWORD, hashed) is True


def test_verify_wrong_password():
    hashed = hash_password(PASSWORD)
    assert verify_password("incorrecta", hashed) is False


def test_two_hashes_of_same_password_differ():
    h1 = hash_password(PASSWORD)
    h2 = hash_password(PASSWORD)
    assert h1 != h2


def test_both_hashes_verify_original():
    h1 = hash_password(PASSWORD)
    h2 = hash_password(PASSWORD)
    assert verify_password(PASSWORD, h1) is True
    assert verify_password(PASSWORD, h2) is True


def test_plaintext_not_in_hash():
    hashed = hash_password(PASSWORD)
    assert PASSWORD not in hashed
