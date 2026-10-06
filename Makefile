PY      := .venv/bin/python
UV      ?= $(shell command -v uv || echo $(HOME)/.local/bin/uv)
VL_DIR  := $(HOME)/.paddlex/official_models/PaddleOCR-VL-1.6
PORT    ?= 8000

.PHONY: setup models pg-start pg-stop ocr-server data public ingest run test test-all reset-db

setup:            ## create venv + install dependencies
	$(UV) venv --python 3.11 .venv
	$(UV) pip install --python $(PY) -r pyproject.toml
	$(UV) pip install --python $(PY) "paddlex[ocr,genai-client]==3.7.2" mlx-vlm

models:           ## pre-download PaddleOCR-VL, reranker, NLI; pull Ollama models
	$(PY) -c "from paddleocr import PaddleOCRVL; PaddleOCRVL(use_doc_orientation_classify=False, use_doc_unwarping=False)" || true
	$(PY) -c "from huggingface_hub import snapshot_download as s; [s(m) for m in ['BAAI/bge-reranker-v2-m3','MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7']]"
	ollama pull qwen2.5:7b
	ollama pull bge-m3

pg-start:         ## start the project-local Postgres (unix socket in ./pgdata/sock)
	$(PY) -c "from dr.db import pg; pg.ensure_cluster(); print('postgres ok')"

pg-stop:
	$(PY) -c "from dr.db import pg; pg.stop_cluster()"

ocr-server:       ## PaddleOCR-VL-1.6 on the Apple GPU via mlx-vlm (keep running during ingest)
	$(PY) -m mlx_vlm.server --model $(VL_DIR) --trust-remote-code --host 127.0.0.1 --port 8111

data:             ## generate the synthetic Sao Mai corpus (~500 files, all formats)
	$(PY) scripts/gen_corpus.py --n 500 --seed 7 --out data/tenant

public:           ## download approved public IPO documents (see data/public_sources.json)
	$(PY) scripts/fetch_public.py

ingest:           ## sync permissions + parse/OCR/embed everything pending
	$(PY) scripts/ingest.py --workers 3

run:              ## start the demo at http://localhost:$(PORT)
	$(PY) -m uvicorn dr.gateway.app:app --host 127.0.0.1 --port $(PORT)

test:             ## fast tests (no LLM)
	$(PY) -m pytest -q -m "not slow and not e2e"

test-all:
	$(PY) -m pytest -q

reset-db:         ## wipe demo data (keeps schema)
	$(PY) -c "from dr.db import pg; pg.ensure_cluster(); pg.reset_all()"
