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
    """High-level CV management with encryption - supports multiple users."""

    def __init__(self, encryption: CVEncryption, cv_dir: Path):
        """
        Initialize CV manager.

        Args:
            encryption: CVEncryption instance
            cv_dir: Directory to store CV files (e.g., data/)
        """
        self._encryption = encryption
        self._cv_dir = cv_dir
        self._cv_dir.mkdir(parents=True, exist_ok=True)
        self._cached_cvs: dict[int, str] = {}

    def _get_cv_path(self, user_id: int) -> Path:
        """Get the CV file path for a user."""
        return self._cv_dir / f"cv_{user_id}.enc"

    def has_cv(self, user_id: int = 0) -> bool:
        """Check if CV is stored for a user."""
        return self._get_cv_path(user_id).exists()

    def get_users_with_cv(self) -> list[int]:
        """Get list of user IDs that have CVs stored."""
        users = []
        for cv_file in self._cv_dir.glob("cv_*.enc"):
            try:
                user_id = int(cv_file.stem.replace("cv_", ""))
                users.append(user_id)
            except ValueError:
                continue
        return users

    def save_cv(self, cv_text: str, user_id: int = 0) -> None:
        """Store encrypted CV for a user."""
        cv_path = self._get_cv_path(user_id)
        self._encryption.encrypt_to_file(cv_text, cv_path)
        self._cached_cvs[user_id] = cv_text

    def get_cv(self, user_id: int = 0) -> Optional[str]:
        """Get decrypted CV text for a user."""
        if user_id in self._cached_cvs:
            return self._cached_cvs[user_id]
        try:
            cv_path = self._get_cv_path(user_id)
            cv_text = self._encryption.decrypt_from_file(cv_path)
            if cv_text:
                self._cached_cvs[user_id] = cv_text
            return cv_text
        except InvalidToken:
            logger.error(f"Failed to decrypt CV for user {user_id} - key may have changed")
            return None

    def clear_cv(self, user_id: int = 0) -> bool:
        """Delete stored CV for a user."""
        self._cached_cvs.pop(user_id, None)
        return self._encryption.delete_cv(self._get_cv_path(user_id))

    # Legacy single-user support (for migration)
    @property
    def legacy_cv_path(self) -> Path:
        """Path to legacy single-user CV file."""
        return self._cv_dir / "cv.enc"

    def migrate_legacy_cv(self, user_id: int) -> bool:
        """Migrate legacy cv.enc to user-specific file."""
        if self.legacy_cv_path.exists() and not self.has_cv(user_id):
            try:
                cv_text = self._encryption.decrypt_from_file(self.legacy_cv_path)
                if cv_text:
                    self.save_cv(cv_text, user_id)
                    logger.info(f"Migrated legacy CV to user {user_id}")
                    return True
            except InvalidToken:
                logger.error("Failed to migrate legacy CV - decryption failed")
        return False
