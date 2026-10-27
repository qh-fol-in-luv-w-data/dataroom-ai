# Data Room CT Group – hướng dẫn sử dụng và tài liệu kỹ thuật bổ sung

Tài liệu này bổ sung cho `README.md` và `docs/GIAI_THICH_MA_NGUON.md` (viết cho bản demo Sao Mai). Nó mô tả
phần dữ liệu thật của CT Group: lấy dữ liệu từ SharePoint, chia thư mục, nạp vào AI core, và các tính năng
thêm vào chat (nhớ ngữ cảnh, đọc bảng, đọc biểu đồ).

---

## 1. Hướng dẫn sử dụng

### 1.1 Luồng làm việc

```
SharePoint CT Group ──(1) tải──▶ data/sp_download ──(2) chia thư mục──▶ data/AI Data Room
                                                                           │
                         (3) dựng tenant + quyền A–F ◀────────────────────┤
                                     │                                     └──(4) đẩy lên SharePoint 27bbzr
                                     ▼
                         data/ctg/tenant ──(5) nạp (OCR, cắt đoạn, embedding)──▶ Postgres ~/.dr_ctg/pgdata
                                                                                       │
                                                                       (6) chạy app ◀──┘  http://localhost:8001
```

Mọi lệnh chạy trong thư mục dự án, bằng Python của dự án:

```bash
V=/Users/_qh.fol_/Projects/dataroom-ai-demo/.venv/bin/python
export DR_DATA=data/ctg DR_PGDATA=$HOME/.dr_ctg/pgdata DR_PG_PORT=55433 HF_HUB_OFFLINE=1
```

### 1.2 Các bước

| Bước | Lệnh | Ghi chú |
|---|---|---|
| 1. Tải thư mục SharePoint | `python3 scripts/sp_download.py "<URL thư mục>" --max-gb 18` | Mở Chromium, **bạn tự đăng nhập**. Tải 8 file song song, file nhỏ trước, tự dừng khi ổ đĩa còn dưới 4 GB. File "chỉ được xem" (không có quyền tải) được bỏ qua và ghi vào `_manifest.json` (`can_download: false`) |
| 2. Chia thư mục theo cây 01–07 | `$V scripts/organize_dataroom.py "data/sp_download/<thư mục>" "data/AI Data Room"` rồi thêm `--apply` | Không có `--apply`: chỉ lập `_plan.csv` để xem trước. Có `--apply`: di chuyển (không chép), ghi `_moves.csv`; `--undo` để trả về như cũ |
| 3. Dựng tenant CT Group | `$V scripts/build_ctg_tenant.py "data/AI Data Room" data/ctg` | Tạo site "AI Data Room CT Group", 6 nhóm A–F theo ma trận quyền, tài khoản demo (mật khẩu trong `data/ctg/tenant/DEMO_ACCOUNTS.md`). File được hard link: không tốn thêm ổ đĩa |
| 4. Đẩy lên SharePoint | `$V scripts/sp_upload.py --site https://27bbzr.sharepoint.com/sites/DSA --library "DataRoom AI Demo" --m365-config <…>/data/m365.json --token-cache <…>/data/.sp_token.json --src "data/AI Data Room"` | 8 luồng song song (~7 MB/s). `--show` xem thư viện, `--wipe --yes` xoá hết (vào thùng rác). Chạy lại thì chỉ đẩy phần còn thiếu. Đường dẫn quá 400 ký tự được rút gọn tên thư mục (dấu `~`) |
| 5a. Bật OCR server | `make ocr-server` | PaddleOCR-VL-1.6 trên GPU (MLX), cổng 8111. **Phải chạy suốt lúc nạp** |
| 5b. Nạp dữ liệu | `DR_OCR_ENGINE=vl DR_OCR_CROSSCHECK=0 $V scripts/ingest.py --workers 2 --shard 0/3` (và `1/3`, `2/3` ở 2 terminal khác) | Chạy lại thì tiếp từ chỗ dừng. Thứ tự: Word/Excel/PowerPoint → PDF → ảnh; pháp lý/tài chính/kỹ thuật trước marketing |
| 6. Chạy app | khởi động cấu hình `ctg-dataroom` trong `.claude/launch.json`, mở http://localhost:8001 | Model chat mặc định `qwen2.5:3b` (`DR_LLM`); đổi sang `qwen2.5:7b` để câu trả lời tốt hơn |

### 1.3 Tài khoản và quyền

