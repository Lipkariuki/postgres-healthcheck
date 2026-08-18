"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Database connection settings for the health check tool."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    @classmethod
    def from_env(cls) -> "Config":
        """Create a Config instance from environment variables."""
        load_dotenv()

        required_values = {
            "DB_HOST": os.getenv("DB_HOST"),
            "DB_PORT": os.getenv("DB_PORT"),
            "DB_NAME": os.getenv("DB_NAME"),
            "DB_USER": os.getenv("DB_USER"),
            "DB_PASSWORD": os.getenv("DB_PASSWORD"),
        }

        missing = [name for name, value in required_values.items() if not value]
        if missing:
            missing_names = ", ".join(missing)
            raise ConfigError(f"Missing required environment variables: {missing_names}")

        db_port = required_values["DB_PORT"]
        try:
            port = int(db_port or "")
        except ValueError as exc:
            raise ConfigError("DB_PORT must be a valid integer") from exc

        if not 1 <= port <= 65535:
            raise ConfigError("DB_PORT must be between 1 and 65535")

        return cls(
            db_host=required_values["DB_HOST"] or "",
            db_port=port,
            db_name=required_values["DB_NAME"] or "",
            db_user=required_values["DB_USER"] or "",
            db_password=required_values["DB_PASSWORD"] or "",
        )
