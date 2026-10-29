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
    llm_model: str = _env("DR_LLM", "qwen3:4b")       # chosen by the model x method benchmark (with binding)
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
    # Latency (laptop: prompt reading ~330 tok/s dominates): the answer was always within the top
    # 5 reranked passages on the fact set, so 5 go to the LLM instead of 10.
    max_passages: int = int(_env("DR_MAX_PASSAGES", "5"))
    # Only the sentences of those passages that the reranker scores highest are sent (prompt reading
    # is the slow half); 0 = send whole passages.
    max_sentences: int = int(_env("DR_MAX_SENTENCES", "14"))
    # character budget of the passages sent to the model (≈3 characters per token for Vietnamese):
    # a list question had reached 5,000 prompt tokens (18 s of prompt reading) through long table rows
    prompt_chars_fact: int = int(_env("DR_PROMPT_CHARS_FACT", "3500"))
    prompt_chars_wide: int = int(_env("DR_PROMPT_CHARS_WIDE", "7000"))
    # How the answer style is chosen: "prompt" = from the question (fact / summary / compare / list /
    # full text, dr/core/intent.py); "role" = BRD v1.4 BR-04 (no Investor.AI.Summarize -> quotes only).
    answer_mode: str = _env("DR_ANSWER_MODE", "prompt")
    # Short answers: a claim is dropped when its reranker relevance to the question is below
    # relevance_min AND it shares fewer than relevance_overlap of the question's key terms
    # (calibrated: keeps 45/46 right answers, drops 453/460 off-topic ones and both real cases).
    relevance_min: float = float(_env("DR_RELEVANCE_MIN", "0.1"))
    relevance_overlap: float = float(_env("DR_RELEVANCE_OVERLAP", "0.6"))
    llm_keep_alive: str = _env("DR_LLM_KEEP_ALIVE", "24h")    # keep the model loaded (Ollama unloads after 5 min)
    answer_cache: int = int(_env("DR_ANSWER_CACHE", "2000"))  # LLM outputs memoised by exact input; 0 = off
    input_guard: bool = _env("DR_INPUT_GUARD", "1") == "1"   # layer 2: normalisation + injection rules + classifier
    mask_pii: bool = _env("DR_MASK_PII", "1") == "1"         # mask personal identifiers in questions, answers, audit
    rate_per_minute: int = int(_env("DR_RATE_MIN", "8"))
    rate_per_hour: int = int(_env("DR_RATE_HOUR", "60"))
    llm_concurrency: int = int(_env("DR_LLM_CONCURRENCY", "2"))
    # Sensitive questions: "contact" = not answered, the asker is pointed to a named person;
    # "review" = answered as a draft that a Reviewer must approve (dr/core/review.py).
    sensitive_mode: str = _env("DR_SENSITIVE_MODE", "contact")
    sensitive_contact: str = _env("DR_SENSITIVE_CONTACT", "chú Trần Kim Chung")
    sensitive_contact_en: str = _env("DR_SENSITIVE_CONTACT_EN", "Mr. Tran Kim Chung")
    search_backend: str = _env("DR_SEARCH", "pg")
    tenant_mode: str = _env("DR_TENANT", "fake")          # fake (simulated SharePoint/Entra) | m365 (Microsoft Graph)
    m365_config: Path = field(default_factory=lambda: Path(_env("DR_M365_CONFIG", str(ROOT / "data" / "m365.json"))))  # pg (pgvector + BM25 in Postgres, RLS in the query) | memory
    nli_threshold: float = float(_env("DR_NLI_THRESHOLD", "0.5"))
    # binding: a number must keep its meaning (price, budget, area…) between the claim and its quote
    # (dr/core/verify.py unbound); DR_BINDING=0 turns it off.
    binding: bool = _env("DR_BINDING", "1") == "1"
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

NEUTRAL_REFUSAL = ("Rất tiếc, chưa tìm thấy thông tin phù hợp trong các tài liệu được chia sẻ với Quý vị. "
                   "Quý vị có thể diễn đạt lại câu hỏi hoặc liên hệ Ban IPO để được hỗ trợ.")
OUT_OF_SCOPE_MESSAGE = ("Câu hỏi của Quý vị liên quan đến thông tin dành riêng cho nhóm nhà đầu tư khác, "
                        "nằm ngoài phạm vi tài liệu được chia sẻ với Quý vị. Rất mong Quý vị thông cảm. "
                        "Nếu cần hỗ trợ thêm, Quý vị vui lòng liên hệ Ban IPO.")
BLOCKED_MESSAGE = ("Câu hỏi có dấu hiệu yêu cầu trợ lý bỏ qua quy tắc, tiết lộ cấu hình hoặc vượt quyền, nên không được xử lý. "
                   "Hãy hỏi trực tiếp về nội dung tài liệu.")
RATE_MESSAGE = "Bạn đang hỏi quá nhanh. Vui lòng thử lại sau {seconds} giây."
RETRY_MESSAGE = "Hệ thống chưa xác minh được đầy đủ nguồn lúc này, vui lòng thử lại sau ít phút."
UNAVAILABLE_MESSAGE = "Trợ lý AI tạm ngừng để đảm bảo an toàn phân quyền. Vui lòng thử lại sau."
