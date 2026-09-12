from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASC_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )
    database_url: str = "sqlite:///./data/aftersale.db"
    log_level: str = "INFO"
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cookie_secure: bool = False
    high_amount_threshold: Decimal = Field(default=Decimal("1000.00"), gt=0, decimal_places=2)
    return_window_days: int = Field(default=7, ge=1, le=365)
    quality_window_days: int = Field(default=30, ge=1, le=365)
    demo_api_token: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=20, gt=0, le=60)
    llm_max_retries: int = Field(default=1, ge=0, le=2)
    llm_max_output_tokens: int = Field(default=1024, ge=128, le=4096)
    agent_max_steps: int = Field(default=8, ge=1, le=20)
    agent_max_tools: int = Field(default=12, ge=1, le=30)
    agent_timeout_seconds: float = Field(default=90, gt=0, le=180)
    agent_context_chars: int = Field(default=40000, ge=2000, le=100000)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url.startswith("sqlite:///./"):
            path = PROJECT_ROOT / self.database_url.removeprefix("sqlite:///./")
            path.parent.mkdir(parents=True, exist_ok=True)
            return "sqlite:///" + path.as_posix()
        return self.database_url
