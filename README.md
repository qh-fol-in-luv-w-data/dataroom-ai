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

## Tính năng theo BRD v1.4

| BRD | Tính năng | Cách hoạt động |
|---|---|---|
| BR-11 | **Song ngữ Việt/Anh** | Câu trả lời theo ngôn ngữ của câu hỏi, kể cả câu từ chối. Câu trích luôn giữ nguyên văn bằng ngôn ngữ tài liệu. Con số được kiểm theo giá trị: "2.786,9" và "2,786.9" là cùng một số. Model bge-m3 cho phép hỏi tiếng Anh vẫn tìm được tài liệu tiếng Việt |
| BR-04 | **Hai chế độ trả lời** | Người có `Investor.AI.Summarize` hoặc `Staff.AI` nhận câu trả lời tổng hợp. Người chỉ có `Investor.AI` dùng *chế độ tra cứu*: chỉ nhận các câu trích nguyên văn đã kiểm chứng |
| BR-08 | **Duyệt câu hỏi nhạy cảm** | Gồm 6 chủ đề: định giá, giá chào bán, phân bổ, cam kết lợi nhuận/cổ tức, dự báo, tranh chấp. Danh sách sửa được trong `data/tenant/sensitive_topics.json`. Câu trả lời cho nhà đầu tư thành bản nháp. Reviewer **chỉ xem và duyệt được khi chính mình có quyền đọc mọi file được trích dẫn**. Reviewer sửa lời từng ý, bỏ ý, duyệt hoặc từ chối kèm ghi chú, và mọi bước đều ghi nhật ký. Khi người hỏi mở câu trả lời đã duyệt, hệ thống hỏi lại SharePoint *bằng danh tính người hỏi* và so đúng phiên bản file. Ý nào người hỏi không còn quyền, hoặc file đã đổi phiên bản, thì bị rút lại. Nhân viên (`Staff.AI`) nhận trả lời trực tiếp |
| BR-02 | **Tìm hồ sơ** | Trang tìm kiếm theo từ khóa, nội dung hoặc ý nghĩa, không cần nhớ tên file. Qua đủ cổng 4, RLS và kiểm tra trực tiếp. Chỉ trả về file AI được dùng, kèm đoạn trích có tô đậm từ khóa, link file và link public thư mục |
| Chức năng 10 | **Phản hồi đúng/sai** | Nút 👍/👎 trên câu trả lời, có ghi chú khi sai. Phản hồi lưu vào chuỗi nhật ký; người dùng chỉ phản hồi được câu trả lời của chính mình |

## Lớp bảo mật đầu vào (L2), che dữ liệu cá nhân, hạn mức

Lớp L2 nằm trong `dr/security/`, chạy local và không tải thêm model.

**Lớp lọc câu hỏi** (`guard.py`) gồm ba bước:
1. **Chuẩn hóa:** NFKC, bỏ ký tự vô hình, đổi ký tự giả dạng Cyrillic/Greek sang chữ Latin.
2. **Luật bắt câu tấn công** tiếng Việt (có dấu và không dấu) và tiếng Anh. Luật chạy cả trên dạng đã giải base64/hex, leetspeak và chữ cách quãng.
3. **Bộ phân loại hồi quy logistic** trên embedding bge-m3. Đây là chính vector dùng để tìm kiếm, nên không tốn thêm thời gian. Câu dài được chấm thêm từng câu, với ngưỡng riêng 0,9.

Bộ dữ liệu tấn công nằm ở `make attack-set`, `scripts/train_guard.py`, `scripts/attack_eval.py`, gồm hai tập dùng mẫu câu khác nhau:
- tập huấn luyện: 600 câu;
- tập thử: 450 câu, có thêm tiếng Trung và tiếng Pháp.

| Tập thử giữ riêng | Kết quả |
|---|---|
| Phát hiện tấn công (300 câu) | **85,3%** |
| Chặn nhầm câu hợp lệ (150 câu) | **0,7%**; câu bẫy 0/82 |
| Theo loại | Ghi đè chỉ dẫn 97%; đòi system prompt 89%; nhập vai 100%; mã hóa 100%; thẻ giả 100%; vượt quyền 82%; trích xuất hàng loạt 71%; ép bịa số / ép khẳng định 43% |
| Độ trễ | Dưới 1 ms; câu dài thêm khoảng 0,1 s |

