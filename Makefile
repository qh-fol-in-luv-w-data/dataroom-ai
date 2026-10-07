PY      := .venv/bin/python
UV      ?= $(shell command -v uv || echo $(HOME)/.local/bin/uv)
VL_DIR  := $(HOME)/.paddlex/official_models/PaddleOCR-VL-1.6
PORT    ?= 8000

.PHONY: setup models pgvector pg-start pg-stop ocr-server data accounts public ingest migrate-search run leak-test qa-eval hard-scans ocr-eval attack-set train-guard attack-eval m365-probe run-m365 scale-test test test-all reset-db

setup:            ## create venv + install dependencies
	$(UV) venv --python 3.11 .venv
	$(UV) pip install --python $(PY) -r pyproject.toml
	$(UV) pip install --python $(PY) "paddlex[ocr,genai-client]==3.7.2" mlx-vlm

models:           ## pre-download PaddleOCR-VL, reranker, NLI; pull Ollama models
	$(PY) -c "from paddleocr import PaddleOCRVL; PaddleOCRVL(use_doc_orientation_classify=False, use_doc_unwarping=False)" || true
	$(PY) -c "from huggingface_hub import snapshot_download as s; [s(m) for m in ['BAAI/bge-reranker-v2-m3','MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7']]"
	ollama pull qwen2.5:7b
	ollama pull bge-m3

pgvector:         ## build + install pgvector 0.8.7 into the Homebrew postgresql@15 (x86_64)
	rm -rf $${TMPDIR:-/tmp}/pgvector && git clone -q --depth 1 --branch v0.8.7 https://github.com/pgvector/pgvector.git $${TMPDIR:-/tmp}/pgvector
	cd $${TMPDIR:-/tmp}/pgvector && arch -x86_64 make install PG_CONFIG=/usr/local/opt/postgresql@15/bin/pg_config OPTFLAGS="" PG_SYSROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk

pg-start:         ## start the project-local Postgres (unix socket in ./pgdata/sock)
	$(PY) -c "from dr.db import pg; pg.ensure_cluster(); print('postgres ok')"

pg-stop:
	$(PY) -c "from dr.db import pg; pg.stop_cluster()"

ocr-server:       ## PaddleOCR-VL-1.6 on the Apple GPU via mlx-vlm (keep running during ingest)
	$(PY) -m mlx_vlm.server --model $(VL_DIR) --trust-remote-code --host 127.0.0.1 --port 8111

data:             ## generate the synthetic Sao Mai corpus (~500 files, all formats)
	$(PY) scripts/gen_corpus.py --n 500 --seed 7 --out data/tenant
	$(PY) scripts/seed_accounts.py

accounts:         ## new random demo password (hashes in tenant.json, plain text in data/tenant/DEMO_ACCOUNTS.md)
	$(PY) scripts/seed_accounts.py

public:           ## download approved public IPO documents (see data/public_sources.json)
	$(PY) scripts/fetch_public.py

ingest:           ## sync permissions + parse/OCR/embed everything pending
	$(PY) scripts/ingest.py --workers 3

migrate-search:   ## one-off: fill pgvector/tsvector columns for chunks ingested before the switch
	$(PY) scripts/migrate_pg_search.py

run:              ## start the demo at http://localhost:$(PORT)
	$(PY) -m uvicorn dr.gateway.app:app --host 127.0.0.1 --port $(PORT)

leak-test:        ## leak matrix on the live demo DB (every user x every marker / secret)
	$(PY) scripts/leak_matrix.py

qa-eval:          ## end-to-end Q&A on the secret facts with the real LLM
	$(PY) scripts/qa_eval.py

hard-scans:       ## generate 40 hard scanned documents + truth (data/eval/hard_scans)
	$(PY) scripts/gen_hard_scans.py --n 40

ocr-eval:         ## OCR accuracy on the hard scans: raw vs cleaned, number cross-check (needs ocr-server)
	$(PY) scripts/ocr_eval.py

attack-set:       ## multilingual prompt-attack dataset (train / held-out test)
	$(PY) scripts/gen_attack_set.py

train-guard:      ## train the input-guard classifier on bge-m3 embeddings (needs Ollama)
	$(PY) scripts/train_guard.py

attack-eval:      ## red-team the guard on the held-out set, then 30 attacks end to end with the guard off
	$(PY) scripts/attack_eval.py --e2e 30

m365-probe:       ## the 9 Microsoft 365 integration tests on a test site (needs data/m365.json)
	$(PY) scripts/m365_probe.py --user

run-m365:         ## the AI core on real SharePoint/Entra (Entra sign-in, Graph connector, OBO live check)
	DR_TENANT=m365 $(PY) -m uvicorn dr.gateway.app:app --host 127.0.0.1 --port $(PORT)

scale-test:       ## 1M-chunk load test of the in-database search (separate DB dataroom_scale, ~10 GB)
	$(PY) scripts/scale_test.py load --n 1000000
	$(PY) scripts/scale_test.py bench

test:             ## fast tests (no LLM)
	$(PY) -m pytest -q -m "not slow and not e2e"

test-all:
	$(PY) -m pytest -q

reset-db:         ## wipe demo data (keeps schema)
	$(PY) -c "from dr.db import pg; pg.ensure_cluster(); pg.reset_all()"
