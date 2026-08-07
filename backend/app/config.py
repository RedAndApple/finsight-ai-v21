from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "finsight.db"))
SAMPLE_DIR = ROOT_DIR / "samples"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    # Generic OpenAI-compatible gateway. Works with OpenRouter and a private base URL.
    ai_api_key: str = _first_env("AI_API_KEY", "OPENROUTER_API_KEY")
    ai_base_url: str = _first_env("AI_BASE_URL", default="https://openrouter.ai/api/v1").rstrip("/")
    ai_model: str = _first_env("AI_MODEL", "OPENROUTER_MODEL", default="openrouter/free")
    ai_site_url: str = _first_env("AI_SITE_URL", "OPENROUTER_SITE_URL", default="http://localhost:8000")
    ai_app_name: str = _first_env("AI_APP_NAME", "OPENROUTER_APP_NAME", default="FinSight AI")
    ai_auth_header: str = os.getenv("AI_AUTH_HEADER", "Authorization").strip() or "Authorization"
    ai_auth_scheme: str = os.getenv("AI_AUTH_SCHEME", "Bearer").strip()
    auto_ai: bool = _env_bool("AUTO_AI")

    # Backward-compatible aliases used by older code/UI.
    @property
    def openrouter_api_key(self) -> str:
        return self.ai_api_key

    @property
    def openrouter_model(self) -> str:
        return self.ai_model

    @property
    def openrouter_site_url(self) -> str:
        return self.ai_site_url

    @property
    def openrouter_app_name(self) -> str:
        return self.ai_app_name

    enable_ocr: bool = _env_bool("ENABLE_OCR", "true")
    ocr_visuals: bool = _env_bool("OCR_VISUALS")
    ocr_language: str = os.getenv("OCR_LANGUAGE", "rus+eng")
    # Scan OCR quality settings. Scale 3.4 is roughly 245 dpi for PDF rendering.
    ocr_dpi_scale: float = float(os.getenv("OCR_DPI_SCALE", "3.0"))
    ocr_form_dpi_scale: float = float(os.getenv("OCR_FORM_DPI_SCALE", "3.5"))
    ocr_text_dpi_scale: float = float(os.getenv("OCR_TEXT_DPI_SCALE", "2.8"))
    ocr_primary_form_pages: int = int(os.getenv("OCR_PRIMARY_FORM_PAGES", "14"))
    ocr_max_pages: int = int(os.getenv("OCR_MAX_PAGES", "0"))  # 0 = all pages
    ocr_min_text_chars: int = int(os.getenv("OCR_MIN_TEXT_CHARS", "80"))
    ocr_quality_warning: float = float(os.getenv("OCR_QUALITY_WARNING", "62"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "100"))
    max_ai_chunks: int = int(os.getenv("MAX_AI_CHUNKS", "12"))
    ai_chunk_chars: int = int(os.getenv("AI_CHUNK_CHARS", "14000"))


settings = Settings()

for directory in (DATA_DIR, UPLOAD_DIR, RESULT_DIR):
    directory.mkdir(parents=True, exist_ok=True)