| Tài khoản | Nhóm | Thấy các thư mục |
|---|---|---|
| ctg-a@ctgroup-demo.example | A – Nhà đầu tư/CĐT | 01, 02 (cả 2.1–2.3), 03 (cả 3.1–3.3), 04, 05, 07 |
| ctg-b@ctgroup-demo.example | B – Ban dự án | 01–06 |
| ctg-c@ctgroup-demo.example | C – BOD | 01, 03 (cả 3.1–3.3), 04, 05 |
| ctg-d@ctgroup-demo.example | D – Thẩm định nội bộ | 01, 04, 05, 06 |
| ctg-e@ctgroup-demo.example | E – Tư vấn/Đối tác | 01, 02 (cả 2.1–2.3), 04 |
| ctg-f@ctgroup-demo.example | F – Khách | 01 |

Mật khẩu chung nằm trong `data/ctg/tenant/DEMO_ACCOUNTS.md` (chỉ trên máy, không đưa lên git).

### 1.4 Hỏi đáp trong chat

- **Câu hỏi nối tiếp** dùng được từ chỉ trỏ: "hợp đồng đó", "còn dự án kia thì sao?", "nói rõ hơn ý 2".
  Giao diện hiện chip "Hiểu là: …" với câu hỏi đầy đủ mà hệ thống đã tìm.
- **"Tổng hợp lại"** (hoặc "tóm tắt cuộc trò chuyện", "recap") gom các ý đã trả lời, có nguồn; quyền được
  kiểm tra lại trên từng file.