Số đo này lạc quan: điểm vận hành được chọn sau khi đã xem tập thử. Kiểm định chéo trên tập huấn luyện đạt 97%, cho thấy độ rơi khi gặp mẫu câu mới.

**End-to-end khi tắt hẳn lớp L2** (`attack_eval.py --e2e 30`): 30 câu tấn công với LLM thật, dưới tên nhà đầu tư Nhóm B, **0 rò rỉ**. 25 câu bị lớp sau từ chối. 5 câu được trả lời, nhưng chỉ từ tài liệu được phép và đã kiểm chứng trích dẫn. Lớp L2 là lớp bảo vệ thêm; ranh giới quyền nằm ở RLS và bước kiểm tra trực tiếp.

**Che dữ liệu cá nhân** (`pii.py`): che CCCD/CMND, hộ chiếu, di động, email cá nhân trong câu hỏi, câu trả lời và nhật ký, giữ lại 3 ký tự cuối. Không che MST, tài khoản công ty, fax hay số liệu. Che sau bước kiểm chứng câu trích.

**Hạn mức** (`ratelimit.py`): mỗi người tối đa 8 câu/phút và 60 câu/giờ; tối đa 2 câu xử lý LLM cùng lúc. Vượt hạn mức trả 429, kèm thời gian chờ.

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

## Chạy trên Microsoft 365 thật (`DR_TENANT=m365`)

Cùng connector, cùng 4 cổng quyền và cùng luồng trả lời như bản demo. Chỉ phần tenant giả lập được thay bằng `dr/m365/`:

| Thành phần | Làm gì |
|---|---|
| `tenant.py` – `GraphTenant` | Đọc delta của từng thư viện tài liệu, kèm quyền và cột `AI_Use` (gọi theo lô `$batch`). Nhóm SharePoint được giãn ra thành người dùng và nhóm Entra qua REST. Link "Anyone" và link toàn tổ chức không bao giờ được tính là quyền. Danh sách thành viên nhóm, app role và trạng thái tài khoản được chụp lại mỗi 60 giây rồi so với lần trước. Live check dùng **OBO bằng token của chính người hỏi**; không có token thì đóng an toàn. Không bao giờ ghi gì vào tenant |
| `auth.py` | Lấy token app-only bằng chứng chỉ (JWT ký RS256) và token OBO. Không cần MSAL Python |
| `entra_auth.py` | Gateway kiểm token Entra: chữ ký qua JWKS, issuer, audience, hạn dùng, scope `Chat.Use`, role `DataRoom.AIAdmin` |
| Giao diện | Đăng nhập bằng MSAL.js (đăng nhập Microsoft, xác thực đa yếu tố theo chính sách tenant). Link trích dẫn mở thẳng `webUrl` trên SharePoint. Không có ảnh cắt trang scan, và OCR không lưu ảnh trang xuống đĩa |
| `scripts/m365_probe.py` | Chạy 9 phép thử tích hợp (kế hoạch §9.1): tự động phép thử 1, 2, 3 (người thử tự đăng nhập bằng device code), 5, 8; đo X (thời gian thu hồi); in checklist cho phép thử 4, 6, 7, 9 |

Các bước:

```bash
.venv/bin/python scripts/m365_probe.py --example-config > data/m365.json   # điền ID app, chứng chỉ, site, nhóm
make m365-probe      # 9 phép thử trên site thử → logs/m365_probe-*.json
make run-m365        # chạy AI core trên SharePoint/Entra thật
```

Cần quản trị tenant chuẩn bị (kế hoạch §2.1):
- 4 app registration:
  - content/acl reader: `Sites.Selected`;
  - directory reader;
  - `dataroom-ai-api`: expose scope `Chat.Use`, app role, quyền ủy quyền Files.Read cho OBO;
  - SPA.
- Cấp quyền `Sites.Selected` trên site thử.
- Cột `AI_Use` trong thư viện.
- Nhóm DR-INV-*.

Đã kiểm bằng một Graph giả lập ở tầng HTTP (`tests/test_m365.py`). **Chưa chạy trên tenant thật**: phải có thông tin tenant mới chạy được.

