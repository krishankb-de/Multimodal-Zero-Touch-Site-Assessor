"""
Application configuration loaded from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)


@dataclass(frozen=True)
class GeminiConfig:
    """Google Gemini API configuration."""

    api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model_name: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash"))


@dataclass(frozen=True)
class PioneerConfig:
    """Pioneer SLM API configuration."""

    api_key: str = field(default_factory=lambda: os.getenv("PIONEER_API_KEY", ""))
    api_url: str = field(
        default_factory=lambda: os.getenv("PIONEER_API_URL", "https://api.pioneer.ai/v1")
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("PIONEER_MODEL", "deepseek-ai/DeepSeek-V3.1")
    )


@dataclass(frozen=True)
class MarketConfig:
    """Market-specific defaults."""

    market: str = field(default_factory=lambda: os.getenv("DEFAULT_MARKET", "DE"))
    currency: str = field(default_factory=lambda: os.getenv("DEFAULT_CURRENCY", "EUR"))
    region: str = field(default_factory=lambda: os.getenv("REGION", "Hamburg"))


@dataclass(frozen=True)
class AppConfig:
    """Root application configuration."""

    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "DEBUG"))
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    pioneer: PioneerConfig = field(default_factory=PioneerConfig)
    market: MarketConfig = field(default_factory=MarketConfig)


# Singleton instance
config = AppConfig()
