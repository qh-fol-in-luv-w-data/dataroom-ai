# Thiết kế: Demo AI core cho Data Room (chạy local)

Ngày 06/10/2026. Bản này hiện thực hóa phần quyền và RAG của kế hoạch tổng (`AI_DataRoom_Master_Plan.md` v0.5) ở quy mô một máy laptop, để demo cho BOD và đội kỹ thuật.

## 1. Mục tiêu và tiêu chí thành công

- Một người bấm chọn danh tính (nhà đầu tư nhóm A, B, C, cố vấn, nhân viên…) rồi hỏi bằng tiếng Việt. AI trả lời có trích dẫn, và **chỉ dùng tài liệu mà danh tính đó được phép đọc và được phép dùng AI**.
- Màn hình "RAG của tôi truy xuất được đến đâu" liệt kê đúng phạm vi của từng người.
- Bảng kịch bản tái hiện được các tình huống thu hồi quyền trong kế hoạch, và cho thấy AI chặn đúng lúc.
- Bộ test tự động chứng minh không rò rỉ: mọi người × mọi chuỗi đánh dấu.
- Chạy trên MacBook M3 Pro, 18 GB RAM, đĩa trống khoảng 6,5 GB. Không tải thêm model, không dùng Docker.

## 2. Ràng buộc tài nguyên

| Hạng mục | Lựa chọn | Lý do |
|---|---|---|
| LLM | Ollama `qwen2.5:7b` (đã có trên máy) | Khoảng 6 GB RAM, hỗ trợ tiếng Việt, không tốn thêm đĩa. Đặt tên model trong cấu hình để đổi được |
| Embedding | Ollama `bge-m3` (đã có) | Đa ngôn ngữ |
| Reranker, NLI | Bỏ | Cần torch, tốn vài GB đĩa. Kiểm căn cứ bằng khớp câu trích nguyên văn |
| OCR | Tesseract `vie` + `eng` (đã có) | Nhẹ |
| Parser | pypdfium2, pypdf, python-docx, openpyxl, python-pptx, thư viện chuẩn `email`, BeautifulSoup | Không dùng Docling/PaddleOCR (vài GB) |
| CSDL | PostgreSQL 15 (Homebrew), thư mục dữ liệu nằm trong project, socket unix | Có RLS. Không có pgvector: vector lưu `real[]` |
| Dung lượng | venv ≤ 0,6 GB; dữ liệu ≤ 1,5 GB; Postgres ≤ 0,5 GB | |

## 3. Kiến trúc

```
data/tenant/        nguồn sự thật giả lập: tenant.json (người, nhóm, app role, site, quyền) + files/
fake_tenant/        "SharePoint + Entra" giả: API delta, GET driveItem theo token người dùng,
                    độ trễ lan truyền nhóm giả lập, cờ mã độc, nhãn mã hóa, phiên bản (cTag)
connector/          đồng bộ delta → bản chép quyền (Postgres), tập thu hồi, mốc độ tươi
ingest/             tải file từ fake_tenant → kiểm an toàn → parse/OCR → cắt đoạn → embedding → Postgres
core/               truy xuất (BM25 + vector trên dòng RLS cho phép) → kiểm tra trực tiếp → LLM → kiểm chứng
gateway/            FastAPI: đăng nhập giả lập, chat, phạm vi, ma trận quyền, kịch bản, nhật ký
web/                một trang HTML/JS tĩnh
tests/              pytest: ma trận rò rỉ, thu hồi, parser
scripts/            sinh dữ liệu tổng hợp, tải tài liệu công khai, khởi động Postgres
```

Mọi thành phần chạy trong một tiến trình FastAPI (fake_tenant gắn ở `/_tenant`, có khóa và nguồn dữ liệu riêng). Như vậy demo chỉ cần một lệnh chạy, nhưng ranh giới giữa các thành phần vẫn giữ như khi tách service. Connector chạy trong luồng nền và poll delta mỗi 5 giây; chu kỳ này rút ngắn so với 60 giây ở production để demo cho nhanh.

## 4. Mô hình quyền (theo mục 3 của kế hoạch tổng)

