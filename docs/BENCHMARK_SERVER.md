# Runbook: cài đặt và chạy benchmark chéo model × phương pháp trên server

> **Dành cho người vận hành trên server.** Làm lần lượt từ bước 0 đến bước 8. Mỗi bước có lệnh **Kiểm tra**: chưa qua thì chưa sang bước sau. Gặp lỗi thì xem bảng ở mục 9 trước. Nếu vẫn không được, dừng lại và báo nguyên văn lỗi; không tự đổi code của pipeline để "cho chạy được".
>
> **Dữ liệu mật CT Group.** Bản dump và `tenant.json` chứa nội dung tài liệu và phân quyền thật.
> - Không tải lên bất kỳ dịch vụ ngoài nào.
> - Không commit thư mục `data/`.
> - Không in nội dung tài liệu ra ngoài các file log của benchmark.
> - Không sửa các test phân quyền.

## 0. Bối cảnh: benchmark đo gì

Hệ thống là RAG data room tiếng Việt chạy trên Postgres. Tìm kiếm kết hợp pgvector và BM25, có RLS, rerank bằng bge-reranker-v2-m3, kiểm chứng bằng mDeBERTa NLI. Các model đều là LLM nhỏ chạy qua Ollama. `scripts/grid_eval.py` chạy **đường trả lời thật** (cổng phân quyền → tìm kiếm → rerank → LLM → kiểm chứng) trên hai bộ câu hỏi, tổng 36 câu:

| Bộ | Script | Câu | Nội dung |
|---|---|---|---|
| OCR | `scripts/ctg_ocr_eval.py` | 28 | Ảnh, PDF scan, câu hỏi nối tiếp, mâu thuẫn giữa tài liệu, 6 câu vượt quyền (phải từ chối) |
| Bảng | `scripts/ctg_table_eval.py` | 8 | Excel, báo giá, so sánh, lớn nhất/nhỏ nhất, biểu đồ |

**Cách xếp hạng:** đúng nhiều hơn đứng trên. Bằng điểm thì xét số câu **trả lời sai**, ít hơn đứng trên (trả lời sai tệ hơn từ chối). Vẫn bằng thì nhanh hơn đứng trên.

**Mốc đã đo trên Mac M-series:** pipeline hiện tại với `qwen2.5:3b` đạt **33/36**, gồm OCR 27/28 và bảng 6/8. Có 1 câu trả lời sai, trung bình 9,2 giây/câu. Trên server, cấu hình này phải ra khoảng 32–34/36. Nếu thấp hơn nhiều, cài đặt có vấn đề (xem mục 9).

### Model

`qwen2.5:3b`, `qwen2.5:7b`, `qwen3:4b` (code tự tắt thinking), `gemma3:4b`, `phi4-mini`.

### Phương pháp

Mỗi phương pháp là một biến môi trường trong `dr/config.py`, **tắt mặc định**.

| Tên | Biến | Làm gì |
|---|---|---|
| `doctype` | `DR_DOCTYPE=1` | Ghi loại tài liệu (bảng giá, hợp đồng, kế hoạch/ngân sách, tuyển dụng…) vào nguồn của mỗi đoạn, kèm quy tắc trong prompt (`dr/core/doctype.py`) |
| `binding` | `DR_BINDING=1` | Con số phải giữ đúng nghĩa giữa câu trả lời và câu trích (giá, ngân sách, diện tích, thu nhập, tiền thuê, thuế) (`verify.unbound`) |
| `two_stage` | `DR_TWO_STAGE=1` | Bước 1 model chỉ chọn câu chứa đáp án, bước 2 mới trả lời từ các câu đó (`llm.pick_sentences`) |
| `fewshot` | `DR_FEWSHOT=1` | Thêm 2 ví dụ bịa về 2 lỗi hay gặp vào prompt |
| `vote3` | `DR_VOTE=3` | Trả lời 3 lần, chọn đáp án đã qua kiểm chứng mà nhiều lần trùng nhau nhất (`answer.vote`) |
| `sent8` / `sent24` | `DR_MAX_SENTENCES=8/24` | Số câu đưa cho model (mặc định 14) |
| `pass3` | `DR_MAX_PASSAGES=3` | Số đoạn đưa cho model (mặc định 5) |
| `fallback7b` | `DR_LLM_FALLBACK=qwen2.5:7b` | Không ý nào qua kiểm chứng thì hỏi lại 7B một lần |

