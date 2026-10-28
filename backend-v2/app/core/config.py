from functools import lru_cache
from typing import Annotated, Any, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode


class Settings(BaseSettings):
    # App
    APP_NAME: str = "DEDAN Health API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, description="Debug mode")
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS
    # `NoDecode` stops pydantic-settings from JSON-parsing the raw env value,
    # which lets the validator below accept a plain comma-separated list.
    CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000"],
        description="Allowed CORS origins (comma-separated or JSON array)",
    )
    #: Host headers the API answers in production (TrustedHost). Behind the
    #: Next.js app the API is reached by its internal name, e.g. ``backend``.
    ALLOWED_HOSTS: Annotated[List[str], NoDecode] = Field(
        default=["localhost", "127.0.0.1"],
        description="Allowed Host headers in production (comma-separated or JSON array)",
    )

    # AI Providers
    # `AI_PROVIDER_MODE` pins every capability to the deterministic offline
    # provider. Values: offline | mock | local | rules. Anything else allows
    # live provider calls, but only if a usable (non-placeholder) credential
    # is configured — see `providers/provider_factory.py`.
    AI_PROVIDER_MODE: str = Field(
        default="offline",
        description="Provider mode: offline (deterministic) or live",
    )
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API key")
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API key")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API key")
    DEFAULT_AI_PROVIDER: str = Field(default="gemini", description="Default AI provider: gemini, openai, anthropic")
    GEMINI_MODEL: str = Field(default="gemini-flash-latest", description="Gemini model to use")
    OPENAI_MODEL: str = Field(default="gpt-4o", description="OpenAI model to use")
    ANTHROPIC_MODEL: str = Field(default="claude-3-5-sonnet-20241022", description="Anthropic model to use")

    # AI Settings
    AI_TEMPERATURE: float = Field(default=0.3, description="AI temperature for generation")
    AI_MAX_TOKENS: int = Field(default=4096, description="Max output tokens")
    AI_TIMEOUT_SECONDS: int = Field(default=60, description="AI request timeout")

    # Image Upload
    MAX_IMAGE_SIZE_MB: int = Field(default=10, description="Max image size in MB")
    ALLOWED_IMAGE_TYPES: Annotated[List[str], NoDecode] = Field(
        default=["image/jpeg", "image/png", "image/webp", "image/heic"],
        description="Allowed image MIME types (comma-separated or JSON array)",
    )
    IMAGE_STORAGE_PATH: str = Field(default="/tmp/dedan_images", description="Local image storage path")
    IMAGE_TTL_HOURS: int = Field(default=24, description="Image time-to-live in hours")

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = Field(default=30, description="Requests per minute per IP")
    RATE_LIMIT_WINDOW: int = Field(default=60, description="Rate limit window in seconds")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Log level")
    LOG_FORMAT: str = Field(default="json", description="Log format: json or text")

    # Security
    API_KEY_HEADER: str = Field(default="X-API-Key", description="API key header name")
    ADMIN_API_KEY: Optional[str] = Field(default=None, description="Admin API key for privileged operations")
    REALTIME_TOKEN_SECRET: Optional[str] = Field(
        default=None, description="Signs login tokens; falls back to ADMIN_API_KEY"
    )

    # External Services (for pharmacy guidance)
    GOOGLE_MAPS_API_KEY: Optional[str] = Field(default=None, description="Google Maps API key for pharmacy lookup")
    COUNTRY_CODE: str = Field(default="ET", description="Default country code for pharmacy guidance")

    # Database. Declared here so a value in `.env` is honoured: it used to be
    # read from the process environment only, so a production Postgres URL in
    # `.env` was ignored and the app silently wrote to a local SQLite file.
    DEDAN_DATABASE_URL: Optional[str] = Field(default=None, description="SQLAlchemy database URL")
    # The file holding the 32-byte master key that encrypts health data
    # (dedan_platform/crypto.py). Read from the environment first, like the URL above.
    PLATFORM_MASTER_KEY_FILE: Optional[str] = Field(default=None, description="Master key file (32 bytes)")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        # The .env ships keys for the notification/reminder subsystems that are
        # read directly with os.getenv; they are not Settings fields. Without
        # this, pydantic-settings 2.16+ raises "extra inputs are not permitted"
        # on every one of them and the app refuses to start.
        extra = "ignore"

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _normalise_environment(cls, value: Any) -> Any:
        """Lower-cased once, here, so every `== "production"` check holds.

        "Production" used to skip TrustedHost, secure cookies and the
        production secret check, which compared case-sensitively.
        """
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("CORS_ORIGINS", "ALLOWED_IMAGE_TYPES", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: Any) -> Any:
        """Accept comma-separated env values as well as JSON arrays.

        pydantic-settings parses complex fields as JSON, so a bare
        ``A,B,C`` in ``.env`` would otherwise raise a JSONDecodeError. Operators
        reasonably expect the comma-separated form, so both are supported.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return value  # already JSON; let pydantic parse it
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


@lru_cache()
def get_settings() -> Settings:
    return Settings()