- **Nguồn quyền:** `tenant.json`, gồm:
  - người dùng: oid, tên, loại guest hoặc member, trạng thái bật/tắt;
  - nhóm: DR-INV-A, DR-INV-B, DR-INV-C, STAFF, REVIEWERS;
  - app role: `Investor.AI`, `Investor.AI.Summarize`, `Staff.AI`, `Reviewer`;
  - site: Chung, Nhóm A, Nhóm B, Nhóm C, Nội bộ, mỗi site có nhóm RAC;
  - quyền theo site, thư mục hoặc file (kế thừa hoặc riêng), cấp cho nhóm, người, hoặc link người cụ thể;
  - link "Anyone" chỉ để thử: không bao giờ được mở rộng thành quyền.
- **fake_tenant** tự đánh giá quyền như SharePoint. Thay đổi nhóm chỉ có hiệu lực ở phía "SharePoint" sau `GROUP_LAG_SECONDS` (mặc định 60). Phía "Entra delta" thấy thay đổi ngay.
- **Bản chép quyền** trong Postgres gồm:
  - `item_reader(item_id, oid)`, dựng từ quyền trên item và tư cách thành viên lấy từ Entra delta;
  - `revocation(oid, group, until)`;
  - `deny_list(oid)`;
  - `feed_status(feed, last_ok)`.
- **Bốn cổng**, tất cả phải qua:
  1. RLS: role `app_query`, `set_config('app.principal_oid', …, true)`, `FORCE ROW LEVEL SECURITY`. Đoạn văn chỉ hiện ra khi có `item_reader`, cờ hiệu lực cho phép, `is_current`, và không đi qua nhóm nằm trong tập thu hồi.
  2. Kiểm tra trực tiếp: `fake_tenant` GET item bằng token người dùng, kiểm cả cTag và `AI_Use`. Chạy trước khi đoạn văn vào LLM và chạy lại trên các file được trích dẫn.
  3. Tập thu hồi theo cặp (oid, nhóm), giữ cho tới khi SharePoint đã áp thay đổi.
  4. Cổng theo người: có app role, không nằm trong danh sách chặn; delta Entra phải tươi (cũ quá 30 giây thì từ chối; ngưỡng rút ngắn để demo).
- **Đóng an toàn khi có lỗi:**
  - 403/404 → loại file trong im lặng, lấy file kế tiếp bù vào;
  - lỗi tạm thời → trả câu "vui lòng thử lại";
  - nguồn delta ngừng → từ chối câu hỏi.

## 5. Nạp tài liệu

- **Định dạng hỗ trợ:**
  - PDF có lớp chữ; PDF scan (raster rồi OCR); docx; xlsx (giá trị, sheet ẩn được gắn nhãn không đáng tin, đơn vị lấy từ dòng tiêu đề); pptx (slide, ghi chú);
  - eml (thân thư và tệp đính kèm, đính kèm kế thừa quyền); html; txt/md; csv; png/jpg (OCR).
- **Bỏ qua kèm lý do:** cờ mã độc (chuỗi EICAR); file có mật khẩu hoặc nhãn mã hóa (phát hiện bằng byte); `AI_Use = Excluded`; định dạng không hỗ trợ (chỉ lưu metadata).
- **Chất lượng lớp chữ PDF** được chấm trước khi định tuyến; dưới ngưỡng thì OCR.
- **Cắt đoạn** theo đoạn văn, bảng, slide hoặc sheet, khoảng 800 ký tự. Lưu:
  - vị trí trích dẫn theo loại file (trang, slide, `sheet!vùng`, tiêu đề);
  - văn bản bỏ dấu để tìm khi người hỏi gõ không dấu;
  - embedding bge-m3;
  - phân vùng (site/nhóm).
- **Đổi cTag:** đặt `is_current = false` ngay, rồi nạp lại.
- **Chấm điểm injection** theo luật. Đoạn bị gắn cờ không bị chặn, chỉ được ghi nhật ký.

## 6. Hỏi đáp

- **Truy xuất:**
  - lấy BM25 (rank_bm25, chỉ trên các dòng RLS cho phép, tính riêng cho từng phân vùng) và cosine;
  - gộp bằng RRF, gom theo file, lấy tối đa 8 file;
  - kiểm tra trực tiếp từng file.
- **Sinh câu trả lời:** `qwen2.5:7b` trả JSON `{claims:[{text, citations:[{chunk_id, quote}]}]}`. Đoạn văn được bọc trong `<untrusted_document>`.
- **Kiểm chứng:**
  - `chunk_id` phải thuộc tập đã kiểm tra;
  - câu trích phải có trong đoạn sau khi chuẩn hóa;
  - con số trong ý phải xuất hiện trong câu trích.

  Ý không đạt bị bỏ. Không còn ý nào thì trả một câu từ chối trung tính.