### Giai đoạn

Script tự chạy hết 4 giai đoạn, không cần can thiệp:

1. Mỗi model chạy với pipeline hiện tại.
2. Từng phương pháp riêng lẻ, trên `qwen2.5:3b` và trên model tốt nhất còn lại.
3. Kết hợp tham lam các phương pháp có ích. Phương pháp nào làm điểm giảm thì bỏ.
4. Chạy lại 2 cấu hình tốt nhất.

**Thời gian:** trên Mac khoảng 6–10 phút mỗi cấu hình (`vote3` lâu gấp 2–3 lần), toàn bộ khoảng 4–5 giờ. GPU NVIDIA nhanh hơn.

## 1. Máy đích và đầu vào

**Máy đích:** Coder workspace `nnle/azure-cod-64`.

- Ubuntu 22.04, chạy trong container, có GPU NVIDIA và sudo.
- Máy này **không vào được GitLab nội bộ**. Code được gửi kèm dưới dạng git bundle.
- **`/home/coder` chỉ có 8 GB.** Mọi thứ nặng phải đặt trong **`~/data`**, gồm venv, cache Hugging Face và uv, model Ollama và cụm Postgres. Không đặt vào `~/inference_ocr`: đó là repo GitHub của dự án OCR, không được chứa dữ liệu CT Group.

Thư mục làm việc là `WORK=~/data/ctg_bench`. Người vận hành đã chép sẵn vào đó:

| File | Nội dung |
|---|---|
| `dataroom.bundle` | Git bundle của code, nhánh `ctg-dataroom`, chỉ code |
| `ctg_dataroom.dump` (596 MB) | Dump Postgres của data room CT Group |
| `ctg_tenant.tgz` (0,2 MB) | `tenant.json` (người dùng, nhóm, quyền), các chủ đề nhạy cảm, câu hỏi gợi ý |
| `SHA256SUMS` | Mã kiểm tra của 3 file trên |

Ở máy khác có mạng nội bộ thì clone thẳng từ GitLab: `git clone -b ctg-dataroom https://gitlab.ctgroupvietnam.com/ctpai/dataroom.git`. Thay `~/data` bằng một ổ còn ≥ 25 GB trống.

**Kiểm tra:**

```bash
cd ~/data/ctg_bench && sha256sum -c SHA256SUMS
```

Nếu thiếu file hoặc sai sha256, dừng lại và báo người vận hành. Agent không tự tìm nguồn dữ liệu khác.

## 2. Yêu cầu hệ thống

- Linux (Ubuntu 22.04/24.04) hoặc macOS, RAM ≥ 16 GB, dung lượng trống ≥ 25 GB trên ổ chứa `WORK` (azure-cod-64: `~/data`).
- GPU NVIDIA tuỳ chọn, VRAM ≥ 8 GB. Reranker và NLI tự dùng CUDA nếu có, không có thì chạy CPU (chậm hơn).
- Quyền `sudo` để cài gói hệ thống. Không có sudo thì báo người vận hành cài các gói ở bước 3.

## 3. Cài gói hệ thống

**Ubuntu:**

```bash
sudo apt update
sudo apt install -y git curl build-essential tmux postgresql-14 postgresql-14-pgvector   # Ubuntu 22.04; 24.04: postgresql-16 postgresql-16-pgvector
sudo service postgresql stop 2>/dev/null || true   # benchmark tự chạy cụm Postgres riêng; dịch vụ mặc định không cần
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
curl -fsSL https://ollama.com/install.sh | sh
```

Nếu `apt` báo không có gói `postgresql-14-pgvector`, thêm kho PGDG rồi cài lại:

