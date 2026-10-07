"""Central settings for the demo. Values can be overridden with environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: Path(_env("DR_DATA", str(ROOT / "data"))))
    pgdata: Path = field(default_factory=lambda: Path(_env("DR_PGDATA", str(ROOT / "pgdata"))))
    pg_port: int = int(_env("DR_PG_PORT", "55432"))
    pg_db: str = _env("DR_PG_DB", "dataroom")
    pg_bin: Path = Path(_env("DR_PG_BIN", "/usr/local/opt/postgresql@15/bin"))

    ollama_url: str = _env("DR_OLLAMA", "http://127.0.0.1:11434")
    llm_model: str = _env("DR_LLM", "qwen2.5:7b")
    embed_model: str = _env("DR_EMBED", "bge-m3")
    rerank_model: str = _env("DR_RERANK", "BAAI/bge-reranker-v2-m3")
    nli_model: str = _env("DR_NLI", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")

    group_lag_seconds: float = float(_env("DR_GROUP_LAG", "60"))
    poll_seconds: float = float(_env("DR_POLL", "5"))
    feed_max_age_seconds: float = float(_env("DR_FEED_MAX_AGE", "30"))
    token_ttl_seconds: int = int(_env("DR_TOKEN_TTL", "3600"))
    token_secret: str = _env("DR_TOKEN_SECRET", "demo-secret-change-me")

    max_files: int = int(_env("DR_MAX_FILES", "8"))
    rerank_top: int = int(_env("DR_RERANK_TOP", "40"))
    nli_threshold: float = float(_env("DR_NLI_THRESHOLD", "0.5"))
    # OCR: PaddleOCR-VL-1.6 served by mlx-vlm on the Apple GPU; PP-OCRv5 latin as fallback.
    ocr_server_url: str = _env("DR_OCR_SERVER", "http://127.0.0.1:8111/")
    ocr_vl_model: str = _env("DR_OCR_VL_MODEL", str(Path.home() / ".paddlex/official_models/PaddleOCR-VL-1.6"))
    ocr_engine: str = _env("DR_OCR_ENGINE", "vl")  # vl | ppocr
    ocr_max_pages: int = int(_env("DR_OCR_MAX_PAGES", "40"))  # per document, keeps big scanned prospectuses bounded

    @property
    def tenant_dir(self) -> Path:
        return self.data_dir / "tenant"

    @property
    def sock_dir(self) -> Path:
        return self.pgdata / "sock"

    def dsn(self, user: str) -> str:
        return f"host={self.sock_dir} port={self.pg_port} dbname={self.pg_db} user={user}"


settings = Settings()

NEUTRAL_REFUSAL = "Không tìm thấy thông tin phù hợp trong các tài liệu bạn được phép truy cập."
RETRY_MESSAGE = "Hệ thống chưa xác minh được đầy đủ nguồn lúc này, vui lòng thử lại sau ít phút."
UNAVAILABLE_MESSAGE = "Trợ lý AI tạm ngừng để đảm bảo an toàn phân quyền. Vui lòng thử lại sau."