- **Trả lời:** một khối duy nhất, sau khi kiểm xong.
- **Nhật ký:** bảng hash nối chuỗi, có trang kiểm chuỗi.

## 7. Giao diện

- **Thanh trên:** chọn danh tính.
- **Tab Chat:** câu trả lời, các thẻ trích dẫn (mở file gốc từ fake_tenant, sau khi kiểm quyền lại), thời gian và các cổng đã qua.
- **Tab "Phạm vi của tôi":** cây site/thư mục/file mà người đó **mở được trên "SharePoint"**. Mỗi file có trạng thái: AI dùng được / Excluded / mã hóa / mã độc / đang nạp. Có tổng số.
- **Tab "Ma trận quyền"** (chỉ quản trị): người × site × số file AI dùng được; bấm vào ô để xem chi tiết.
- **Tab "Kịch bản":** các nút:
  1. gỡ người X khỏi nhóm A, kèm đồng hồ cho thấy "SharePoint" còn cho mở nhưng AI đã chặn;
  2. chuyển nhóm;
  3. đổi `AI_Use` của một file;
  4. thay file bằng bản đã biên tập;
  5. offboard;
  6. làm hỏng bản chép quyền (thêm quyền giả), để thấy kiểm tra trực tiếp vẫn chặn;
  7. tắt delta Entra, để thấy hệ thống từ chối;
  8. khôi phục.
- **Tab "Nhật ký":** các dòng gần nhất và nút kiểm chuỗi hash.

## 8. Dữ liệu

- **Công ty giả lập:** CTCP Năng lượng Sao Mai (mã SMP), IPO năm 2026. Bộ tài liệu khoảng 500 file. Nội dung do script sinh theo mẫu có số liệu nhất quán:
  - báo cáo tài chính 2023–2025 (xlsx, PDF);
  - hợp đồng (docx);
  - biên bản họp HĐQT (PDF scan có dấu đỏ);
  - slide nhà đầu tư (pptx);
  - email trao đổi (eml, có tệp đính kèm);
  - hồ sơ pháp lý, giấy phép (ảnh scan);
  - thẩm định (html/md);
  - danh mục tài sản (csv).
- **Phân bố theo site:**
  - Chung: khoảng 40%;
  - Nhóm A, B, C: khoảng 15% mỗi nhóm;
  - Nội bộ: khoảng 15%.

  Mỗi site cài chuỗi đánh dấu riêng (ví dụ `MARKER-SITE-B-…`) và một vài "sự thật" chỉ site đó có (ví dụ giá chào riêng cho nhà đầu tư chiến lược), để thử rò rỉ bằng câu hỏi.
- **Ca đặc biệt:** file có mật khẩu; file EICAR; file `Excluded`; hợp đồng v1/v2 đã biên tập; file cài prompt injection; PDF có chữ trắng ẩn; một thư mục có quyền riêng cấp cho một người; link "Anyone"; người thuộc hai nhóm.
- **Tài liệu công khai thật:** 30–50 tài liệu (bản cáo bạch, BCTC, slide IR) từ trang công bố thông tin, đặt vào site Chung. Danh sách nguồn và dung lượng được trình bày để người dùng duyệt **trước khi tải**; không tải tự động.

## 9. Kiểm thử

- **Ma trận rò rỉ:** với mỗi người × mỗi chuỗi đánh dấu, gọi API truy xuất (không qua LLM, để nhanh và tất định). Khẳng định: không đoạn nào thuộc site không được cấp lọt ra; trong tập ứng viên không có file `Excluded`, mã hóa hay mã độc.
- **Thu hồi:** gỡ nhóm, chuyển nhóm, offboard, đổi `AI_Use`, thay phiên bản, làm hỏng bản chép, tắt nguồn. Mỗi kịch bản khẳng định kết quả đúng như mục 4.
- **RLS:** dùng role `app_query` mà không đặt `principal_oid` thì nhận về 0 dòng.
- **Parser:** mỗi định dạng có một file mẫu.
- **End-to-end có LLM:** đánh dấu riêng, chạy tay vì chậm.

## 10. Ngoài phạm vi

- Graph/Entra thật.
- Reranker, NLI, Bản 2 (đếm và liên kết chéo).
- Bộ phân loại injection học máy.
- Neo WORM vào SharePoint.
- Triển khai nhiều máy.

Connector được viết theo một interface (`TenantSource`), để sau này thay bằng Graph thật.
