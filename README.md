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

## Giới hạn so với production

- SharePoint và Entra là bản giả lập. Connector được viết để sau này thay bằng Graph thật (delta, `/permissions`, OBO).
- Đăng nhập là token HMAC giả lập, thay cho MSAL và Entra.
- Chỉ mục giữ trong bộ nhớ, vector lưu dạng mảng trong Postgres (không có pgvector). Phù hợp quy mô demo vài chục nghìn đoạn.
- Không có sandbox gVisor cho parser, không có ClamAV/YARA. Kiểm tra an toàn file ở mức tối thiểu.
