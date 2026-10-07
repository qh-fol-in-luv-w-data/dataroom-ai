# Data Room AI – bản demo chạy local

Demo phần **AI core** của kế hoạch tổng *AI cho Data Room IPO* (bản v0.5), chạy hoàn toàn trên một MacBook:

- "SharePoint Online + Entra ID" được mô phỏng: site, thư mục, file, nhóm, app role, link chia sẻ, RAC, nhãn mã hóa, cờ mã độc, phiên bản. Thay đổi nhóm có **độ trễ giả lập** như SharePoint thật.
- AI core đúng kiến trúc của kế hoạch:
  - bản chép quyền trong PostgreSQL có **RLS**;
  - **4 cổng quyền**;
  - kiểm tra trực tiếp với "SharePoint" bằng danh tính người hỏi;
  - tập thu hồi theo (người, nhóm);
  - đóng an toàn khi nguồn quyền ngừng cập nhật;
  - kiểm chứng trích dẫn nguyên văn;
  - nhật ký có chuỗi hash.
- Model chạy local:

  | Việc | Model |
  |---|---|
  | Sinh câu trả lời | `qwen2.5:7b` (Ollama) |
  | Embedding | `bge-m3` (Ollama) |
  | Rerank | `bge-reranker-v2-m3` |
  | Kiểm căn cứ (NLI) | `mDeBERTa-v3-xnli` |
  | OCR và đọc bố cục | **PaddleOCR-VL-1.6** chạy trên GPU Apple qua MLX; dự phòng PP-OCRv5 |

- Dữ liệu: **500 tài liệu** của công ty giả lập *CTCP Năng lượng Sao Mai*, gồm 11 định dạng: docx, xlsx, pptx, PDF có chữ, PDF scan có dấu đỏ, eml kèm tệp đính kèm, html, csv, md, txt, png/jpg. Có thể thêm khoảng 50 tài liệu IPO công khai thật (`data/public_sources.json`).

## Yêu cầu

