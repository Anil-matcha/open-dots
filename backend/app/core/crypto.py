from cryptography.fernet import Fernet, MultiFernet

from app.core.config import settings

_fernet = MultiFernet(
    [Fernet(key.strip().encode()) for key in settings.TOKEN_ENCRYPTION_KEYS.split(",") if key.strip()]
)


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