```bash
sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
```

Container không có systemd, nên Ollama được chạy tay ở bước 5.

**macOS:**

```bash
brew install postgresql@16 pgvector uv ollama
```

**Kiểm tra:**

```bash
pg_config --bindir; ls "$(pg_config --sharedir)/extension/vector.control"; uv --version; ollama --version
```

- Ubuntu: nếu `pg_config` trỏ sai phiên bản, đường dẫn bin là `/usr/lib/postgresql/16/bin`.
- `vector.control` phải tồn tại. Phiên bản pgvector cần ≥ 0.8; bản dump được tạo bằng 0.8.7.
- Ollama phải ≥ 0.9, để có tham số `think` cho Qwen3.

## 4. Lấy code và cài Python

Mọi cache nặng đều đặt trong `~/data`, để thư mục home 8 GB không bị đầy. Thêm 5 dòng sau vào **cuối `~/.bashrc`**, rồi chạy `source ~/.bashrc`:

```bash
export WORK=$HOME/data/ctg_bench
export UV_CACHE_DIR=$HOME/data/.cache/uv
export HF_HOME=$HOME/data/.cache/huggingface
export OLLAMA_MODELS=$HOME/data/ollama
export PIP_CACHE_DIR=$HOME/data/.cache/pip TMPDIR=$HOME/data/tmp
```

Tạo các thư mục cache, clone code từ bundle và cài Python:

```bash
mkdir -p "$UV_CACHE_DIR" "$HF_HOME" "$OLLAMA_MODELS" "$PIP_CACHE_DIR" "$TMPDIR"
cd "$WORK" && git clone -b ctg-dataroom dataroom.bundle dataroom && cd dataroom
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r pyproject.toml
```

**Kiểm tra:**

```bash
ls scripts/grid_eval.py scripts/smoke_answer.py dr/core/doctype.py && .venv/bin/python -c "import torch, sentence_transformers, psycopg; print('cuda', torch.cuda.is_available())"
```

`cuda False` trên máy có GPU NVIDIA nghĩa là torch bản CPU đã được cài. Khi đó cài lại torch đúng bản CUDA theo pytorch.org; việc này không bắt buộc.

