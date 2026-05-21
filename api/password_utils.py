"""Password hashing helpers (no FastAPI/Redis imports — safe for db bootstrap)."""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def get_password_hash(password: str) -> str:
    if not password or not str(password).strip():
        raise ValueError("password is required for hashing")
    return _ph.hash(str(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False