- macOS Apple Silicon, ≥ 16 GB RAM, ~10 GB đĩa trống.
- Ollama.app đang chạy, đã có `qwen2.5:7b` và `bge-m3` (`make models` sẽ pull nếu thiếu).
- PostgreSQL 15 (Homebrew: `brew install postgresql@15`). Dữ liệu nằm trong `./pgdata`, chỉ mở socket unix, không mở cổng TCP.
- `uv` (https://docs.astral.sh/uv/).

## Chạy

```bash
make setup        # tạo .venv và cài thư viện (paddle, torch, fastapi…)
make models       # tải PaddleOCR-VL, reranker, NLI; pull model Ollama
make data         # sinh 500 tài liệu + tenant.json + facts.json
make ocr-server   # (terminal riêng) PaddleOCR-VL-1.6 trên GPU qua MLX, cổng 8111
make ingest       # đồng bộ quyền + đọc/OCR/embedding (~20–40 phút lần đầu)
# tuỳ chọn: thêm 40 hồ sơ scan khó vào site Chung rồi nạp
#   make hard-scans && .venv/bin/python scripts/add_hard_scans.py && make ingest
make run          # mở http://localhost:8000
```

Kiểm thử:

```bash
make test         # test nhanh (không cần LLM): RLS, tenant, connector, parser, cổng quyền, API
make leak-test    # ma trận rò rỉ trên dữ liệu thật: mọi người × mọi chuỗi đánh dấu × mọi bí mật
make qa-eval      # hỏi đáp thật bằng LLM: người được phép trả lời đúng, người không được phép không lộ
```

Tài liệu công khai, chỉ chạy sau khi đã duyệt danh sách nguồn:

```bash
make public && make ingest
```

## Người dùng demo

| Danh tính | Nhóm | Ghi chú |
|---|---|---|
| Nguyễn Văn An (inv-a1) | Nhóm A | Có thêm thư mục riêng "Thoa-thuan-rieng/Hong-Ha" (quyền riêng) |
| Trần Thị Bích (inv-a2) | Nhóm A | |
| Sarah Lim (inv-b1), Kenji Watanabe (inv-b2) | Nhóm B | |
| Lê Quang Cường (inv-c1) | Nhóm C | Được gửi nhầm link một file Nhóm B, nhưng RAC chặn |
| Phạm Minh Đức (inv-ab) | Nhóm A + B | Dùng để demo gỡ khỏi một nhóm |
| Hoàng Thu Hà (inv-noai) | Nhóm A | Xem được SharePoint nhưng **không có quyền AI** |
| Đỗ Minh Khoa (adv-1) | Cố vấn | Thấy cả A, B, C, không thấy Nội bộ |
| Vũ Thị Lan (staff-1), Bùi Văn Tâm (rev-1) | Nhân viên | Thấy cả site Nội bộ |
| Quản trị demo | — | Ma trận quyền, kịch bản, nhật ký |

## Kịch bản demo 10 phút

1. **Cùng câu hỏi, khác người hỏi.** Đăng nhập Nguyễn Văn An, hỏi *"Phí thu xếp cho nhóm quỹ trong nước là bao nhiêu?"*: AI trả lời 0,85%, có trích dẫn nguyên văn và nút "Mở trên SharePoint". Đổi sang Sarah Lim (Nhóm B) và hỏi lại: câu từ chối trung tính, không có gợi ý nào về việc tài liệu tồn tại. Mở "Chi tiết các cổng" để thấy từng bước.
2. **RAG truy xuất được đến đâu.** Mở tab *RAG của tôi truy xuất được đến đâu*. Tab này liệt kê mọi file người đó mở được trên SharePoint và trạng thái AI của từng file: dùng được, không cho AI, mã hóa, mã độc, đang chặn.
3. **Ma trận quyền.** Đăng nhập *Quản trị demo* và mở *Ma trận quyền*: mỗi người × mỗi site, số file AI dùng được trên số file SharePoint cho mở.
4. **Gỡ khỏi một nhóm.** Ở tab *Kịch bản*, chạy kịch bản 1 (gỡ Phạm Minh Đức khỏi Nhóm A).
   - Bảng trạng thái hiện "SharePoint còn 60s mới áp dụng".
   - Đăng nhập Phạm Minh Đức, mở tab *Phạm vi*: các file Nhóm A chuyển sang **"AI đang chặn"**, dù SharePoint vẫn cho mở.
   - Hỏi về Nhóm B vẫn được trả lời.
5. **Thay bằng bản đã biên tập.** Chạy kịch bản 4, rồi hỏi Sarah Lim *"Đối tác bảo lãnh và hạn mức bảo lãnh là gì?"*. AI không bao giờ trích bản cũ.
6. **Tiêm lỗi vào bản chép quyền.** Chạy kịch bản 6, rồi hỏi Sarah Lim về nội dung Nhóm A. Kiểm tra trực tiếp chặn file đó, thấy rõ trong "Chi tiết các cổng".
7. **Ngắt nguồn Entra.** Chạy kịch bản 7, đợi 30 giây: mọi câu hỏi bị từ chối (đóng an toàn). Sau đó khôi phục.
8. **Nhật ký.** Ở tab *Nhật ký*, bấm "Kiểm tra chuỗi hash".
9. **Bản scan.** Hỏi *"Biên bản họp HĐQT thông qua nội dung gì?"*: trích dẫn có nhãn "văn bản nhận dạng từ bản scan" (PaddleOCR-VL).
10. **Prompt injection.** Hỏi bất kỳ câu nào chạm tới tài liệu `sp-injection`: câu lệnh cài trong tài liệu bị coi là dữ liệu, được gắn cờ trong "Chi tiết các cổng", và không làm lộ gì.

## Cấu trúc

```
dr/tenant/      SharePoint + Entra giả lập (nguồn sự thật, độ trễ nhóm, kiểm tra trực tiếp, delta)
dr/connector/   đồng bộ delta → bản chép quyền, tập thu hồi, RAC, độ tươi nguồn
dr/db/          PostgreSQL cục bộ, schema và chính sách RLS
dr/ingest/      kiểm tra an toàn file, parser mọi định dạng, OCR PaddleOCR-VL, cắt đoạn, nạp
dr/core/        chỉ mục lai phân vùng, 4 cổng, hỏi đáp, kiểm chứng
dr/models/      embedding, reranker, NLI, LLM
dr/gateway/     FastAPI, đăng nhập giả lập, kịch bản
web/            giao diện (HTML/JS thuần)
scripts/        sinh dữ liệu, nạp, tải tài liệu công khai, ma trận rò rỉ, đánh giá hỏi đáp
docs/           spec và kế hoạch triển khai
```

## Bản scan khó: tiền xử lý và kiểm tra con số

Bộ thử `make hard-scans` gồm 40 tài liệu (52 trang, 2.037 con số chính) với 12 kiểu lỗi: xoay 90/180/270°, nghiêng, ảnh chụp điện thoại trên bàn, fax 100 dpi, độ phân giải thấp, dấu đỏ và chữ ký đè lên số, chữ viết tay, bảng kéo dài nhiều trang, hai cột, nếp gấp và vết cà phê. `make ocr-eval` so OCR thẳng với OCR có tiền xử lý.

Các bước tiền xử lý (`dr/ingest/preprocess.py`) chỉ dùng model đã có trên máy, không tải thêm:
- nắn phẳng ảnh chụp, chỉ khi có mặt bàn bao quanh trang;
- cân sáng;
- phóng to trang có độ phân giải thấp;
- tự nhận hướng trang, dựa trên hình dạng dòng chữ và điểm tin cậy khi đọc xuôi so với đọc ngược;
- chỉnh nghiêng.

| | OCR thẳng | Có tiền xử lý |
|---|---|---|
| Con số chính đọc đúng | 95,9% (1.954/2.037) | **98,4% (2.004/2.037)** |
| Độ chính xác ký tự (chữ có dấu) | 95,2% | 97,1% |
| Số bị dấu, chữ ký, vết bẩn đè | 94,9% | 97,4% |
| Số viết tay | 60,9% | 65,2% |
| Thời gian mỗi trang (M3 Pro) | 19,8 s | 22,1 s |

Theo từng kiểu lỗi, các mức tăng lớn nhất:

| Kiểu lỗi | OCR thẳng | Có tiền xử lý |
|---|---|---|
| Xoay 90° | 79% | 100% |
| Độ phân giải thấp | 51% | 93% |
| Xoay 270° | 88% | 95% |

PaddleOCR-VL không cho kết quả giống hệt nhau giữa các lần chạy. Ở lượt đo trước, kiểu độ phân giải thấp được 72% khi OCR thẳng.

**Kiểm tra con số bằng bộ đọc thứ hai.** PP-OCRv5 latin đọc lại cùng trang đã làm sạch. Một con số bị gắn cờ "chưa xác nhận" khi rơi vào một trong hai trường hợp:
- bộ đọc thứ hai không đọc ra con số đó;
- con số sai định dạng Việt Nam, ví dụ `1.555.36`, vì số thập phân phải dùng dấu phẩy.

Kết quả: bắt được **16/20 số đọc sai (80%)**, báo nhầm 3,7% số đúng. Câu trả lời trích con số bị gắn cờ sẽ hiện nhãn "số từ bản scan chưa xác nhận", kèm **ảnh cắt đúng vùng trên trang gốc** để người đọc tự đối chiếu. Ảnh cắt được phục vụ qua `/crop/…`, có kiểm tra quyền SharePoint giống `/open`.

Còn yếu: chữ viết tay (65%) và các trường hợp cả hai bộ đọc cùng sai một kiểu. Bản production nên cho người duyệt xem lại các trang có số bị gắn cờ trước khi mở cho nhà đầu tư dùng AI.

## Tìm kiếm trong Postgres và thử tải 1 triệu đoạn

Tìm kiếm chạy ngay trong PostgreSQL (`dr/core/pgindex.py`), với quyền `app_query`. **RLS lọc ngay trong câu truy vấn tìm kiếm**, ứng dụng không bao giờ giữ danh sách id được phép.

- **Vector:** pgvector 0.8.7, chỉ mục HNSW, kiểu `halfvec(1024)`.
  - Người chỉ thấy ít dữ liệu (≤ 20 nghìn đoạn) dùng tìm vét cạn trên đúng các file của họ.
  - Người thấy nhiều dữ liệu dùng HNSW với chế độ *iterative scan*, để bước lọc quyền không làm thiếu kết quả.
- **BM25:** viết bằng SQL, thống kê tính riêng theo từng site.
  - Ứng viên được chọn theo các từ hiếm nhất trong câu hỏi.
  - Ứng viên lấy qua một hàm `SECURITY DEFINER`. Lý do: khi bật RLS, Postgres không được dùng chỉ mục GIN cho toán tử `@@`. Các id lấy ra vẫn được RLS lọc trong cùng câu SQL.
- Tắt JIT cho `app_query`, vì JIT tốn khoảng 1 giây cho mỗi câu ngắn.
- Biến `DR_SEARCH=memory` để quay lại chỉ mục trong RAM cũ.
- Kiểm tra chéo với bản RAM cũ trên các câu hỏi demo: top-1 trùng 18–19/19 câu, top-10 trùng trung bình 9,4–9,6/10, không trả về id nào ngoài quyền.

`make scale-test` dựng database riêng `dataroom_scale`, gồm 1.000.000 đoạn tổng hợp (ghép từ đoạn thật) và 22 site, rồi đo trên MacBook M3 Pro. Postgres ở đây là bản x86 chạy qua Rosetta, nên số đo là cận trên.

| Bước nạp | Thời gian |
|---|---|
| Chép 1 triệu đoạn | 5,6 phút |
| Chỉ mục GIN | 3,3 phút |
| Chỉ mục HNSW | 6 phút |
| Thống kê BM25 | 8,2 phút |
| Dung lượng | 10 GB (HNSW 2,6 GB) |

| Người dùng (phạm vi thấy) | Đoạn được thấy | Tìm kiếm p50 / p95 | Recall vector* |
|---|---|---|---|
| Nhân viên (100%) | 1.000.000 | 535 / 1.132 ms | 0,94 |
| Nhà đầu tư lớn (38%) | 379.193 | 205 / 690 ms | 0,94 |
| Nhóm trung bình (11%) | 110.865 | 163 / 573 ms | 0,93 |
| Nhóm nhỏ (2,8%) | 28.633 | 511 / 813 ms | 0,96 |
| Chỉ vài file được chia sẻ | 81 | 69 / 94 ms | 1,00 |

\* Tỷ lệ kết quả HNSW gần bằng kết quả thứ 40 của tìm vét cạn (dung sai 0,005). Recall chặt là 0,75–0,83.

Tìm kiếm vẫn dưới 1 giây ở mọi trường hợp. Bước chậm nhất của một câu trả lời vẫn là LLM (10–16 giây trên laptop). Nhóm nhỏ chậm hơn nhóm trung bình vì HNSW phải bỏ qua nhiều đoạn không có quyền. Bản production nên **dùng chỉ mục riêng theo site**, vì data room chia site theo nhóm nhà đầu tư, và **chạy Postgres native trên máy chủ**.

## Giới hạn so với production

- SharePoint và Entra là bản giả lập. Connector được viết để sau này thay bằng Graph thật (delta, `/permissions`, OBO).
- Đăng nhập là token HMAC giả lập, thay cho MSAL và Entra.
- Chỉ mục HNSW đang là một chỉ mục chung. Ở quy mô lớn, người chỉ thấy vài site nên dùng chỉ mục HNSW riêng theo site (xem mục Thử tải).
- Không có sandbox gVisor cho parser, không có ClamAV/YARA. Kiểm tra an toàn file ở mức tối thiểu.