## 5. Tải model

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download as s; [s(m) for m in ['BAAI/bge-reranker-v2-m3','MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7']]"
(nohup ollama serve > "$WORK/ollama.log" 2>&1 &) ; sleep 5     # dùng OLLAMA_MODELS ở bước 4; bỏ qua nếu Ollama đã chạy
for m in bge-m3 qwen2.5:3b qwen2.5:7b qwen3:4b gemma3:4b phi4-mini; do ollama pull $m || echo "PULL FAIL $m"; done
```

**Kiểm tra:** `ollama list` phải có đủ 6 model, và không dòng nào in `PULL FAIL`.

## 6. Nạp dữ liệu

Giải nén tenant (tạo `data/ctg/tenant/*.json`) và đặt biến môi trường. **Các bước sau dùng chung các biến này**, nên chạy trong cùng một shell, hoặc ghi chúng vào `$WORK/dataroom/bench.env` rồi `source`:

```bash
cd "$WORK/dataroom" && tar xzf "$WORK/ctg_tenant.tgz"
cat > bench.env <<'EOF'
export DR_DATA=data/ctg
export DR_PGDATA=$HOME/data/ctg_bench/pgdata
export DR_PG_PORT=55433
export DR_PG_BIN=$(pg_config --bindir)
export HF_HUB_OFFLINE=1
EOF
source bench.env
```

Ubuntu: nếu `pg_config --bindir` không ra `/usr/lib/postgresql/14/bin` (hoặc `/16/` trên 24.04), sửa dòng `DR_PG_BIN` cho đúng.

Tạo cụm Postgres riêng (database `dataroom`, schema, role, RLS), rồi nạp dữ liệu. Trên Mac bước nạp mất khoảng 5 phút.

```bash
.venv/bin/python -c "from dr.db import pg; pg.ensure_cluster(); print('postgres ok')"
$DR_PG_BIN/pg_restore -h $DR_PGDATA/sock -p $DR_PG_PORT -U dr_admin -d dataroom --data-only --disable-triggers "$WORK/ctg_dataroom.dump"
```

**Kiểm tra:** số dòng phải đúng như dưới.

```bash
.venv/bin/python -c "from dr.db import pg; c=pg.admin(); print([c.execute(f'select count(*) from {t}').fetchone()[0] for t in ('chunks','facts','items')])"
```

Kết quả phải là `[51148, 1689, 6792]`.

- `pg_restore` báo lỗi "already exists" hoặc lỗi khoá trùng nghĩa là đã nạp hai lần. Xoá cụm và làm lại từ đầu:

  ```bash
  $DR_PG_BIN/pg_ctl -D "$DR_PGDATA" -m fast stop; rm -rf /home/coder/data/ctg_bench/pgdata
  ```

  Sau đó chạy lại `ensure_cluster` và `pg_restore`.
- Không cần thư mục `data/ctg/tenant/files/` (13 GB tài liệu gốc). Benchmark chỉ đọc từ database.

## 7. Hỏi thử một câu

Bước này kiểm tra database, tenant, Ollama, reranker và NLI cùng lúc. Lần đầu mất khoảng 1 phút.

```bash
source bench.env && .venv/bin/python scripts/smoke_answer.py qwen2.5:3b
```

**Kiểm tra:** dòng cuối phải bắt đầu bằng `SMOKE OK`, ví dụ `SMOKE OK (qwen2.5:3b) | Diện tích thông thủy của Căn S-01 là 26.4 m².`. Nếu ra `FAIL`, xem mục 9.

## 8. Chạy benchmark

Quy tắc:

- **Chỉ chạy một benchmark tại một thời điểm.** Hai lượt resync quyền cùng lúc làm luồng quyền bị coi là cũ (cổng 4) và mọi câu bị từ chối.
- Không chạy gì khác dùng Ollama song song.

```bash
cd "$WORK/dataroom" && source bench.env
tmux new -d -s grid "source bench.env && .venv/bin/python -u scripts/grid_eval.py 2>&1 | tee data/ctg/grid.log"
```

Không có tmux thì dùng `nohup … &`. Theo dõi tiến độ bằng `tail -f data/ctg/grid.log`. Mỗi cấu hình in một dòng: `tên  đúng/36  sai N  giây/câu  (phút)`.

- **Chạy tiếp sau khi bị ngắt:** chạy lại đúng lệnh trên. Các cấu hình đã có trong `data/ctg/grid/results.jsonl` không chạy lại.
- **Một cấu hình bị lỗi:** script dừng và in đường dẫn file log của cấu hình đó. Lần lỗi không được ghi vào kết quả. Sửa nguyên nhân (mục 9) rồi chạy lại.
- **Chỉ chạy một số model:** thêm `--models qwen2.5:3b,qwen3:4b`.
- **Chạy tay một cấu hình**, ví dụ bật `binding` và `doctype` trên `qwen3:4b`:

  ```bash
  DR_LLM=qwen3:4b DR_BINDING=1 DR_DOCTYPE=1 .venv/bin/python -u scripts/ctg_ocr_eval.py
  DR_BINDING=1 DR_DOCTYPE=1 .venv/bin/python -u scripts/ctg_table_eval.py qwen3:4b
  ```

### Khi chạy xong

Dòng cuối của log là bảng xếp hạng, đồng thời được ghi vào `data/ctg/grid/REPORT.md`.

Gửi lại cho người vận hành các file sau. Chúng chỉ chứa câu hỏi, câu trả lời ngắn và điểm, nhưng vẫn là nội dung nội bộ:

- `data/ctg/grid/REPORT.md`
- `data/ctg/grid/results.jsonl`
- `data/ctg/grid.log`

Kèm theo một tóm tắt ngắn:

- cấu hình tốt nhất và điểm của nó;
- số câu trả lời sai;
- thời gian mỗi câu;
- 2 lần chạy của cấu hình tốt nhất có khớp nhau không.

Lưu ý khi đọc kết quả:

- 36 câu là ít: chênh 1 câu có thể chỉ do GPU cho kết quả lệch giữa các lần chạy.
- Grid search trên chính 36 câu này dễ chọn ra cấu hình khớp riêng bộ đề. Trước khi đổi cấu hình mặc định, phải xác nhận lại trên một bộ 100–200 câu viết từ những tài liệu chưa từng dùng để chọn cấu hình.
- Ưu tiên cấu hình có ít câu trả lời sai.

## 9. Lỗi thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `connection to server on socket ".../sock/.s.PGSQL.55433" failed` | Cụm Postgres chưa chạy (thường sau khi khởi động lại máy) | `source bench.env && .venv/bin/python -c "from dr.db import pg; pg.ensure_cluster()"` |
| `initdb`/`pg_ctl: not found` | `DR_PG_BIN` sai | Đặt `DR_PG_BIN` thành thư mục chứa `pg_ctl` (`pg_config --bindir`, Ubuntu: `/usr/lib/postgresql/16/bin`) |
| Postgres không mở được socket, hoặc lỗi "path too long" | Đường dẫn socket Unix vượt khoảng 100 ký tự | Giữ `DR_PGDATA` ngắn, ví dụ `$HOME/data/ctg_bench/pgdata` |
| `could not open extension control file ".../vector.control"` | Thiếu pgvector cho đúng phiên bản Postgres | Cài `postgresql-<phiên bản>-pgvector` khớp với `pg_config --version` |
| Postgres trên macOS báo "became multithreaded during startup" | Thiếu locale | `export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8` (code đã tự đặt khi khởi động, cần nếu tự chạy `pg_ctl`) |
| Hầu hết câu ra "SAI" và câu trả lời là lời từ chối hoặc thông báo cổng phân quyền | Hai benchmark hoặc hai lượt resync chạy cùng lúc | Dừng mọi tiến trình `ctg_*_eval`/`grid_eval` (`pkill -f grid_eval; pkill -f ctg_`), rồi chỉ chạy lại một lượt |
| `httpx.ConnectError` tới `127.0.0.1:11434` | Ollama chưa chạy | `ollama serve &` hoặc `sudo systemctl start ollama` |
| `model "…" not found` | Model chưa được pull | `ollama pull <model>` (script chờ tối đa 30 phút cho model đang tải) |
| Lỗi `think` hoặc Qwen3 trả JSON rỗng | Ollama quá cũ | Cập nhật Ollama ≥ 0.9 |
| Hugging Face báo offline hoặc không tìm thấy model | Chưa tải reranker/NLI trước khi bật `HF_HUB_OFFLINE=1` | Chạy lệnh tải ở bước 5 mà không đặt `HF_HUB_OFFLINE` |
| `No space left on device` trong `/home/coder` | Cache hoặc model bị ghi vào thư mục home (8 GB) | Kiểm tra `UV_CACHE_DIR`, `HF_HOME`, `OLLAMA_MODELS`, `TMPDIR` đều trỏ vào `~/data` (bước 4), rồi dọn `~/.cache` và `~/.ollama/models` |
| `nvidia-smi`: "Failed to initialize NVML" | Container không thấy driver đầy đủ. Không chặn benchmark | Chạy `.venv/bin/python -c "import torch; print(torch.cuda.is_available())"`. Nếu False, reranker và NLI chạy CPU; Ollama xem `$WORK/ollama.log` (dòng "inference compute") |
| Hết RAM/VRAM khi chạy `fallback7b` | 3B và 7B cùng nằm trong bộ nhớ | `export OLLAMA_MAX_LOADED_MODELS=1`, khởi động lại Ollama |
| Điểm của `qwen2.5:3b` cơ bản thấp hơn nhiều so với 32–34/36 | Dữ liệu nạp thiếu, hoặc chạy song song | Kiểm tra lại số dòng ở bước 6 và đảm bảo chỉ có một benchmark đang chạy |