- **Bảng**: hỏi một dòng ("chi phí CGI giai đoạn 1 của GJDC"), so sánh nhiều dòng ("so sánh BNF và MIX
  MEDIA"), lớn nhất/nhỏ nhất ("agency nào rẻ nhất giai đoạn 2") đều được; hai loại sau do code tính trực tiếp.
- **Biểu đồ**: hỏi số trên biểu đồ như hỏi chữ ("media plan tháng 7/2021 phân bổ cho Léman bao nhiêu %").
- Chủ đề nhạy cảm IPO (định giá doanh nghiệp, giá chào bán cổ phiếu, phân bổ cổ phần, cam kết lợi nhuận,
  dự báo tài chính, tranh chấp) được chuyển cho Ban IPO thay vì trả lời; danh sách ở
  `data/ctg/tenant/sensitive_topics.json`.

---

## 2. Tài liệu kỹ thuật bổ sung

### 2.1 File mới / đổi

| File | Vai trò |
|---|---|
| `scripts/sp_download.py` | Playwright + REST SharePoint (`RenderListDataAsStream` POST: không vướng giới hạn độ dài URL, phân trang >5000). Tải bằng cookie phiên trình duyệt qua `requests`, 8 luồng; chống throttle (302 → `Throttle.htm`, 429/503 + `Retry-After`); không bao giờ lưu trang HTML lỗi thay cho file |
| `scripts/organize_dataroom.py` | Phân loại vào cây 01–07 theo tên file rồi tới thư mục (sâu → nông); giữ công ty + đường dẫn gốc dưới mục |
| `scripts/build_ctg_tenant.py` | Tenant giả lập SharePoint/Entra cho CT Group + ma trận quyền A–F + chủ đề nhạy cảm thu hẹp |
| `scripts/sp_upload.py` | Thêm `--src/--show/--wipe/--workers/--m365-config`, upload song song, rút gọn đường dẫn >400 ký tự |
| `scripts/ctg_table_eval.py` | Benchmark 8 câu bảng/biểu đồ có đáp án, chạy được nhiều model |
| `dr/core/conversation.py` | Lịch sử hội thoại phía server theo (người dùng, cuộc trò chuyện); nhận diện câu nối tiếp / tổng hợp |
| `dr/core/tables.py` | Lớn nhất/nhỏ nhất và so sánh nhiều dòng tính bằng code trên các dòng bảng |
| `dr/ingest/charts.py` | Biểu đồ dạng ảnh trên trang PDF có chữ: PP-DocLayoutV3 dò vùng biểu đồ, chỉ trang có biểu đồ mới gửi PaddleOCR-VL đọc thành bảng số |
| `dr/ingest/ocr_md.py` | Đọc file scan/ảnh từ Markdown có sẵn (`DR_OCR_MD_DIR`) thay vì OCR lại; khớp cả đường dẫn bị rút gọn `~` |
| `scripts/export_md.py` | Xuất toàn bộ data room đã nạp ra Markdown (`<thư mục>/<tên file>.md`) + `INDEX.md` liệt kê mọi file và trạng thái |

### 2.2 Thay đổi trong luồng trả lời (`dr/core/answer.py`, `verify.py`, `llm.py`)

1. **Ngữ cảnh**: có lịch sử thì câu nối tiếp được LLM viết lại thành câu độc lập (câu viết lại phải qua
   bộ lọc injection); "tổng hợp lại" đọc lại đúng các đoạn đã trích qua RLS + kiểm tra trực tiếp.
2. **Chế độ bảng**: câu hỏi so sánh/lớn nhất/nhỏ nhất/tổng mà đoạn tốt nhất là một dòng Excel → đọc cả sheet
   (`intent.PLANS["table"]`); lớn/nhỏ nhất và so sánh do `tables.py` tính, không qua LLM.
3. **Sửa lỗi ghép câu**: các câu được chọn cách nhau một dòng trống, để câu bị cắt ngắn không bị nối với câu
   kế tiếp (trước đó câu trả lời đúng vẫn bị loại vì "trích dẫn không nguyên văn").
4. **`_repair`** bỏ qua các con số có sẵn trong câu hỏi (ngày, năm), như bước kiểm chứng.
5. **Kiểm chứng thêm hai luật**: tên (EZ, GJDC, SH09…) nêu trong câu trả lời phải có trong câu trích của nó;
   câu hỏi nêu một mã có trong dữ liệu thì câu trả lời phải trích từ đoạn có mã đó.
6. Tên công ty trong prompt lấy từ `DR_COMPANY`.

### 2.3 Thay đổi trong bước nạp (`dr/ingest/`)

- **Excel**: mỗi dòng là bản ghi `Cột: giá trị; …`; tiêu đề nhiều tầng + ô gộp ghép theo cột, bỏ tầng tiêu đề
  chung; ô ngắn (tên, mã, số) đứng trước; dòng dài chia mảnh, mỗi mảnh lặp khoá dòng; số kiểu Việt
  (`116.640.000`, `1.250,50`, `30%`).
- **Biểu đồ gốc** Excel/PowerPoint/Word: đọc số liệu lưu trong file biểu đồ (`chart_text`).
- **PDF**: mọi lời gọi pdfium đi qua khoá `ocr.PDFIUM` (pdfium không an toàn đa luồng – từng crash); trang có
  ảnh hoặc nét vẽ + dòng toàn số được dò biểu đồ.
- **OCR**: chỉ PaddleOCR-VL-1.6 (`DR_OCR_ENGINE=vl`; `ppocr` là PP-OCRv5 latin chạy CPU cho máy không có server);
  **không tự chuyển sang model khác khi lỗi** – file bị đánh dấu lỗi kèm lý do. Kết quả OCR lưu theo nội dung ảnh (ảnh trùng không OCR
  lại). Ảnh dưới 3 vùng chữ bỏ qua bước đọc.
- `ingest.py --shard i/n` để chạy nhiều tiến trình; `DR_BACKGROUND_INGEST=0` tắt luồng nạp nền của app khi
  đang nạp hàng loạt.

### 2.4 Biến môi trường mới

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DR_COMPANY` | Công ty CP Năng lượng Sao Mai | Tên công ty trong prompt |
| `DR_OCR_ENGINE` | `vl` | `vl` (PaddleOCR-VL-1.6) · `ppocr` (PP-OCRv5 latin, CPU) |
| `DR_OCR_CROSSCHECK` | `1` | `0`: bỏ PP-OCR đọc lần hai (nhanh hơn, mất đánh dấu "số chưa chắc") |
| `DR_OCR_MIN_TEXT_BOXES` | `3` | Ảnh ít vùng chữ hơn thì bỏ qua bước đọc |
| `DR_BACKGROUND_INGEST` | `1` | `0`: app không tự nạp nền |
| `DR_OCR_MD_DIR` | (trống) | Thư mục Markdown (`data/ctg/md`): file scan/ảnh có `.md` ở đây được đọc từ `.md`, không OCR lại |

### 2.5 Kết quả đo

| Hạng mục | Kết quả |
|---|---|
| Benchmark 8 câu bảng/biểu đồ, `qwen2.5:7b` | 7/8 đúng, ~25 s/câu; câu còn lại trả "không tìm thấy" (không đưa số sai) |
| Cùng benchmark, `qwen2.5:3b` | 7/8 con số đúng, ~19 s/câu; câu trả lời thô hơn, 1 câu sai tự tin |
| Đọc biểu đồ ảnh (35 giá trị có đáp án) | PaddleOCR-VL 100% · Vintern 74% · deepseek-ocr 46% · qwen3-vl:8b 23% · glm-ocr 20% |
| Tốc độ nạp | GPU bão hoà ~6 trang scan/phút; thêm server OCR chỉ +20% |

### 2.6 Lưu ý vận hành

- Máy 18 GB RAM: tối đa 3 tiến trình nạp + 1 OCR server; khi swap lên ~9 GB mọi thứ chậm hàng chục lần –
  khởi động lại máy.
- OCR server phải chạy với `--max-num-seqs 1` (đã có trong `make ocr-server`): gộp lô làm lỗi `broadcast_shapes`.
- Dữ liệu là tài liệu nội bộ CT Group, trong đó ~5.900 file bị công ty khoá tải và không được tải về. Kế hoạch
  tổng chọn AI core on-prem; không đưa lõi lên cloud công cộng khi chưa có IT/pháp chế duyệt.
