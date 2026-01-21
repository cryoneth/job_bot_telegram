"""CV encryption using Fernet (symmetric encryption)."""

import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CVEncryption:
    """Handles CV encryption and decryption using Fernet."""

    def __init__(self, key: Optional[str] = None):
        """
        Initialize encryption with a key.

        Args:
            key: Fernet key as base64 string. If None, generates a new key.
        """
        if key:
            self._key = key.encode() if isinstance(key, str) else key
        else:
            self._key = Fernet.generate_key()
            logger.warning(
                "No encryption key provided. Generated new key. "
                "Save this to .env: CV_ENCRYPTION_KEY=%s",
                self._key.decode(),
            )
        self._fernet = Fernet(self._key)

    @property
    def key(self) -> str:
        """Get the encryption key as string."""
        return self._key.decode()

    @classmethod
    def generate_key(cls) -> str:
        """Generate a new Fernet encryption key."""
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: str) -> bytes:
        """
        Encrypt text.

        Args:
            plaintext: Text to encrypt.

        Returns:
            Encrypted bytes.
        """
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """
        Decrypt bytes back to text.

        Args:
            ciphertext: Encrypted bytes.

        Returns:
            Decrypted text.

        Raises:
            InvalidToken: If decryption fails (wrong key or corrupted data).
        """
        return self._fernet.decrypt(ciphertext).decode("utf-8")

    def encrypt_to_file(self, plaintext: str, file_path: Path) -> None:
        """
        Encrypt text and save to file.

        Args:
            plaintext: Text to encrypt.
            file_path: Path to save encrypted data.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.encrypt(plaintext)
        file_path.write_bytes(encrypted)
        logger.info("CV encrypted and saved to %s", file_path)

    def decrypt_from_file(self, file_path: Path) -> Optional[str]:
        """
        Read and decrypt file.

        Args:
            file_path: Path to encrypted file.

        Returns:
            Decrypted text, or None if file doesn't exist.

        Raises:
            InvalidToken: If decryption fails.
        """
        if not file_path.exists():
            return None
        encrypted = file_path.read_bytes()
        return self.decrypt(encrypted)

    def delete_cv(self, file_path: Path) -> bool:
        """
        Securely delete CV file.

        Args:
            file_path: Path to CV file.

        Returns:
            True if file was deleted, False if it didn't exist.
        """
        if file_path.exists():
            # Overwrite with random data before deleting
            file_path.write_bytes(Fernet.generate_key() * 10)
            file_path.unlink()
            logger.info("CV file deleted: %s", file_path)
            return True
        return False


class CVManager:
    """High-level CV management with encryption."""

    def __init__(self, encryption: CVEncryption, cv_path: Path):
        self._encryption = encryption
        self._cv_path = cv_path
        self._cached_cv: Optional[str] = None

    @property
    def has_cv(self) -> bool:
        """Check if CV is stored."""
        return self._cv_path.exists()

    def set_cv(self, cv_text: str) -> None:
        """Store encrypted CV."""
        self._encryption.encrypt_to_file(cv_text, self._cv_path)
        self._cached_cv = cv_text

    def get_cv(self) -> Optional[str]:
        """Get decrypted CV text."""
        if self._cached_cv is not None:
            return self._cached_cv
        try:
            self._cached_cv = self._encryption.decrypt_from_file(self._cv_path)
            return self._cached_cv
        except InvalidToken:
            logger.error("Failed to decrypt CV - key may have changed")
            return None

    def clear_cv(self) -> bool:
        """Delete stored CV."""
        self._cached_cv = None
        return self._encryption.delete_cv(self._cv_path)