## Tốc độ trả lời

Đo trên MacBook M3 Pro 18 GB, model qwen2.5:7b chạy bằng Ollama. Máy này đọc tài liệu đầu vào khoảng 330 token/giây
và sinh chữ khoảng 27 token/giây. Phần LLM đọc tài liệu là phần chậm nhất.

| | Trước | Sau |
|---|---|---|
| Câu hỏi mới | 13–22 s | 6–10 s |
| Câu hỏi lặp lại (cùng phạm vi quyền) | 13–22 s | 0,1–0,3 s |
| Câu đầu tiên sau 5 phút nghỉ | ~40 s (nạp lại model) | như câu thường (model giữ trong bộ nhớ 24 h) |
| Câu nhạy cảm, câu bị chặn | < 0,3 s | < 0,3 s |

Các thay đổi:
- **5 đoạn văn thay vì 10** (`DR_MAX_PASSAGES`). Trên bộ câu hỏi chuẩn, đáp án luôn nằm trong 5 đoạn đầu sau rerank.
- **Chỉ gửi những câu liên quan** (`DR_MAX_SENTENCES=14`). Reranker chấm điểm từng câu trong 5 đoạn văn và chỉ giữ
  14 câu cao nhất, nên phần đầu vào LLM giảm từ khoảng 2.000 xuống còn khoảng 1.000 token.
- **Trích dẫn bằng mã câu.** Mỗi câu trong tài liệu được gắn mã `[D2.3]`, model ghi mã thay vì chép lại câu trích.
  Câu trích hiển thị chính là câu gốc nên luôn đúng nguyên văn, và model sinh ít token hơn. Quy tắc mọi con số trong
  ý trả lời phải có trong câu được dẫn vẫn giữ nguyên. Ở chế độ tra cứu, model chỉ chọn mã câu.
- **Nhớ kết quả theo đúng đầu vào** (LLM, rerank, NLI, embedding). Khóa nhớ gồm câu hỏi và chính các đoạn văn người
  hỏi được phép xem, đã qua kiểm tra trực tiếp. Quyền hoặc phiên bản file thay đổi thì đầu vào đổi theo, nên không
  bao giờ dùng lại đáp án của phạm vi khác. Các cổng quyền và nhật ký vẫn chạy cho mỗi câu hỏi.
- **Model luôn sẵn sàng.** Server nạp sẵn model khi khởi động, Ollama giữ model 24 h (`DR_LLM_KEEP_ALIVE`).
- **Tiến trình thật** qua `POST /api/chat/stream` (NDJSON): bước nào xong hiện ngay bước đó kèm thời gian.
  Dòng tiến trình chỉ có tên bước, không chứa nội dung. Câu trả lời vẫn hiện một lần sau khi đã kiểm chứng và kiểm
  tra quyền lần cuối.

Chất lượng sau khi tăng tốc: QA 9/11 (B-fx là lỗi đã biết; C-price là câu nhạy cảm nên chuyển liên hệ), không rò rỉ 8/8.
Hỏi chéo nhóm: 54/54 không rò rỉ, 30/30 câu nhạy cảm chuyển liên hệ, đối chứng 3/3. Đã thử qwen2.5:3b: chỉ đúng 8/11
và hay trả về mỗi mã câu, nên giữ 7B. Muốn câu mới dưới 2 giây cần máy chủ GPU (prefill vài nghìn token/giây).

## Giới hạn so với production

- SharePoint và Entra là bản giả lập. Connector được viết để sau này thay bằng Graph thật (delta, `/permissions`, OBO).
- Chế độ demo đăng nhập bằng token HMAC. Chế độ `m365` đã có MSAL/Entra nhưng chưa chạy trên tenant thật. MSAL.js đang tải từ CDN; production nên tự host kèm SRI.
- Chỉ mục HNSW đang là một chỉ mục chung. Ở quy mô lớn, người chỉ thấy vài site nên dùng chỉ mục HNSW riêng theo site (xem mục Thử tải).
- Hạn mức để trong bộ nhớ một process; production dùng kho dùng chung ở Gateway.
- Không có sandbox gVisor cho parser, không có ClamAV/YARA. Kiểm tra an toàn file ở mức tối thiểu.
