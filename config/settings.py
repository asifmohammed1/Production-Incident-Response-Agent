"""Lightweight settings loader for local development.

Loads values from environment variables or `.env` (if python-dotenv available).
Provides the small subset of settings used by the project.
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


@dataclass
class Settings:
    LOG_WATCH_DIR: str = os.getenv("LOG_WATCH_DIR", "./sample_logs")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:latest")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    LOG_STREAM_INTERVAL: float = float(os.getenv("LOG_STREAM_INTERVAL", "1.0"))


settings = Settings()

__all__ = ["settings"]
