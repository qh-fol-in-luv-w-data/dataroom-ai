# Data Room AI Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, single-command demo of the permission-aware RAG core from the master plan v0.5. It covers a simulated SharePoint and Entra, a Postgres RLS mirror, four permission gates, PaddleOCR/PP-StructureV3 parsing, bge-m3 + reranker + NLI, and qwen2.5:7b answers, all over roughly 500 multi-format Vietnamese documents plus real public IPO documents.

**Architecture:** One FastAPI process hosts the components below. Each has its own module and interface.

- `fake_tenant` is the source of truth for files, groups and permissions, with simulated SharePoint group lag.
- A background `connector` polls tenant delta into Postgres mirror tables.
- `ingest` parses, chunks and embeds documents into Postgres.
- An in-memory search index holds embeddings and BM25 per partition. It is only ever scored over chunk ids that Postgres RLS returns for the caller.
- `core.answer` runs the four gates, LLM, verification and audit.
- A static web UI provides the identity picker, chat, scope, matrix, scenarios and audit views.

**Tech Stack:** Python 3.11 (uv venv), FastAPI, psycopg 3, PostgreSQL 15 (Homebrew, project-local cluster, unix socket), Ollama (`qwen2.5:7b`, `bge-m3`), PaddleOCR 3.x (PP-OCRv5 latin/vi, PP-StructureV3), sentence-transformers (`BAAI/bge-reranker-v2-m3`), transformers (`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`), rank-bm25, reportlab/python-docx/openpyxl/python-pptx for corpus generation, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-dataroom-ai-demo-design.md`

## Global Constraints

- **Platform:** macOS arm64, 18 GB RAM. No Docker. Ollama.app must be running for embeddings and answers.
- **Postgres:**
  - Cluster lives in `./pgdata`. Listens only on the unix socket `./pgdata/sock` (no TCP); port 55432 is used only to name the socket.
  - The app role `app_query` has no BYPASSRLS. Every table holding document content or permissions uses `FORCE ROW LEVEL SECURITY`.
  - Identity is set with `set_config('app.principal_oid', <oid>, true)` inside a transaction.
- **Demo timing:** `GROUP_LAG_SECONDS=60` (SharePoint lag), `POLL_SECONDS=5`, `FEED_MAX_AGE_SECONDS=30`, `TOKEN_TTL_SECONDS=3600`.
- **Fail-closed rules:**
  - Live check: anything other than 200 with a matching cTag and an allowed `AI_Use` drops the file silently.
  - A stale Entra feed refuses every question with the neutral message.
- **Answer delivery:** answers are released as one block after verification. Neutral refusal text: `"Không tìm thấy thông tin phù hợp trong các tài liệu bạn được phép truy cập."`
- **User-visible text** is Vietnamese. Code and comments are English.
- **Data budget:** generated and downloaded data ≤ 1.5 GB. Public documents are downloaded only after the user approves the list.

---

### Task 1: Project skeleton, config, Postgres lifecycle

**Files:**
- Create: `dr/__init__.py`, `dr/config.py`, `dr/db/pg.py`, `dr/db/schema.sql`, `Makefile`, `tests/conftest.py`, `tests/test_rls.py`

**Interfaces:**
- Produces:
  - `dr.config.settings` (dataclass `Settings`: paths, `pg_dsn_admin`, `pg_dsn_app`, model names, timing constants);
  - `dr.db.pg.ensure_cluster() -> None` (initdb if missing, start pg_ctl, create db and roles, apply schema);
  - `dr.db.pg.admin() -> psycopg.Connection`;
  - `dr.db.pg.as_principal(oid: str) -> contextmanager[psycopg.Cursor]` (opens a transaction as `app_query`, sets `app.principal_oid`).

Schema tables:

| Table | Columns | RLS predicate |
|---|---|---|
| `items` | item_id, site_id, path, name, ext, ctag, etag, ai_use, encrypted, malware, web_url, size, status, reason | `item_id IN (SELECT item_id FROM item_reader WHERE oid = current_setting('app.principal_oid', true))` |
| `chunks` | chunk_id, item_id, site_id, ctag, is_current, ordinal, locator, text, text_folded, injection_flag, converter | Item readable **and** `items.ai_use IN ('Allowed','OnPremOnly')` **and** not encrypted, not malware **and** `chunks.is_current` **and** `chunks.ctag = items.ctag` |
| `item_reader` | item_id, oid, via_kind, via_id (the grant path) | Self only |
| `grants` | item_id, principal_kind, principal_id, source | None (app_query cannot select) |
| `memberships` | group_id, oid | None (app_query cannot select) |
| `revocations` | oid, group_id, created_at, until | None (app_query cannot select) |
| `deny_list` | oid, reason, created_at | None (app_query cannot select) |
| `feed_status` | feed, last_ok, detail | None (app_query cannot select) |
| `audit` | seq, ts, oid, kind, payload jsonb, prev_hash, row_hash | INSERT only for app_query |

Postgres functions for app_query, all `SECURITY DEFINER` with a fixed search_path:

- `me_denied() -> bool`
- `feed_age(feed text) -> float`

- [ ] **Step 1:** Write `tests/test_rls.py`.
  - (a) `as_principal('nobody')` sees 0 rows in `items` and `chunks`.
  - (b) Insert two items. Grant item1 to oid `u1` via `item_reader` with the admin connection. `as_principal('u1')` sees only item1.
  - (c) An `app_query` connection without `set_config` sees 0 rows.
  - (d) `app_query` cannot `SELECT` from `memberships` (permission denied).
- [ ] **Step 2:** Run `pytest tests/test_rls.py`. Expect failure (no module).
- [ ] **Step 3:** Implement `config.py`, `pg.py` and `schema.sql` as above. The `Makefile` targets are `setup`, `pg-start`, `pg-stop`, `data`, `ingest`, `run`, `test`.
- [ ] **Step 4:** Run the tests. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 2: Fake tenant (SharePoint + Entra simulation)

**Files:**
- Create: `dr/tenant/model.py`, `dr/tenant/service.py`, `tests/test_tenant.py`

**Interfaces:**
- `TenantState` is loaded from `data/tenant/tenant.json`. It holds users, groups, app roles, sites, folders and items. Each item has: id, site, path, name, ext, file path, ctag, etag, ai_use, encrypted, malware, versions, grants (inherit flag + list of `{kind: group|user|link_specific|link_anyone|link_org, id}`).
- `FakeTenant(path)` methods:
  - `.entra_delta(cursor:int) -> (events, cursor)`. Membership, user enabled and role events, visible immediately.
  - `.drive_delta(cursor:int) -> (events, cursor)`. Item add, change and delete events, carrying ctag, etag, ai_use and flags.
  - `.permissions(item_id) -> list[Grant]` (resolved, inheritance applied).
  - `.sp_can_read(oid, item_id, now=None) -> bool`. SharePoint's view: group membership changes take effect only after `GROUP_LAG_SECONDS`, and "Anyone" or organization links are honoured only for anonymous access, which never happens here.
  - `.get_item_as_user(oid, item_id) -> (status:int, meta:dict|None)`. Live check: 200 with `{id, ctag, etag, ai_use}`, or 403 / 404.
  - `.download(item_id) -> bytes`. App-only.
  - Mutations used by scenarios: `remove_member`, `add_member`, `set_user_enabled`, `set_ai_use`, `publish_version(item_id)` (swaps in the prepared v2 file and changes ctag), `pause_entra_feed(bool)`.
  - `.snapshot_counts()`.

- [ ] **Step 1:** Write `tests/test_tenant.py` against a small fixture tenant written inline. It covers:
  - inheritance;
  - a unique-permission folder;
  - a specific-people link that grants, and an Anyone link that does not;
  - group lag: right after `remove_member`, `sp_can_read` is still True and `entra_delta` already shows the removal; after advancing a fake clock past the lag, it is False;
  - `publish_version` changes ctag and emits a drive event;
  - `get_item_as_user` returns 403 for a non-reader.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement with an injectable clock (`now_fn`).
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 3: Connector (mirror, revocation set, freshness)

**Files:**
- Create: `dr/connector/sync.py`, `tests/test_connector.py`

**Interfaces:**
- `Connector(tenant, now_fn).poll_once() -> dict`. It:
  - applies drive and Entra delta;
  - upserts `items`, `grants`, `memberships`;
  - on a membership removal, inserts `revocations(oid, group, until = now + GROUP_LAG_SECONDS + 5)`;
  - rebuilds `item_reader` from grants × memberships (direct user grants and specific-people links), skipping any path through a revoked `(oid, group)`;
  - updates `feed_status`.
  - Returns change counts, including the item ids whose ctag changed or that were deleted, so ingest can react.
- On a ctag change it runs `UPDATE chunks SET is_current=false WHERE item_id=…` immediately.
- On deletion it deletes the item's chunks and the item.
- `Connector.run_forever(stop_event)` runs as a background thread.

- [ ] **Step 1:** Write tests.
  - After a poll, `item_reader` matches `tenant.sp_can_read` for all (user, item) pairs when no change is pending.
  - After `remove_member(u, A)`, the next poll leaves u with no rows for items reachable only via A, while `sp_can_read` is still True (lag).
  - A user in both A and B keeps the B items.
  - `pause_entra_feed` makes `feed_age('entra')` grow.
  - `publish_version` sets `is_current=false` on old chunks.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 4: Corpus generator (synthetic, about 500 files, all formats)

**Files:**
- Create: `scripts/gen_corpus.py`, `scripts/corpus/` (templates: `company.py` facts, `writers.py` per format), `tests/test_corpus.py`

**Interfaces:**
- `python scripts/gen_corpus.py --n 500 --seed 7` writes `data/tenant/files/**` and `data/tenant/tenant.json`.
- Every file embeds its site marker `KS-<SITE>-<4 digits>` and the document id.
- `data/tenant/facts.json` holds the per-site secret facts with expected answers, used by the leak and QA tests.

Formats:

- docx: contracts, resolutions; one with a prompt injection.
- xlsx: financial statements with a unit row and one hidden sheet.
- pptx: investor decks with notes.
- PDF:
  - text PDFs via reportlab with a Vietnamese TTF from `/System/Library/Fonts/Supplemental/Arial Unicode.ttf`;
  - scanned PDFs: render text to an image, add a red seal, rotation and noise, embed as image-only;
  - a PDF with hidden white text;
  - an encrypted PDF (pypdf `encrypt`).
- eml with docx/xlsx/pdf attachments.
- html due-diligence reports.
- csv asset registers.
- md/txt.
- png/jpg scanned licences.
- One file per special case: malware facet with the custom signature string `DATAROOM-DEMO-MALWARE-SIGNATURE`; `ai_use=Excluded`; a contract with a prepared v2 (redacted); a unique-permission folder for `inv-a1` only; a specific-people link in GRP-B for `inv-c1`; an Anyone link in COMMON.

Users:

| Oid | Who | Groups and roles |
|---|---|---|
| inv-a1, inv-a2 | Group A investors | DR-INV-A |
| inv-b1, inv-b2 | Group B investors | DR-INV-B |
| inv-c1 | Group C investor | DR-INV-C |
| inv-ab | Investor in both A and B | DR-INV-A, DR-INV-B |
| inv-noai | Group A investor | DR-INV-A, without `Investor.AI` |
| adv-1 | Adviser | ADVISERS, `Staff.AI` |
| staff-1 | Staff | STAFF, `Staff.AI` |
| rev-1 | Reviewer | REVIEWERS + STAFF, `Reviewer` |
| admin | Demo console | — |

Sites and their groups (RAC = the same list):

| Site | Groups |
|---|---|
| COMMON | DR-INV-A, DR-INV-B, DR-INV-C, ADVISERS, STAFF |
| GRP-A | DR-INV-A, ADVISERS, STAFF |
| GRP-B | DR-INV-B, ADVISERS, STAFF |
| GRP-C | DR-INV-C, ADVISERS, STAFF |
| INTERNAL | STAFF |

- [ ] **Step 1:** Write tests: run the generator with `--n 60` into a tmp dir. Check that every format is present, every item's file exists, each site's marker appears in at least one file of that site and in none outside it, and every special case is present.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Generate the full corpus (`--n 500`) and commit the code. `data/tenant/files` is gitignored.

### Task 5: Parsers + Paddle OCR/structure

**Files:**
- Create: `dr/ingest/safety.py`, `dr/ingest/ocr.py`, `dr/ingest/parsers.py`, `dr/ingest/chunker.py`, `tests/test_parsers.py`

**Interfaces:**
- `safety.inspect(data:bytes, ext:str) -> SafetyResult(ok:bool, reason:str|None, encrypted:bool, malware:bool)`. Detects:
  - the custom signature;
  - an encrypted PDF (pypdf `is_encrypted`);
  - an OLE container where OOXML is expected (encrypted Office);
  - a zip bomb (ratio > 100 or > 50 MB uncompressed);
  - a type mismatch.
- `ocr.ocr_image(img: PIL.Image) -> list[Line(text, bbox, score)]`: PaddleOCR `lang='vi'`, lazy singleton, Tesseract fallback on error.
- `ocr.structure_pdf_pages(pdf_bytes, pages:list[int]) -> list[PageBlocks]`: PP-StructureV3 with layout, table and seal on; formula and chart off; tables returned as markdown.
- `parsers.parse(data:bytes, ext:str, name:str) -> ParsedDoc(blocks: list[Block(kind, text, locator, meta)], converter:str, attachments: list[(name, ext, bytes)])`:
  - PDF: text-layer quality score; good pages use pypdfium2 text, bad or scanned pages use `structure_pdf_pages`.
  - docx: paragraphs with heading path, tables, embedded images to OCR.
  - xlsx: cached values, number formats, a unit from the header row (`đơn vị`), hidden sheets flagged as `meta.hidden=True`, locator `Sheet!A1:D20`.
  - pptx: slide text and notes.
  - eml: headers and body, attachments returned.
  - html: BeautifulSoup text.
  - csv, txt, md.
  - png and jpg: `ocr_image`.
- `chunker.chunk(doc: ParsedDoc, max_chars=800) -> list[Chunk(text, locator, ordinal, injection_flag)]`, plus `fold(text)` (unidecode, lowercase).

- [ ] **Step 1:** Write tests on small generated fixtures, one per format:
  - each format parses to non-empty text containing its marker;
  - xlsx keeps the unit and flags the hidden sheet;
  - the encrypted PDF is reported as encrypted;
  - the signature file is reported as malware;
  - the scanned PDF's OCR output contains its marker (marked `slow`, needs Paddle).
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 6: Ingest pipeline + embeddings + search index

**Files:**
- Create: `dr/ingest/pipeline.py`, `dr/models/embed.py`, `dr/core/index.py`, `scripts/ingest.py`, `tests/test_index.py`

**Interfaces:**
- `embed.embed_texts(texts:list[str]) -> np.ndarray[float32, (n,1024)]` via Ollama `/api/embed` with model `bge-m3`, batched by 32 and L2-normalised.
- `pipeline.ingest_item(tenant, item_id) -> dict` downloads the file, then runs safety, parse, chunk, embed, and inserts the chunks with the current ctag. On a skip, it marks `items.status/reason`.
- `pipeline.ingest_pending(tenant, workers=2)` processes items whose `status` is pending or whose ctag changed.
- `index.SearchIndex`:
  - loads all current chunks into memory: id, item, site, folded tokens, embedding;
  - `.refresh()` picks up new chunk ids;
  - `.search(allowed_ids:set[int], query:str, qvec, k=40) -> list[(chunk_id, score)]`.
  - BM25 is built **per site partition** over both accented and folded tokens. Scores are computed only for `allowed_ids`.
  - Vector cosine runs over `allowed_ids` only. Results are merged with RRF (k=60).

- [ ] **Step 1:** Write tests with a fake embedder (hash-based vectors):
  - search never returns ids outside `allowed_ids`;
  - an unaccented query finds an accented chunk;
  - the per-partition BM25 statistics of site A do not change when documents are added to site B.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 7: Reranker, NLI, LLM, verification

**Files:**
- Create: `dr/models/rerank.py`, `dr/models/nli.py`, `dr/models/llm.py`, `dr/core/verify.py`, `tests/test_verify.py`

**Interfaces:**
- `rerank.rerank(query, passages:list[str]) -> list[float]`: CrossEncoder `BAAI/bge-reranker-v2-m3`, device mps if available, `max_length=512`.
- `nli.entail(premise, hypothesis) -> float`: probability of entailment.
- `llm.answer_json(question, passages:list[dict(chunk_id, text, source)]) -> dict`: Ollama `/api/chat` with `format` set to the JSON schema `{claims:[{text, citations:[{chunk_id:int, quote:str}]}], refusal:bool}`, `temperature=0`. The system prompt is in Vietnamese and requires verbatim quotes from `<untrusted_document id=…>`.
- `verify.check(claims, passages_by_id) -> (kept:list[Claim], dropped:list[(Claim, reason)])`. Rules:
  - the cited chunk_id must be in the passage set;
  - the normalised quote must be a substring of the normalised passage (whitespace and Unicode NFC; a fuzzy ratio ≥ 0.9 is allowed for OCR passages);
  - every number in the claim text must appear in at least one of its quotes after `vn_number` normalisation.
- `verify.vn_numbers(text) -> set[Decimal]` handles `1.234,5`, `1,234.5`, `tỷ`/`triệu`/`nghìn` and `%`.

- [ ] **Step 1:** Write tests for `vn_numbers`, quote matching, number mismatch rejection and an invented chunk_id. All are pure: no models.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement. Model loaders are lazy singletons.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 8: Answer orchestration (four gates) + audit chain

**Files:**
- Create: `dr/core/gates.py`, `dr/core/answer.py`, `dr/audit.py`, `tests/test_gates.py`, `tests/test_audit.py`

**Interfaces:**
- `gates.principal_gate(token_claims) -> GateResult`: checks the role (`Investor.AI` or `Staff.AI`), deny_list and Entra feed age.
- `gates.allowed_chunk_ids(oid) -> set[int]`: a Postgres query under `as_principal`. This is gate 1, and it already excludes revoked paths via `item_reader`.
- `gates.live_check(tenant, oid, item_ids) -> dict[item_id, bool]`: gate 2, comparing ctag and ai_use with the mirror. The mirror ctag is read under RLS.
- `answer.ask(tenant, index, token_claims, question, scope_site=None) -> AnswerResult(text_blocks, claims, citations, refused:bool, trace:list[step])`. Steps:
  1. principal gate;
  2. allowed ids;
  3. index.search;
  4. fetch texts under RLS;
  5. rerank top 40 and keep the best up to 8 files;
  6. live check, dropping silently and backfilling;
  7. LLM;
  8. verify plus NLI scores;
  9. second live check on cited files (dropping claims whose file failed) and principal gate again;
  10. audit.
- `audit.append(kind, oid, payload) -> int` serialises with `pg_advisory_xact_lock`; `row_hash = sha256(prev_hash || canonical_json)`. `audit.verify() -> (ok:bool, first_bad_seq:int|None)`.

- [ ] **Step 1:** Write tests using a stub LLM (returns a claim quoting the first passage) and a stub reranker:
  - a user without the role is refused;
  - stale feed is refused;
  - a file failing the live check never appears in citations;
  - a corrupted mirror (an injected fake `item_reader` row) is still blocked by the live check;
  - the audit chain verifies, and tampering with a row is detected.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 9: Gateway API + scenarios

**Files:**
- Create: `dr/gateway/app.py`, `dr/gateway/auth.py`, `dr/gateway/scenarios.py`, `tests/test_api.py`

**Interfaces:**
- `auth.issue(oid) -> token` (HMAC-signed JSON carrying oid, roles and exp); `auth.verify(token) -> claims`.
- Endpoints:
  - `GET /api/users`
  - `POST /api/login {oid}`
  - `POST /api/chat {question, scope_site?}`
  - `GET /api/scope`: tree of sites, folders and files that the caller can open in "SharePoint", each with an AI status: `ai_ok | excluded | encrypted | malware | pending | unsupported`. For files the AI can use, include the chunk count.
  - `GET /api/matrix` (admin)
  - `GET /api/status`
  - `POST /api/scenario/{name}` (admin)
  - `GET /api/audit?limit=`
  - `GET /api/audit/verify`
  - `GET /open/{item_id}?t=token`: the "SharePoint viewer" serves the file inline only if `sp_can_read`.
- Scenarios: `remove_from_group`, `move_group`, `exclude_file`, `publish_redacted_version`, `offboard`, `corrupt_mirror`, `pause_entra_feed`, `reset`. Each returns a description plus what to try next.

- [ ] **Step 1:** Write API tests with TestClient, a stub LLM and a small tenant: login, scope correctness against `sp_can_read`, admin-only endpoints refusing investors, and each scenario changing behaviour as described.
- [ ] **Step 2:** Run. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 10: Web UI

**Files:**
- Create: `web/index.html`, `web/app.js`, `web/style.css`

The UI has an identity picker (grouped: investors, staff, admin) and five tabs:

1. **Chat:** answer blocks; citation chips that open `/open/{id}` and show the locator and an "OCR" badge; per-claim NLI badge; a collapsible gates trace.
2. **Phạm vi của tôi:** the tree with status badges and counts.
3. **Ma trận quyền:** admin only.
4. **Kịch bản:** buttons, a live SharePoint-vs-AI status panel, and a countdown for the group lag.
5. **Nhật ký:** table plus a "Kiểm chuỗi" button.

- [ ] **Step 1:** Implement with vanilla JS (fetch), no build step.
- [ ] **Step 2:** Manual check in the browser via `make run`.
- [ ] **Step 3:** Commit.

### Task 11: Leak matrix + scenario tests on the full corpus

**Files:**
- Create: `tests/test_leak_matrix.py`, `tests/test_scenarios_e2e.py`

- [ ] **Step 1:** Leak matrix. For every user × every site marker, call `allowed_chunk_ids` + `index.search(marker)` (BM25 only). Assert that no returned chunk belongs to an item the user cannot `sp_can_read`, or to an excluded, encrypted or malware item. Also assert that `allowed_ids` equals the set of chunks of readable, AI-usable items (completeness).
- [ ] **Step 2:** Scenario tests on the real corpus with a stub LLM: remove inv-ab from A, then GRP-A markers are gone within one poll while `sp_can_read` is still True; offboard; exclude; publish v2 (the old clause text is no longer retrievable); pause the feed and see a refusal.
- [ ] **Step 3:** Mark the LLM QA checks as `e2e`. For each site fact in `facts.json`, the authorised user gets the fact and unauthorised users get the neutral refusal.
- [ ] **Step 4:** Run all. Commit.

### Task 12: Public documents (after approval) + README

**Files:**
- Create: `scripts/fetch_public.py`, `data/public_sources.json`, `README.md`

- [ ] **Step 1:** Research 30–50 public IPO and disclosure documents (prospectuses, audited financial statements, investor presentations) from official disclosure sites. Record url, title, format and size in `public_sources.json`. **Present the list to the user for approval before downloading.**
- [ ] **Step 2:** After approval, `fetch_public.py` downloads them into `data/tenant/files/COMMON/Cong-bo-thong-tin/` and registers them in `tenant.json`; then re-ingest.
- [ ] **Step 3:** Write the README in Vietnamese: requirements, `make setup / data / ingest / run / test`, a 10-minute demo script and troubleshooting.
- [ ] **Step 4:** Commit.
