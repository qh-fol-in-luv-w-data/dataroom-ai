# KẾ HOẠCH TỔNG: AI CORE CHO DATA ROOM TRÊN SHAREPOINT (IPO)

Bản v0.6, ngày 07/10/2026. Bản này cập nhật theo kết quả đo trên bản demo local (mục 14):
- tiền xử lý scan và đối chiếu con số OCR;
- lớp đầu vào L2 chặn ở ngưỡng tin cậy cao;
- che dữ liệu cá nhân;
- hạn mức theo người dùng;
- RLS với chỉ mục toàn văn;
- chính sách ảnh cắt trang scan.

Bản v0.5 ngày 06/10 đã bổ sung offboard nhân viên/cố vấn và mốc chuyển OTP.

**Phạm vi.** Data Room do công ty tự xây trên SharePoint Online (Microsoft 365). Dự án này chỉ xây **AI core**, chạy on-prem tại Việt Nam. Tenant có Microsoft 365 E3, E5 (Purview, Defender for Office 365 P2, Entra ID P2) và một số license Microsoft 365 Copilot.

**Nguồn:**

- **Kế hoạch bảo mật** (`reference/AI_DataRoom_Security_Plan.md`), chỉ dùng làm tham khảo.
- **Khảo sát RAG** ngày 05–06/10 (`research-evidence/`).
- **Phản biện bản v0.2**: 56 phát hiện (`research-evidence/plan-review.json`).
- **Chọn công nghệ AI core** ngày 06/10 (`research-evidence/tech-selection.json`).
- **Thiết kế lại theo Microsoft 365** ngày 06/10: 5 nhóm, kiểm lại trên tài liệu Microsoft (`research-evidence/m365-redesign.json`).
- **Phản biện bản v0.4** theo 5 hướng: 47 phát hiện, không phát hiện nào bị bác; tất cả đã được xử lý trong bản này (`research-evidence/plan-review-v04.json`).
- **Bản demo local và số đo** ngày 06–07/10 (`~/Projects/dataroom-ai-demo`, file `README.md`, thư mục `logs/`). Mục 14 tóm tắt kết quả và các điểm demo khác production.

## 1. Tóm tắt

- Nguồn sự thật về quyền là **SharePoint cùng Entra ID**. AI core đọc tài liệu và quyền qua Microsoft Graph, rồi xử lý và trả lời on-prem.
- AI core chỉ đọc. Mọi cấu hình trên SharePoint, Entra và Purview thuộc về chủ Data Room và quản trị tenant (mục 2).

Các quyết định chính:

1. **Nhà đầu tư là khách Entra B2B** trong tenant công ty. Mỗi nhóm nhà đầu tư có một access package, cấp cùng lúc quyền mở thư mục trên SharePoint và quyền dùng AI. Nhân viên nội bộ có vai trò riêng (`Staff.AI`).
2. **Bốn cổng quyền, phải qua cả bốn** (mục 3.3):
   - RLS trên bản chép quyền;
   - kiểm tra trực tiếp với SharePoint bằng token của chính người hỏi, kiểm cả phiên bản file và cờ `AI_Use`;
   - tập thu hồi theo từng cặp (người, nhóm), lấy từ Entra;
   - danh sách chặn theo người.

   Khi nguồn dữ liệu quyền ngừng cập nhật thì hệ thống đóng lại, không mở.
3. **Quyền ứng dụng, ghi đúng và đủ:**
   - `Sites.Selected` (Graph và SharePoint) trên đúng các site Data Room, cho nội dung và quyền;
   - `Lists.SelectedOperations.Selected` trên thư viện neo nhật ký;
   - `ActivityFeed.Read`: đọc nhật ký kiểm toán toàn tenant, chỉ đọc;
   - quyền đọc thư mục Entra toàn tenant cho danh sách chặn.

   Không dùng `Files.Read.All` ứng dụng, cũng không dùng `Sites.FullControl.All`.
4. **Chỉ kết nối chiều ra từ on-prem tới Microsoft.** Cổng vào duy nhất là giao diện chat, qua reverse proxy và WAF tại DMZ; TLS được giải mã tại Việt Nam.
5. **Không giữ file gốc on-prem.** Câu trả lời được kiểm chứng xong mới gửi cho người hỏi, gửi nguyên một khối. Trích dẫn mở file trong SharePoint.
6. **Không dùng Copilot hay agent của Microsoft cho nhà đầu tư; chặn Copilot nội bộ khỏi Data Room** (mục 6.3, 6.6).
7. **File có nhãn Purview mã hóa bị loại khỏi AI.** LLM chạy on-prem: Gemma 4 31B trên vLLM.
8. **"Độ chính xác 99%"** nghĩa là: trên các câu AI trả lời, độ đúng ≥ 99% với độ tin cậy 95%; AI từ chối nhầm không quá 15%. Định nghĩa đầy đủ ở mục 7.
9. **Bản 1 khoảng 20 tuần**, gồm kiểm thử, sửa lỗi, thử nội bộ, rồi 4 tuần hypercare. Chín phép thử tích hợp ở tuần 1–2 quyết định đi tiếp hay dừng. Microsoft ghi rõ phép thử 3 có khả năng thất bại, nên phương án dự phòng đã được thiết kế sẵn (mục 3.6).

## 2. Phân vai và phụ thuộc bên ngoài

### 2.1 Phân vai

| Việc | Người làm |
|---|---|
| Mời nhà đầu tư thành khách B2B. Chuyển mọi người dùng OTP kiểu cũ của SharePoint sang khách B2B và chia sẻ lại **trước 31/10/2026**. Microsoft chia hai giai đoạn: chia sẻ mới đi qua B2B từ 05–06/2026; link OTP cũ bị từ chối từ tháng 10/2026 và hoàn tất ngày 31/10. Việc tuần 1: liệt kê mọi người dùng bên ngoài trên các site Data Room chưa có tài khoản khách. AI core không chép quyền cho người dùng OTP kiểu cũ mà sinh cảnh báo | Quản trị tenant |
| Access package cho từng nhóm nhà đầu tư; nhóm và access package cho nhân viên (`Staff.AI`) và người duyệt (`Reviewer`); connected organization; access review hằng tháng | Quản trị tenant, deal team duyệt |
| Conditional Access cho khách và cho nhân viên dùng app AI | Quản trị tenant |
| Ngừng quyền một nhà đầu tư: gỡ assignment, chạy `revokeSignInSessions` | Quản trị tenant. AI core không có quyền ghi vào thư mục người dùng |
| Site Data Room: tắt link "Anyone" và link toàn tổ chức; chỉ chia sẻ cho khách đã có; AllowLimitedAccess | Chủ Data Room |
| Quyết định có tách mỗi nhóm nhà đầu tư một site và bật RAC không. Nếu phép thử 3 thất bại thì việc tách site trở thành bắt buộc | Chủ Data Room |
| Gán `AI_Use` ban đầu cho **mọi file đang có** bằng script cập nhật hàng loạt (giá trị mặc định của thư mục chỉ áp cho file tải lên sau); đặt giá trị mặc định cho file mới | Chủ Data Room |
| Nhãn "IPO Data Room": chính sách tự gắn nhãn phía dịch vụ cho file đang có (chạy mô phỏng trước, rồi bật), nhãn mặc định của thư viện cho file mới; DLP chặn Copilot; Restricted Content Discovery | Quản trị Purview / SharePoint |
| Xác nhận thư viện không bật IRM; bật EnableAIPIntegration và DisallowInfectedFileDownload; export cấu hình RAC hằng ngày | Quản trị SharePoint |
| Cấp quyền cho từng site, chạy bằng script của một principal quản trị riêng, mỗi khi có site Data Room mới: content-reader = read; acl-reader = vai trò thấp nhất đủ đọc toàn bộ quyền; dataroom-ai-api = read. Cấp `Sites.Selected` cả cho tài nguyên SharePoint (REST) của acl-reader | Quản trị tenant |
| Đồng ý cấp quyền đọc thư mục cho app directory-reader | Quản trị tenant |
| Mua Workload ID Premium; liên kết Azure subscription để tính phí khách theo MAU | Quản trị tenant |
| Site neo nhật ký, retention policy, Preservation Lock (mục 6.4) | Quản trị Purview, sau khi luật sư chốt thời hạn lưu |
| Chụp lại thẻ Data Location trong admin center đưa vào hồ sơ tuân thủ | Quản trị tenant |
| Bộ câu hỏi chuẩn và gán nhãn (khoảng 50 ngày công nghiệp vụ, ước lượng của tôi) | Trưởng deal team cử người |
| Toàn bộ AI core | Đội AI core |

### 2.2 Sổ phụ thuộc

Cần một **người bảo trợ cấp điều hành**, có quyền thúc quản trị tenant và Purview. Báo cáo hằng tuần liệt kê các mục bị trễ.

| Mục | Chủ | Cần trước | Nếu trễ |
|---|---|---|---|
| Hạn mức ngân sách GPU | BOD | Tuần 0 | Lùi đặt hàng; dời go-live tương ứng |
| Site thử, ≥ 10 khách thử (OTP qua B2B và Entra), cấp quyền cho site thử, đồng ý quyền cho directory-reader, dùng thử Workload ID Premium, Azure subscription | Quản trị tenant | Cuối tuần 1 | Phép thử tích hợp lùi theo ngày |
| Cam kết thời gian của người nghiệp vụ; bắt đầu làm việc với luật sư | Trưởng deal team; pháp chế | Tuần 1 | Cổng độ chính xác và pháp lý lùi theo |
| Ba quyết định của chủ Data Room: tách site/RAC; câu trích từ tài liệu chỉ-xem; chấp nhận rủi ro nếu phải dùng chế độ dự phòng | Chủ Data Room | Tuần 2 | Mặc định giữ cấu trúc hiện tại, hoãn RAC. Nếu phép thử 3 thất bại mà chưa có quyết định thì dừng phần dành cho nhà đầu tư |
| Xác nhận không bật IRM, EnableAIPIntegration, DisallowInfectedFileDownload | Quản trị SharePoint | Tuần 2 | Không nạp production |
| Chọn cấu hình GPU, đặt hàng | Đội AI core, BOD | Tuần 3 | Dời go-live tương ứng |
| Bật tính năng tổng hợp hay không (`Investor.AI.Summarize`) | BOD | Tuần 6 | Mặc định tắt |
| Gán `AI_Use` cho file đang có trên production; nhãn, DLP, RCD trên production | Chủ Data Room; quản trị Purview | Tuần 6 | Chưa có gì để nạp; cổng phủ nhãn trượt |
| GPU giao và chạy thử xong | Nhà cung cấp | Tuần 8 | Go-live lùi theo ngày |
| Access package, Conditional Access, cấp quyền site trên production; export RAC hằng ngày | Quản trị tenant / SharePoint | Tuần 8 | Phase 2 dùng site thử lâu hơn |
| Bộ câu hỏi giữ riêng (≥ 500 câu) đóng băng | Người nghiệp vụ | Tuần 10 | Cổng độ chính xác lùi |
| Thời hạn lưu nhật ký và thời hạn của site neo | Luật sư | Tuần 12 | Chưa khóa Preservation Lock |
| Hợp đồng với đơn vị kiểm thử xâm nhập độc lập | Đội AI core | Tuần 4 (thử ở tuần 14–15, thử lại tuần 17) | Go-live lùi |
| Ý kiến pháp lý bằng văn bản | Luật sư | Trước tuần 18 | Không thử nội bộ |

## 3. Mô hình quyền

### 3.1 Vai trò

| App role | Ai có | Ghi chú |
|---|---|---|
| `Investor.AI` | Nhà đầu tư, cấp qua access package của nhóm | |
| `Investor.AI.Summarize` | Như trên | Chỉ bật khi BOD cho phép tổng hợp |
| `Staff.AI` | Nhân viên phát hành, cố vấn | Access package riêng, deal team duyệt. Có thể chọn phạm vi một nhóm nhà đầu tư cho mỗi phiên, để câu trả lời không trộn tài liệu của nhiều nhóm |
| `Reviewer` | Người duyệt hàng chờ (Bản 2) | |

Mọi vai trò dùng chung các cổng ở mục 3.3. Danh sách chặn được dựng từ cả nhóm nhà đầu tư lẫn nhóm nhân viên.

### 3.2 Ba quyền AI của kế hoạch bảo mật, ánh xạ sang SharePoint và Entra

- **`VIEW`:** người hỏi mở được file trên SharePoint tại thời điểm hỏi.
- **`AI_QUERY` và `AI_CITATION`:**
  - ở cấp tài liệu: `AI_Use` cho phép và file không bị mã hóa;
  - ở cấp người: có app role tương ứng.

  Hai quyền này được **gộp có chủ ý**, vì câu trả lời nào cũng bắt buộc có trích dẫn.
- **`AI_SUMMARIZE`:** app role `Investor.AI.Summarize`, cộng thêm cổng theo ý định câu hỏi do Gateway quyết định.
- **Cột `AI_Use`** có ba giá trị: `Allowed`, `OnPremOnly`, `Excluded`. Để trống được hiểu là `Excluded`. Mọi xử lý hiện đều on-prem, nên `OnPremOnly` và `Allowed` hiện được đối xử như nhau.
- **Quy tắc theo nhãn:** file có nhãn áp mã hóa, kể cả DKE, HYOK hay nhãn có hạn, được coi là `Excluded`. Cờ hiệu lực của file là mức chặt nhất giữa cột `AI_Use` và quy tắc này.

### 3.3 Bốn cổng quyền

**1. RLS trên bản chép quyền**, chạy trước mọi bước truy xuất. Một file chỉ lọt vào tập ứng viên khi thỏa đồng thời:

- có đường cấp quyền đọc cho `oid` này, tính từ quyền trên item của SharePoint và tư cách thành viên nhóm lấy từ delta của Entra;
- đường cấp quyền đó không đi qua nhóm nằm trong tập thu hồi (cổng 3);
- cờ hiệu lực cho phép;
- file đang là phiên bản hiện hành (`is_current`);
- nếu site có RAC, người hỏi thuộc nhóm RAC của site.

**2. Kiểm tra trực tiếp với SharePoint.** Gateway đổi token người hỏi lấy token Graph (OBO, quyền ủy quyền `Sites.Selected`; SharePoint lấy giao của quyền ứng dụng và quyền người dùng). Sau đó gọi theo lô:

```
GET /drives/{d}/items/{i}?$select=id,cTag,eTag&$expand=listItem($expand=fields($select=AI_Use))
```

Lệnh gọi này chạy cho từng file ứng viên trước khi đoạn văn vào LLM, rồi chạy lại cho các file được trích dẫn trước khi trả lời. File bị loại khi gặp một trong các trường hợp:

- kết quả khác 200;
- `cTag` khác với cTag đã lưu cùng các đoạn văn;
- `AI_Use` không cho phép.

**3. Tập thu hồi theo cặp (oid, nhóm).**

- **Nguồn:** delta của nhóm DR-INV, nhóm nhân viên và nhóm RAC, chạy mỗi 60 giây.
- **Tác dụng:** loại mọi đường cấp quyền đi qua nhóm mà người đó vừa rời.
- **Thời hạn giữ một mục:** cho tới khi lần đối soát đêm cho thấy SharePoint đã áp thay đổi, tối thiểu 24 giờ.
- **Vì sao cần:** SharePoint có thể mất tới một ngày mới áp thay đổi nhóm, nên trong khoảng này kiểm tra trực tiếp vẫn cho qua. Tập thu hồi là kiểm soát bảo mật cho đúng tình huống đó: người bị gỡ khỏi một nhóm nhưng còn ở nhóm khác, hoặc bị chuyển nhóm.

**4. Cổng theo người.**

- Token có đúng app role.
- `oid` không nằm trong danh sách chặn (người bị offboard, tài khoản bị tắt).
- Mọi nguồn dữ liệu quyền còn "tươi" (mục 3.5).

**Cổng nào có thẩm quyền với loại thay đổi nào:**

| Thay đổi | Cổng có thẩm quyền |
|---|---|
| Quyền trên item hoặc thư mục SharePoint | Kiểm tra trực tiếp (cổng 2) |
| Thay đổi nhóm Entra, RAC | Tập thu hồi và RLS (cổng 1, 3) |
| Offboard | Danh sách chặn (cổng 4) |
| Phiên bản mới, `AI_Use` | Kiểm tra trực tiếp và `is_current` (cổng 1, 2) |

### 3.4 Thu hồi quyền

| Thao tác | Cái chặn đầu tiên | Độ trễ mục tiêu |
|---|---|---|
| Gỡ quyền file hay thư mục trong SharePoint | Kiểm tra trực tiếp | AI chặn không muộn hơn X giây sau khi SharePoint chặn chính người đó mở file trên trình duyệt. X đo ở phép thử 3. Bản chép quyền cập nhật trong ≤ 5 phút qua getchanges |
| Gỡ khỏi một nhóm, chuyển nhóm, gỡ khỏi nhóm RAC | Tập thu hồi | ≤ 2 phút |
| Offboard | Danh sách chặn (token còn hạn tới 60 phút cũng không qua được) | ≤ 2 phút |
| Đổi `AI_Use` hoặc thay file bằng phiên bản mới | Kiểm tra trực tiếp (so cTag và `AI_Use`) | Câu hỏi kế tiếp |

### 3.5 Đóng an toàn khi có lỗi

- **Nguồn dữ liệu quyền bị cũ:**
  - Delta Entra (nhóm, app-role assignment, trạng thái tài khoản) cũ quá 3 phút: từ chối mọi câu hỏi bằng câu trung tính và cảnh báo.
  - Delta hoặc getchanges của một drive cũ quá 5 phút: loại drive đó khỏi truy xuất.
- **Delta trả 410 hoặc token delta bị đặt lại:** cách ly drive và liệt kê lại toàn bộ.
- **Không đọc được cấu hình RAC của một site:** đóng site đó.
- **Không lấy được token OBO:** không trả lời.
- **403/404 ở kiểm tra trực tiếp:**
  - Loại file **trong im lặng**, chỉ ghi nhật ký nội bộ.
  - Lấy file kế tiếp bù vào, trong một ngân sách cố định.
  - Thời gian phản hồi được đệm theo bậc.
- **429 hoặc quá thời gian với một file nằm trong top-k:**
  - Câu tra cứu, câu về con số và câu đếm trả câu trung tính "vui lòng thử lại".
  - Câu tổng hợp vẫn trả lời, kèm một câu cố định không có con số: "câu trả lời có thể chưa bao gồm mọi tài liệu liên quan".

### 3.6 Chế độ dự phòng nếu phép thử 3 thất bại

Microsoft ghi rằng dưới chế độ giới hạn, người dùng trên thiết bị không được quản lý không truy cập nội dung qua ứng dụng được. Vì vậy phép thử 3 được coi là **có khả năng thất bại** với nhà đầu tư. Khi đó kiểm tra trực tiếp (cổng 2) không dùng được và được thay bằng thiết kế sau.

- **Điều kiện tiên quyết:** mỗi nhóm nhà đầu tư một site, có RAC. Khi đó việc cách ly giữa các nhóm không còn phụ thuộc vào việc chép đúng quyền từng item. Chủ Data Room không đồng ý thì không mở AI cho nhà đầu tư.
- **Thay cổng 2:**
  - acl-reader đọc lại `/permissions` của từng file ứng viên và file được trích dẫn, bằng app-only;
  - đánh giá kết quả với tư cách thành viên nhóm Entra lấy trực tiếp lúc hỏi;
  - kiểm `cTag` và `AI_Use` như cổng 2.
- **Ngưỡng tươi:** delta và getchanges của drive phải thành công trong vòng 5 phút.
- **Cổng go-live đổi thành:**
  - bản chép quyền thừa quyền = 0;
  - chạy lại toàn bộ ma trận rò rỉ và kiểm thử xâm nhập ở chế độ này;
  - có chữ ký của chủ Data Room, quản trị bảo mật và luật sư.
- **Năng lực giảm:** mỗi lần đọc quyền tốn 5 RU, nên mỗi câu hỏi tốn khoảng 85 RU, tức khoảng 9 câu/phút trong ngân sách hiện tại.
- **Lịch:** phần thiết kế này nằm trong Phase 1. Nhân viên trên thiết bị được quản lý vẫn dùng chế độ chính nếu phép thử chứng minh được.

### 3.7 Danh tính trong database và công tắc tắt AI

- **Danh tính.** RLS dựa trên `app.principal_oid`, cho mọi loại người dùng:
  - mỗi giao dịch bắt đầu bằng `SET LOCAL ROLE` và `set_config('app.principal_oid', oid, true)`;
  - role của pool không có `BYPASSRLS`;
  - các bảng bật `FORCE ROW LEVEL SECURITY`;
  - thiếu danh tính thì trả về rỗng.
- **Công tắc tắt AI:**
  - theo thư mục: cập nhật hàng loạt `AI_Use` cho mọi item trong thư mục, bằng script của chủ Data Room; AI core đối soát và báo những item còn `Allowed`;
  - theo nhóm: gỡ app role;
  - toàn hệ thống: tắt ở Gateway. Kỹ sư trực được bật mà không cần xin duyệt (RB-4).

## 4. Kiến trúc tổng

### 4.1 Kết nối với Microsoft 365

```
SharePoint Online (các site Data Room)                Entra ID
  ▲ delta 60 s/drive, tải file, ?format=pdf             ▲ delta nhóm DR-INV/nhân viên/RAC 60 s,
  ▲ REST: role assignment, nhóm SharePoint, getchanges   ▲ app-role assignment, accountEnabled
  ▲ Management Activity API mỗi giờ                     ▲ token OBO cho kiểm tra trực tiếp
  └──── chỉ chiều ra, qua forward proxy có danh sách FQDN ────┘
                         │
          [AI core on-prem, Việt Nam] — mỗi app một certificate (thêm một certificate dự phòng),
                                        khóa không xuất được trong OpenBao
           ├─ content-reader   : Sites.Selected read (Graph)
           ├─ acl-reader       : Sites.Selected, vai trò thấp nhất đủ đọc quyền (Graph + SharePoint), máy riêng
           ├─ directory-reader : GroupMember.Read.All, Application.Read.All, User.Read.All
           │                     (toàn tenant, chỉ đọc; code chỉ lấy đúng trường cần)
           ├─ audit-reader     : ActivityFeed.Read (lọc về site Data Room và app AI ngay lúc nạp)
           ├─ anchor-writer    : Lists.SelectedOperations.Selected write trên thư viện neo
           └─ dataroom-ai-api  : API confidential; OBO với quyền ủy quyền Sites.Selected; có quyền site = read
```

### 4.2 Luồng nạp tài liệu

```
Delta 60 s → item mới, đổi cTag, đổi eTag, hoặc bị xóa
 ├─ Chỉ đổi eTag: đọc lại trường AI_Use và nhãn; không còn cho phép thì xóa đoạn ngay
 ├─ Đổi cTag: đánh dấu mọi đoạn và bản ghi của phiên bản cũ is_current = false NGAY,
 │             rồi đưa vào hàng ưu tiên để nạp lại (làn ưu tiên của Dagster, chạy cả ban ngày)
 └─ Bị xóa: xóa hẳn; ghi biên nhận
 └─ Bỏ qua, chỉ lưu metadata và lý do, nếu: có facet malware; cờ hiệu lực = Excluded; byte tải về vẫn bị mã hóa
 └─ Tải file vào vùng tạm mã hóa trong sandbox gVisor không mạng; xóa khi xử lý xong
 └─ [L3] Magika + libmagic → ClamAV → YARA-X → oletools → giới hạn file nén
 └─ Định tuyến:
     ├─ Excel ───────► đọc trực tiếp xlsx (openpyxl hoặc tương đương), KHÔNG qua PDF:
     │                 giá trị đã tính, định dạng số, chuỗi hiển thị, công thức; tách ô gộp;
     │                 gắn đơn vị và kỳ từ dòng tiêu đề và ghi chú (ví dụ "đơn vị: triệu đồng");
     │                 sheet, dòng, cột ẩn được đánh dấu là không đáng tin; trích dẫn theo sheet!vùng
     ├─ Word, PowerPoint, email ─► Docling cho nội dung; Graph ?format=pdf (dự phòng LibreOffice)
     │                 để có ảnh slide và đầu vào OCR cho ảnh nhúng
     └─ PDF ─────────► chấm chất lượng lớp chữ TRƯỚC khi định tuyến (tỉ lệ dấu tiếng Việt hợp lệ,
                       tỉ lệ từ có trong từ điển, ký tự rác): đạt → Docling; không đạt hoặc là scan →
                       raster bằng pypdfium2 (~200 dpi) → làm sạch trang → PaddleOCR-VL-1.6
 └─ Làm sạch trang trước OCR (chỉ dùng model có sẵn, mỗi bước chỉ chạy khi trang cần; đo ở mục 14):
     nắn phẳng ảnh chụp (chỉ khi viền ảnh tối hơn trang giấy, tức có mặt bàn) → cân sáng →
     phóng to trang < ~180 dpi → tự nhận hướng 0/90/180/270 (dáng dòng chữ + điểm nhận dạng
     xuôi/ngược) → chỉnh nghiêng. KHÔNG lọc nhiễu fax: ở 100 dpi dấu chấm/phẩy trong số chỉ 1–2 px,
     lọc nhiễu biến "12.345" thành "12345"
 └─ Đối chiếu con số: PP-OCRv5 đọc lại cùng trang đã làm sạch. Số mà bộ đọc thứ hai không thấy, hoặc
     sai định dạng số Việt Nam (nhóm sau dấu chấm phải đủ 3 chữ số, thập phân dùng dấu phẩy), bị gắn
     cờ "chưa xác nhận" trên đoạn (ocr_doubt). Ý nào dùng số bị gắn cờ thì hiện "chưa chắc"
 └─ Trang OCR có số bị gắn cờ, chữ viết tay, điểm thấp hoặc nhiều bảng: vào hàng chờ người duyệt
     trước khi mở AI cho nhà đầu tư; trong lúc chờ thì tạm loại, chưa được trích
 └─ [L3] Làm sạch Unicode và chữ ẩn → chấm điểm injection → phát hiện dữ liệu cá nhân
 └─ Cắt đoạn → PostgreSQL dưới RLS: văn bản; văn bản đã tách từ và bản bỏ dấu (BM25); embedding;
        vị trí trích dẫn theo loại file; converter_id + phiên bản; sp_item_id; eTag/cTag; nhãn; AI_Use;
        site; nhóm; is_current
 └─ Đổi converter thì nạp lại cả file, không bao giờ trộn đoạn của hai converter
 └─ [Bản 2] LangExtract → bảng bản ghi, mỗi dòng gắn với phiên bản; chỉ dòng is_current được truy vấn
 └─ So sánh với liệt kê đầy đủ mỗi tuần; nạp hàng loạt chạy ban đêm
```

**Vị trí trích dẫn theo loại file:**

| Loại file | Vị trí trích dẫn |
|---|---|
| PDF | Số trang |
| Word | Đường dẫn tiêu đề + một đoạn trích ngắn; số trang chỉ ghi "khoảng" |
| PowerPoint | Số slide |
| Excel | `sheet!vùng` |

### 4.3 Đồng bộ quyền

| Nguồn | Chu kỳ |
|---|---|
| Graph delta theo drive | 60 s |
| Graph `/permissions` trên gốc phân cấp quyền và item mới đổi | Theo delta |
| SharePoint REST getchanges (role assignment, thành viên nhóm SharePoint, security policy) | 1–5 phút |
| Entra delta: nhóm DR-INV, nhân viên, RAC (cùng transitiveMembers), app-role assignment, accountEnabled | 60 s |
| Cấu hình RAC: khai báo trong git, đối chiếu với export của quản trị SharePoint | Hằng ngày |
| Đối soát quyền của mọi gốc phân cấp quyền, và cờ `AI_Use` | Hằng đêm |
| Liệt kê lại toàn bộ | Hằng tuần |

Mọi nguồn đều có mốc "lần thành công cuối" để áp quy tắc ở mục 3.5. Kết quả được dựng thành `item_reader(item_id, oid)` cùng tập thu hồi, rồi đưa vào chính sách RLS.

Quy tắc mở rộng quyền: chỉ tính quyền cấp cho người dùng, nhóm Entra, nhóm SharePoint và link người cụ thể. Link "Anyone", link toàn tổ chức, EEEU và Limited Access không bao giờ được mở rộng thành quyền, mà sinh cảnh báo. Mỗi lần acl-reader đọc quyền, kết quả được so với ảnh chụp trước. Cấp quyền nào không khớp thiết kế nhóm thì cảnh báo trong vài phút và đóng băng AI cho site đó.

### 4.4 Luồng truy vấn

```
Người dùng mở ai.dataroom.<tên miền công ty> (link đặt trên site Data Room)
 └─ Reverse proxy + WAF tại DMZ → FastAPI; SPA và API cùng một origin
 └─ [L1] MSAL đăng nhập Entra qua login.microsoftonline.com/{tenantId}; Conditional Access đã áp lúc cấp token
        Gateway kiểm iss, aud, scp = Chat.Use, roles, oid; cổng 4 (danh sách chặn, độ tươi)
 └─ [L2] hạn mức theo oid và IP (mặc định 8 câu/phút, 60 câu/giờ) + trần số câu xử lý đồng thời trên GPU
        → kiểm soát hàng đợi (khi gần hết ngân sách thì xếp hàng hoặc báo "hệ thống đang bận",
        không trả lời với ít nguồn hơn)
        → chuẩn hóa: NFKC, bỏ ký tự vô hình/điều khiển hướng, đổi ký tự giả dạng Cyrillic/Greek
        → luật injection tiếng Việt (có dấu và không dấu) và tiếng Anh, chạy trên cả dạng giải
          base64/hex, leetspeak và chữ cách quãng
        → bộ phân loại hồi quy logistic trên embedding bge-m3 (chính vector dùng để tìm kiếm, không
          tốn thêm). Câu dài được chấm thêm từng câu, với ngưỡng riêng cao hơn
        → CHẶN khi luật khớp hoặc điểm vượt ngưỡng tin cậy cao; điểm thấp hơn thì chỉ ghi log.
          Đổi sang chỉ ghi log nếu tỉ lệ chặn nhầm trên câu hỏi thật của đợt thử nội bộ > 1% (mục 7)
        → che dữ liệu cá nhân trong câu hỏi trước khi vào LLM và nhật ký → nhận diện ngôn ngữ
        → kiểm tra phạm vi
 └─ Phân loại câu hỏi (Gateway quyết định)
 └─ [L4] BM25 (truy vấn cả dạng có dấu và bỏ dấu) + vector trong PostgreSQL dưới RLS (cổng 1, 3), chỉ trên
        các phân vùng người hỏi được cấp → gộp RRF → rerank → gom theo file
        RLS nằm ngay trong câu truy vấn tìm kiếm (vai trò không vượt RLS), ứng dụng không giữ danh sách id.
        Người hỏi thấy ít (≤ 20 nghìn đoạn): tìm vét cạn trên đúng file của họ; thấy nhiều: HNSW với
        iterative scan; HNSW riêng theo phân vùng cho người chỉ thấy một vài phân vùng.
        Lưu ý đã đo: dưới RLS, Postgres KHÔNG dùng chỉ mục GIN cho `@@` (hàm không LEAKPROOF) và quét
        cả bảng (1,2 s ở 200 nghìn đoạn). Lấy ứng viên qua một hàm SECURITY DEFINER chỉ trả id, rồi
        RLS lọc trong cùng câu SQL. Phải kiểm lại điều này với pg_textsearch ở PoC. Tắt JIT cho vai trò truy vấn
        Trần số file: đặt từ đường cong recall ở PoC (mặc định 12; cao hơn cho câu tổng hợp hoặc liệt kê)
 └─ [L4] Kiểm tra trực tiếp (cổng 2) theo $batch; 403/404 → loại im lặng, lấy file kế tiếp bù vào
 └─ Đọc cách ly từng đoạn → tổng hợp bằng JSON có ràng buộc schema; tối đa 5 file được trích dẫn
 └─ [L5] Kiểm chứng: chunk_id thuộc tập đã kiểm → câu trích có trong đoạn → con số khớp → số từ trang scan
        bị gắn cờ thì ý thành "chưa chắc" → NLI → LLM chấm lại → DLP: che CCCD/CMND, hộ chiếu, di động,
        email cá nhân SAU khi kiểm chứng (không che MST, tài khoản công ty, số liệu)
 └─ [L5] Kiểm tra trực tiếp lần hai trên các file được trích dẫn, kiểm lại cổng 4
        Một file bị loại ở bước này → xóa mọi ý dựa vào nó, chạy lại L5 hoặc sinh lại câu trả lời;
        không bao giờ gửi một ý đã mất trích dẫn
 └─ [L5] Nhật ký: một dòng trước khi trả, một dòng niêm phong hash sau khi trả
 └─ Trả lời: toàn bộ đầu ra của LLM được giữ ở server; SSE chỉ mang sự kiện tiến độ và heartbeat
        cho tới khi mọi bước trên qua; câu trả lời đã kiểm được gửi một lần
 └─ Giao diện: câu trích (văn bản; câu trích từ trang OCR ghi "văn bản nhận dạng từ bản scan"),
        vị trí trích dẫn theo loại file, link webUrl mở file trong SharePoint
        Không bao giờ trả downloadUrl, ảnh trang hay file gốc
        Ngoại lệ có điều kiện cho câu trích từ trang scan, để người đọc đối chiếu con số: ảnh cắt đúng vùng
        câu trích, chỉ khi file KHÔNG chịu chính sách chặn tải hay chỉ xem; ảnh được dựng khi có yêu cầu
        từ file lấy bằng token của chính người hỏi, chỉ trong bộ nhớ, không cache. On-prem chỉ lưu tọa độ
        vùng (page, bbox). File chặn tải: chỉ hiện "trang N, vùng …" và link mở đúng trang trên SharePoint
        (bản demo đang cache ảnh trang trên đĩa, là điểm khác production, xem mục 14)
```

### 4.5 Câu hỏi đếm và tổng (Bản 2)

1. Chạy truy vấn SQL theo mẫu dưới RLS, chỉ trên các dòng `is_current`.
2. Liệt kê các file nguồn khác nhau của kết quả.
3. Kiểm tra trực tiếp **tất cả** các file đó, theo lô 20.
4. Chỉ tổng hợp trên các dòng thuộc file đã qua kiểm tra.

Quy tắc kèm theo:

- **Trần:** 100 file. Vượt trần thì đề nghị người hỏi thu hẹp câu hỏi.
- **Kết quả không đầy đủ:** gặp 429 hoặc quá thời gian với bất kỳ file nào trong phạm vi thì trả câu cố định "chưa thể đếm đầy đủ lúc này, vui lòng thử lại", **không bao giờ trả một tổng thiếu**. 403/404 chỉ đơn giản đưa file ra khỏi phạm vi.
- **Ngân sách:** có dòng ngân sách RU riêng và hàng đợi riêng.
- **Cache:** có thể giữ kết quả kiểm tra theo (oid, item, cTag) tối đa 60 giây, xóa ngay khi có sự kiện delta hoặc thu hồi.

## 5. Kiểm soát cho từng thành phần

| Thành phần | Đường rò rỉ | Kiểm soát |
|---|---|---|
| Bản chép quyền | Thu hồi hay cấp quyền đến chậm; delta 410; nhóm SharePoint không xuất hiện trong delta | Với thay đổi quyền trên item: kiểm tra trực tiếp có thẩm quyền, bản chép chỉ ảnh hưởng độ phủ. **Với thay đổi nhóm Entra: bản chép (thành viên nhóm và tập thu hồi) là kiểm soát bảo mật.** Áp ngưỡng tươi, cách ly khi 410, dùng getchanges, đối soát đêm |
| Thay đổi nhóm chậm tới SharePoint (tới 1 ngày) | Người rời một nhóm nhưng còn nhóm khác vẫn qua được kiểm tra trực tiếp | Tập thu hồi theo cặp (oid, nhóm), giữ tối thiểu 24 giờ |
| Nguồn quyền ngừng cập nhật | Danh sách chặn và tập thu hồi đứng yên trong khi hệ thống vẫn trả lời | Ngưỡng tươi; từ chối câu hỏi khi delta Entra cũ quá 3 phút |
| Phiên bản cũ | Trích bản trước khi biên tập lại; trích file đã bị đặt Excluded | Đặt `is_current = false` ngay khi đổi cTag; kiểm tra trực tiếp so cTag và `AI_Use` |
| Thông báo lỗi và thời gian phản hồi | Thông báo "có nguồn không xác minh được" hoặc số file thay đổi cho A biết B có tài liệu liên quan | Loại im lặng khi gặp 403/404; lấy file khác bù vào; đệm thời gian; thông báo chung chỉ cho 429/timeout |
| Stream | Văn bản chưa kiểm tới trình duyệt | Giữ toàn bộ ở server, gửi một khối sau khi kiểm xong |
| Token của khách | CAE không hỗ trợ khách | Token 60 phút; sign-in frequency 8 giờ; cổng 4 ở mọi request |
| Nhân viên, cố vấn | Thấy nhiều nhóm, có thể chuyển tiếp câu trả lời trộn tài liệu của nhiều nhóm | `Staff.AI` riêng; có thể chọn phạm vi một nhóm cho mỗi phiên; có trong ma trận rò rỉ |
| directory-reader | Đọc thư mục toàn tenant | Chỉ đọc; code chỉ lấy đúng trường cần; Conditional Access cho workload identity; cảnh báo từ sign-in log |
| acl-reader | Có quyền ghi trong site nếu cần vai trò cao | Thử vai trò thấp nhất trước. Nếu phải dùng fullcontrol: Conditional Access cho workload identity là bắt buộc; chạy trên máy riêng mà proxy chiều ra chỉ cho GET (và POST `/$batch` chứa toàn GET); so ảnh chụp quyền mỗi lần đọc; đóng băng site khi có cấp quyền lạ |
| Danh tính ứng dụng | Certificate bị lộ | `Sites.Selected`; khóa không xuất được trong OpenBao; Conditional Access chặn mọi IP ngoài IP ra của on-prem |
| File có nhãn mã hóa | Giải mã rồi hiển thị nội dung mà nhãn không cho chép | Không giải mã; kiểm byte là căn cứ cuối cùng; ngoại lệ chỉ bằng `Unlock-SPOSensitivityLabelEncryptedFile` do quản trị viên chạy, có ghi nhật ký |
| Câu trích | Văn bản rời khỏi chế độ chỉ-xem | Chỉ câu trích đã kiểm, có giới hạn độ dài; tài liệu không được lộ chữ thì đặt `Excluded` |
| Link | downloadUrl còn dùng được khoảng 1 giờ sau khi thu hồi; URL xác thực sẵn của `format=pdf` | Chỉ dùng webUrl. URL xác thực sẵn không bao giờ ghi vào log và chỉ content-reader được đi theo |
| Đưa giao diện ra internet | Câu trả lời bị giải mã trên dịch vụ cloud trung gian | Reverse proxy + WAF tại DMZ |
| Copilot nội bộ | Nhân viên dùng Copilot tóm tắt tài liệu IPO | Nhãn phủ 100% (tự gắn cho file đang có, nhãn mặc định cho file mới) + DLP + RCD. RCD không che file người dùng sở hữu, mới dùng hay đang mở, nên DLP với nhãn phủ đủ mới là kiểm soát chính. Tên file không chứa chi tiết nhạy cảm |
| Chỉ mục BM25 và vector | Thống kê từ khóa tính cả tài liệu bị ẩn; HNSW lọc sau phụ thuộc dòng ẩn | Phân vùng theo nhóm nhà đầu tư (và tách nội bộ với bên ngoài); thống kê BM25 tính riêng cho từng phân vùng; chỉ truy vấn phân vùng được cấp; tài liệu dùng chung cho nhiều nhóm được lập chỉ mục trong từng phân vùng |
| Bảng bản ghi, liên kết chéo (Bản 2) | Đếm tính cả hồ sơ không được xem; bảng thực thể gộp | Mục 4.5; SQL theo mẫu; nối bằng khóa chính xác; Splink chỉ gợi ý ngoại tuyến, người duyệt, không vào luồng truy vấn |
| Vòng lặp agent | Đoạn văn bị cài lệnh đổi tham số công cụ | Thứ tự bước cố định; công cụ chỉ đọc; phạm vi lấy từ phiên |
| Parser, OCR | File độc chiếm worker | Sandbox gVisor không mạng; GPU chỉ nhận ảnh và văn bản |
| Giao diện chat | Model sinh ảnh hoặc link markdown để đẩy dữ liệu ra ngoài | Markdown chỉ có chữ; CSP chặt; link trích dẫn do ứng dụng dựng |
| Cache | Trả lại câu trả lời của người khác | Không cache câu trả lời. Token OBO cache theo oid trong thời hạn, không ghi đĩa |
| Xóa, rút tài liệu | Bản phái sinh còn sót | Mục 4.2; backup ≤ 35 ngày |
| Hàng chờ người duyệt | Sửa số liệu sai lan tới mọi người | Vai trò `Reviewer`. Trang hoặc vùng bảng được render lại theo yêu cầu trong sandbox, từ SharePoint, chỉ cho người duyệt nội bộ, xóa sau khi duyệt. Trường số cần hai người |
| Phản hồi từ chối | Kiểu từ chối khác nhau làm lộ sự tồn tại của tài liệu | Một câu trung tính; đệm thời gian |
| Tính năng học | Chuyển mối quan tâm giữa các nhà đầu tư | Không có |
| Nhật ký, trace, bảng điều khiển | Lộ mối quan tâm của từng nhà đầu tư cho người nội bộ | Trace chỉ ghi ID, có test CI. Bảng điều khiển và nhật ký dùng RBAC qua nhóm Entra, không chỉ dựa vào mạng; oid được ẩn danh hóa trên bảng điều khiển. Nội dung câu hỏi chỉ vai trò tuân thủ đọc được, có ghi lại mỗi lần đọc. Nhật ký Purview được lọc về site Data Room ngay lúc nạp |
| Kết nối ra ngoài | Worker gọi dịch vụ ngoài | Forward proxy với danh sách FQDN; parser không có mạng |
| Chuỗi cung ứng (D08) | Gói phần mềm, trọng số hay công cụ CI bị cài mã độc | Khóa hash; mirror nội bộ; ghim công cụ CI theo digest; tắt `trust_remote_code` |

## 6. Bảng quyết định công nghệ

Cột "Điều kiện" là bắt buộc.

### 6.1 Danh tính, quyền, bức tường giữa các nhóm

| Vị trí | Chọn | License | Dự phòng | Điều kiện |
|---|---|---|---|---|
| Danh tính nhà đầu tư | Khách Entra B2B. Ai có Entra thì dùng tài khoản công ty của họ; còn lại dùng mã OTP qua email của Entra | E3/E5; phí khách theo MAU | Tài khoản do công ty cấp | Chuyển OTP SharePoint kiểu cũ trước 31/10/2026; chỉ deal team được mời khách; tắt SMS cho khách; authority theo tenant |
| Vòng đời | Entitlement management (chỉ tính năng P2): access package cho từng nhóm nhà đầu tư, cho nhân viên và người duyệt; hạn 90 ngày hoặc tới mốc IPO; access review hằng tháng | P2 | Mời thủ công | Không dùng tính năng của Entra ID Governance add-on; kiểm hằng tháng cờ `GovernanceLicenseFeatureUsed` |
| Conditional Access | Khách: MFA (authentication strength chỉ cho khách có Entra), điều khoản sử dụng (NDA), sign-in frequency 8 giờ, app-enforced restrictions. Nhân viên: chính sách nội bộ hiện hành | P1 | — | Không yêu cầu thiết bị tuân thủ cho khách |
| Cổng quyền | Bốn cổng (mục 3.3) | — | Chế độ dự phòng (mục 3.6) | Phép thử 3 |
| Quyền ứng dụng | Sáu app ở mục 4.1 | Workload ID Premium (khoảng 3 USD/identity/tháng) | Không có Premium: certificate + cảnh báo từ log. Riêng acl-reader dùng fullcontrol thì Premium là bắt buộc | Không dùng client secret. Quyền site do principal quản trị riêng cấp, bằng script. Mỗi service principal gán trực tiếp vào policy |
| Token | SPA (public) và API (confidential, scope `Chat.Use`, app role). OBO với quyền ủy quyền `Sites.Selected` | — | Quyền ủy quyền `Files.Read.All`: ngoại lệ đã duyệt, cần quản trị bảo mật ký. Vẫn bị giới hạn bởi quyền của chính người dùng | Claims challenge; `offline_access`; cache token OBO |
| Bức tường thứ hai | Mỗi nhóm nhà đầu tư một site (communication site) + RAC | SAM, có sẵn nhờ license Copilot | Chỉ quyền trên item + phân vùng trong AI core | Bắt buộc nếu dùng chế độ dự phòng. Mỗi site tối đa 10 nhóm. Không dùng Teams shared channel |

**Đã loại:**

| Phương án | Lý do |
|---|---|
| Keycloak | SharePoint chỉ cấp quyền cho principal Entra |
| Entra External ID | Không có đường truy cập SharePoint |
| B2B direct connect | Chỉ dùng cho kênh Teams shared channel |
| Information Barriers | Ảnh hưởng toàn tenant |
| SpiceDB | SharePoint mới là nguồn quyền |

### 6.2 Kết nối Microsoft 365, mạng, giao diện

| Vị trí | Chọn | Dự phòng | Điều kiện |
|---|---|---|---|
| Phát hiện thay đổi | Mục 4.3 | Change notification qua Event Hubs, chỉ để đánh thức poller, nếu chủ chấp nhận thêm tài nguyên Azure | Không webhook. Gửi User-Agent `NONISV\|<Company>\|VDR-AI/<ver>` |
| Ngân sách throttling | Chia theo app. dataroom-ai-api ≤ 750 RU/phút cho kiểm tra trực tiếp (≈ 44 câu/phút ở mức khoảng 17 RU/câu). content-reader ≤ 750 ban ngày, ≤ 1.000 ban đêm. acl-reader ≤ 750; một lần đối soát đêm tốn số gốc phân cấp × 5 RU, phải nằm trong 1,2 triệu RU/ngày. Trần chung cho cả AI core ban ngày ≤ 1.500 RU/phút | Bậc 1.001–5.000 license (gấp đôi) | Hạn mức tenant 18.750 RU / 5 phút (khoảng 3.750/phút) dùng chung với Copilot, backup và DLP, nên AI core theo dõi tổng. Giới hạn theo người cho khách đặt sau phép thử 8. Ngày go-live tạm dừng nạp hàng loạt và liệt kê lại |
| Office → PDF | Graph `?format=pdf` cho Word, PowerPoint, email (không bao giờ cho Excel) | LibreOffice trong gVisor (Gotenberg ≥ 8.37, image chỉ có LibreOffice) | `Sites.Selected` bị từ chối thì dùng LibreOffice, không nới quyền. Ghi riêng host của URL chuyển hướng `format=pdf` và chỉ thêm đúng host đó vào danh sách cho phép |
| Lưu trữ on-prem | Không giữ file gốc; chỉ dữ liệu phái sinh, PostgreSQL trên ổ LUKS | — | Backup ≤ 35 ngày. Thời hạn xóa tối đa = max(backup, chu kỳ poll, chu kỳ liệt kê lại) |
| Mạng | Forward proxy với FQDN cụ thể: `graph.microsoft.com`, `login.microsoftonline.com`, `<tenant>.sharepoint.com`, `manage.office.com`, CRL/OCSP | — | Kiểm danh sách endpoint của Microsoft hằng ngày; ghi lại host tải file thực tế trong pilot; không mở wildcard |
| Giao diện | assistant-ui + MSAL.js, SPA và API cùng origin, qua reverse proxy + WAF tại DMZ | Entra Application Proxy, nếu chủ chấp nhận TLS bị giải mã trên cloud | Proxy dự phòng (mục 6.10); không chuyển gói nào vào trong trước khi JWT hợp lệ |
| Trích dẫn | Câu trích + vị trí theo loại file + webUrl | Nếu phép thử 6 thất bại: chỉ câu trích và vị trí | Không trả downloadUrl, ảnh trang hay file gốc |

**Đã loại:**

| Phương án | Lý do |
|---|---|
| Entra Application Proxy | Giải mã TLS trên cloud; timeout 180 giây; cần máy chủ Windows làm connector |
| Webhook về on-prem | Mở cổng vào từ internet |
| Header `deltashowsharingchanges` | Cần `Sites.FullControl.All` |
| SPFx | Quyền gắn vào principal SharePoint dùng chung cho cả tenant |
| SeaweedFS, trình xem ảnh trang riêng | SharePoint đã giữ bản gốc và có trình xem |

### 6.3 Purview và an toàn tài liệu

| Vị trí | Chọn | License | Điều kiện |
|---|---|---|---|
| Cờ AI | Cột `AI_Use`; gán ban đầu bằng script hàng loạt; giá trị mặc định cho file mới; quy tắc theo nhãn ở mục 3.2 | Có sẵn | Thay đổi cột được ghi vào nhật ký; đối soát đêm |
| File mã hóa | Loại khỏi AI; không dùng super user hay MIP SDK | — | Kiểm byte là căn cứ cuối cùng; xác nhận thư viện không bật IRM |
| Mã độc | Facet malware + DisallowInfectedFileDownload + chuỗi on-prem (Magika, ClamAV, YARA-X, oletools, gVisor) | Defender for Office 365 P2 | Microsoft không quét mọi file và không hứa quét file tải qua API, nên chuỗi on-prem là kiểm soát chính. Kiểm lại facet malware định kỳ |
| Chặn Copilot nội bộ | Nhãn "IPO Data Room" (không mã hóa): chính sách tự gắn nhãn phía dịch vụ cho file đang có, nhãn mặc định thư viện cho file mới. DLP cho vị trí Microsoft 365 Copilot. RCD | DLP cho Copilot chỉ có trong E5 | Mọi người dùng Copilot có quyền vào Data Room phải có E5 hoặc add-on E5 IPG. Bật trước khi nạp: DLP mất tới 4 giờ, RCD có thể hơn một tuần. Kiểm agent SharePoint/Copilot Studio; nếu chúng không tuân DLP thì chặn tạo agent |
| Vệ sinh quyền trước go-live | Báo cáo data access governance của SAM, site access review, phép thử rò rỉ riêng của AI core | SAM có sẵn nhờ license Copilot; báo cáo nhãn cần E5 | DSPM chỉ phát hiện link bên ngoài hoặc ẩn danh, không phát hiện cấp nhầm trực tiếp; chỉ dùng tham khảo |

**Đã loại:**

| Phương án | Lý do |
|---|---|
| Super user | Toàn quyền trên mọi nội dung mã hóa của tenant |
| Gắn nhãn từ AI core | API tính phí, cần quyền ghi |
| Restricted SharePoint Search | Không cho bật mới từ 31/07/2026, ngừng hẳn ngày 31/01/2027 |

### 6.4 Nhật ký

| Vị trí | Chọn | Điều kiện |
|---|---|---|
| Nhật ký câu trả lời | Bảng append-only, hash nối chuỗi trong PostgreSQL | Ghi nối tiếp bằng advisory lock (kiểm lại trong phép đo tải); một dòng trước khi trả, một dòng niêm phong sau khi trả |
| Nhật ký Microsoft 365 | Poll Management Activity API mỗi giờ (Audit.SharePoint, Audit.General, Audit.AzureActiveDirectory), lọc về site Data Room và app AI, lưu on-prem | Purview chỉ giữ hoạt động của khách, của người không có E5 và của app AI core trong 180 ngày; người dùng nội bộ có E5 được giữ 1 năm. Blob hết hạn sau 7 ngày. Cảnh báo khi trễ quá 24 giờ, và khi nội dung mới nhất đã cũ hơn 5 ngày. Truyền PublisherIdentifier |
| Neo WORM | Đầu chuỗi được ký, ghi vào thư viện "AI-Audit-Anchor" trên một site riêng. Thư viện có nhãn record mặc định; retention policy phạm vi tĩnh khóa bằng Preservation Lock | Các bước bắt buộc, theo thứ tự: |

Thứ tự triển khai neo WORM:

1. Chạy thử đầu cuối với retention policy **chưa khóa**, và xác minh phạm vi tĩnh chỉ chứa đúng site neo.
2. Luật sư chốt thời hạn lưu bằng văn bản.
3. Khóa chỉ sau một yêu cầu thay đổi đã ký, trước phép thử WORM ở tuần 14.
4. Tắt quyền sửa thuộc tính record.
5. Neo lỗi **không** chặn câu trả lời: checkpoint xếp hàng tại chỗ, chuỗi hash vẫn chạy, bảng điều khiển cảnh báo khi quá N giờ chưa neo được.

### 6.5 AI core on-prem

| Vị trí | Chọn | Điều kiện chính |
|---|---|---|
| Kho tìm kiếm | PostgreSQL 17/18 + pgvector + pg_textsearch, gộp RRF | pgvector ≥ 0.8.7, cấm IVFFlat. pg_textsearch ≥ 1.5.1. Không trả điểm. Phân vùng theo nhóm nhà đầu tư và tách nội bộ với bên ngoài, thống kê BM25 riêng cho từng phân vùng. Có thêm trường bỏ dấu. Thử cách tách từ có `_` |
| Khóa | OpenBao ≥ 2.7.1, cụm 3 node | Giữ certificate của các app dưới dạng khóa không xuất được |
| Điều phối | Dagster OSS, không Spark | Ghim 1.13.x; có làn ưu tiên để nạp lại khi đổi cTag; giao diện sau RBAC |
| Sandbox | gVisor, nvproxy | Driver nằm trong danh sách hỗ trợ; không dùng NVIDIA DRA; dự phòng Kata (phép thử 9) |
| Đọc file, OCR | Docling; PaddleOCR-VL-1.6; openpyxl cho Excel; pypdfium2 | Không dùng PyMuPDF (AGPL) |
| Tách từ, embedding, rerank | underthesea; bge-m3; bge-reranker-v2-m3 | Endpoint nội bộ |
| LLM | Gemma 4 31B trên vLLM ≥ 0.31.0 (dự phòng Qwen 3.8 27B) | So hai model trong PoC; tắt `trust_remote_code`; chỉ Gateway gọi được |
| Chống injection | Ngăn bằng cấu trúc. Bản 1: chuẩn hóa + luật tiếng Việt/tiếng Anh + hồi quy logistic trên embedding bge-m3 (có sẵn, đa ngôn ngữ), chặn ở ngưỡng tin cậy cao | Bỏ Prompt Guard 2: Meta khóa model (phải xin duyệt thủ công) và model không hỗ trợ tiếng Việt. Huấn luyện lại trên câu tấn công thật thu từ red-team. Bộ phân loại tinh chỉnh từ mmBERT vẫn để Bản 1.1 |
| Dữ liệu cá nhân | Bộ nhận dạng tiếng Việt tự viết (CCCD 12 số, CMND, hộ chiếu, di động, email; loại trừ theo ngữ cảnh MST, tài khoản, fax); Presidio làm khung nếu cần thêm loại | Không dùng NlpHUST ELECTRA. Che sau bước kiểm chứng câu trích |
| Hạn mức | Cửa sổ trượt theo oid (8/phút, 60/giờ) + semaphore số câu đồng thời trên GPU | Bản 1 đặt ở Gateway; nhiều node thì dùng kho dùng chung |
| Làm sạch scan | OpenCV + PP-OCRv5 det/rec (đã có cho PaddleOCR): nắn phẳng, cân sáng, phóng to, xoay, chỉnh nghiêng; PP-OCRv5 latin làm bộ đọc thứ hai để đối chiếu số | Không thêm model; không lọc nhiễu fax |
| Kiểm căn cứ | Kiểm câu trích tất định + NLI mDeBERTa + LLM chấm lại; `vn_numeric` | NLI không bao giờ là lý do duy nhất để chấp nhận |
| Đo lường, trace | DeepEval trong CI. Bản 1: OpenTelemetry chỉ ghi ID vào kho log nội bộ | Langfuse dời sang Bản 1.1. Tắt telemetry |
| Gateway | FastAPI tự viết | Không dùng LiteLLM |
| Red-team | garak, promptfoo, PyRIT | |
| Liên kết chéo (Bản 2) | Nối bằng khóa chính xác | Splink chỉ gợi ý ngoại tuyến, có người duyệt, không vào luồng truy vấn |

### 6.6 Vì sao không dùng AI có sẵn của Microsoft

| Lựa chọn | Lý do không dùng cho nhà đầu tư |
|---|---|
| Microsoft 365 Copilot, SharePoint agents | Không cấp license Copilot cho khách B2B được (theo Microsoft Q&A); không kiểm soát được chất lượng tiếng Việt, trích dẫn hay phép đếm |
| Copilot Studio với nguồn SharePoint | Câu trả lời từ SharePoint không có cho khách trong app bật SSO; chỉ tóm tắt 3 kết quả đầu; không đọc được file có nhãn mã hóa |
| Microsoft 365 Copilot Retrieval API | Tối đa 25 kết quả; 200 yêu cầu mỗi người mỗi giờ; Excel chỉ tìm theo từ khóa; không đọc ảnh hay biểu đồ; gói trả theo lượt cho người không có license vẫn ghi preview |
| Azure AI Search, SharePoint indexer | Preview; không mở rộng nhóm lồng; chép nội dung sang Azure |

Nhân viên nội bộ dùng Copilot cho việc thường ngày, nhưng với dữ liệu Data Room thì dùng AI core.

### 6.7 Phần cứng

Đây là ước lượng của tôi.

- **Tối thiểu:** 4 × L4 24 GB.
- **Khuyến nghị:** 2 × H100 80 GB, hoặc A100 80 GB.
- **Chọn cấu hình:** sau khi so model ở tuần 3. Định cỡ cho tải ban ngày chạy đồng thời: LLM, embedding, rerank, NLI, chấm lại. OCR và nạp hàng loạt chạy ban đêm.
- **Tuần 1–8:** thuê hoặc mượn GPU cùng dòng card, đặt on-prem. Nếu thuê GPU trên cloud thì chỉ được chạy tài liệu đã công bố hoặc tài liệu giả lập.
- GPU cho worker OCR phải nằm trong danh sách nvproxy hỗ trợ.

### 6.8 Đã loại (tổng hợp)

| Công cụ | Lý do |
|---|---|
| Keycloak, SpiceDB, Entra External ID, B2B direct connect, Information Barriers | Mục 6.1 |
| Entra Application Proxy, webhook, SPFx, Event Hubs (mặc định) | Mục 6.2 |
| SeaweedFS, trình xem riêng, Gotenberg làm đường chính | Mục 6.2 |
| `Files.Read.All` ứng dụng; `Sites.FullControl.All`; super user; Restricted SharePoint Search | Mục 6.1, 6.3. Ngoại lệ duy nhất: quyền **ủy quyền** `Files.Read.All` làm dự phòng cho token, cần ký duyệt |
| Copilot, SharePoint agents, Copilot Studio, Retrieval API, Azure AI Search, Graph Search làm bộ truy xuất | Mục 6.6 |
| OpenSearch, ParadeDB, VectorChord-bm25, MinIO, Vault, immudb, Zitadel, Open WebUI, Arize Phoenix, LiteLLM, TGI, Spark, NeMo Guardrails | Không phù hợp về license hoặc kiến trúc |

### 6.9 License và chi phí ngoài E5

| Hạng mục | Cần không | Ghi chú |
|---|---|---|
| Workload ID Premium | Nên mua; bắt buộc nếu acl-reader dùng fullcontrol | Khoảng 3 USD mỗi identity mỗi tháng, cho 6 service principal; có dùng thử 90 ngày |
| Azure subscription liên kết để tính phí khách theo MAU | Bắt buộc | |
| E5 cho mọi người dùng Copilot có quyền vào Data Room | Bắt buộc nếu muốn chặn Copilot | Hoặc add-on E5 IPG |
| SMS cho MFA của khách | Tránh | |
| Entra ID Governance add-on, SAM Plan 1, lưu nhật ký 10 năm, Multi-Geo, Advanced Data Residency | Không | |

### 6.10 Tính sẵn sàng

AI ngừng hoạt động thì nhà đầu tư vẫn dùng SharePoint bình thường. Tuy vậy, mọi kiểm soát đều đóng khi có lỗi, nên một điểm hỏng đơn có thể làm tắt toàn bộ AI.

- **Mục tiêu:**
  - SLO 99,5% trong khung giờ hỗ trợ (giờ Việt Nam cộng giờ của các nhóm nhà đầu tư, BOD chốt);
  - RTO 4 giờ;
  - RPO 15 phút.
- **Hạ tầng:**
  - Reverse proxy và forward proxy chạy hai node.
  - OpenBao chạy cụm Raft 3 node, có người giữ khóa unseal được ghi danh, có backup đã thử khôi phục.
  - PostgreSQL chạy một primary và một standby (Patroni).
  - GPU/vLLM có N+1; nếu không, khi lỗi hệ thống báo "tạm ngừng" bằng câu trung tính.
- **Certificate:** mỗi app đăng ký sẵn một certificate dự phòng, để mất khóa hay certificate hết hạn không làm ngừng hệ thống.

## 7. Đo lường và cổng go-live

**Định nghĩa "đúng".** Một câu trả lời đúng khi đồng thời:

- đúng sự thật;
- đủ so với danh sách ý bắt buộc của đáp án;
- trích từ phiên bản hiện hành của file.

**Định nghĩa "99%".** Cổng tính trên các câu AI trả lời: độ đúng ≥ 99% với độ tin cậy 95% một phía. Tức là trong ≥ 500 câu đã trả lời được phép tối đa 1 lỗi; 2 lỗi trở lên là trượt, quy tắc này được ghi lại trước khi chạy. Kèm theo:

- từ chối nhầm ≤ 15%;
- độ đúng tính cả câu từ chối được báo cáo riêng cho BOD.

**Điều kiện chạy.** Bộ giữ riêng chạy trên:

- kho production;
- pipeline production (cùng converter, OCR, quy tắc loại, trần file, kiểm tra trực tiếp);
- ≥ 3 tài khoản khách có phạm vi khác nhau.

**Phân tầng câu hỏi.** Các loại câu hỏi (tìm tài liệu, tra cứu, bảng, tổng hợp, không có đáp án) được chia theo loại nguồn (PDF gốc, PDF scan, Word, Excel, PowerPoint) và theo kiểu gõ (có dấu, không dấu):

- mỗi tầng ≥ 60 câu đã trả lời;
- tầng nào có ≥ 2 lỗi thì trượt.

**Bộ câu hỏi.** Tập phát triển và tập giữ riêng do hai nhóm khác nhau gán nhãn. Tập giữ riêng chia làm hai phần:

- một phần 100 câu dùng để chạy thử ở tuần 12;
- phần còn lại chỉ dùng cho cổng.

Phần đã dùng thì thay bằng câu mới.

**Mẫu số của "từ chối nhầm"** là các câu có đáp án trong tài liệu **được phép dùng AI**. Ngoài ra lấy mẫu câu hỏi từ toàn bộ phạm vi người hỏi mở được, để đo phần thiếu do tài liệu bị loại.

| Cổng | Cách đo | Ngưỡng |
|---|---|---|
| Rò rỉ chéo | Ma trận quyền tự sinh: ≥ 10 khách thử, cộng tài khoản nhân viên và người duyệt; nhân với thư mục, file, nhóm SharePoint, link người cụ thể, RAC, trạng thái hạn. Từ 3.000 phép thử mỗi lần. Cài chuỗi đánh dấu trong mọi file không được cấp. Cố tình làm sai bản chép quyền. Thay file bằng bản đã biên tập rồi chia sẻ cho nhóm khác. Chạy với cổng thực sự sẽ dùng khi go-live (chế độ chính hoặc dự phòng) | 0 lỗi, kèm kiểm thử xâm nhập độc lập |
| Thu hồi | Gỡ quyền item; gỡ một trong hai nhóm; chuyển nhóm; gỡ khỏi nhóm RAC; offboard nhà đầu tư, nhân viên và cố vấn; nguồn quyền ngừng cập nhật. Không đoạn văn chưa kiểm nào tới trình duyệt | Item: ≤ X giây sau khi SharePoint chặn trên trình duyệt. Nhóm và offboard: ≤ 2 phút. Nguồn ngừng: từ chối câu hỏi trong ≤ 3 phút |
| Phiên bản và `AI_Use` | Thay file; đổi `AI_Use` sang Excluded | Câu hỏi kế tiếp không trích được bản cũ hay file bị loại |
| Bản chép quyền | So với SharePoint trên ≥ 1.000 cặp (người, file) | Thiếu quyền ≤ 1%. Thừa quyền: kiểm tra trực tiếp chặn 100% (chế độ chính) hoặc bằng 0 (chế độ dự phòng) |
| Không can nhiễu | Thêm hoặc bớt tài liệu chỉ B xem được | A nhận cùng nội dung, trích dẫn, thông báo, số file và bậc thời gian; nhánh BM25 cho cùng thứ hạng |
| Câu trả lời đúng | Như định nghĩa trên | ≤ 1 lỗi trên ≥ 500 câu đã trả lời; không tầng nào có ≥ 2 lỗi |
| Độ phủ khi tổng hợp | Tỉ lệ file nguồn của đáp án lọt tới LLM, tính ở trần file đang dùng | ≥ 98% với câu tổng hợp và câu liệt kê |
| Trích dẫn hợp lệ | Câu trích có nguyên văn trong đoạn thuộc file đã qua kiểm tra | 100% |
| Vị trí trích dẫn | Vị trí trích dẫn mở ra đúng chỗ có câu trích trong trình xem SharePoint (mẫu có Word, PowerPoint, Excel) | ≥ 99% |
| Trích dẫn đỡ được ý | Đoạn trích đứng riêng vẫn suy ra được ý | ≥ 99% |
| Con số | Khớp bộ (giá trị, thang, đơn vị, kỳ). Riêng trang scan: so với bản người chép lại từ ảnh trang, ≥ 300 số. Có tầng Excel | 100% |
| Trả lời nhầm | Số câu được trả lời / số câu không có đáp án | ≤ 2%, và bằng 0 với câu chỉ trả lời được từ tài liệu không được cấp |
| Khi bị throttling | Chạy lại một phần bộ giữ riêng dưới tải gây 429 | Cùng độ đúng, hoặc từ chối rõ ràng |
| Tải | Số phiên khách đồng thời ở mức đỉnh dự kiến, có đồng bộ chạy song song, chạy trong giờ làm việc | 0 file bị loại vì 429; p95 thời gian trong ngưỡng chốt ở PoC |
| Injection: hệ thống | Mẫu tấn công trực tiếp và cài trong tài liệu, các biến thể tiếng Việt | 0 mẫu làm lộ dữ liệu hoặc gửi được ra ngoài |
| Injection: bộ phát hiện | Recall trên bộ tấn công giữ riêng (≥ 300 câu, tiếng Việt, không dấu, Anh, trộn, ngôn ngữ khác, có làm rối); báo nhầm trên câu hỏi thật của đợt thử nội bộ và trên bộ câu bẫy | Báo nhầm ≤ 1% thì giữ chế độ chặn, nếu không thì chuyển sang chỉ ghi log. Recall chỉ theo dõi, không chặn go-live (demo: 85% recall, 0,7% báo nhầm trên tập tổng hợp, mục 14) |
| Con số trên trang scan | Tỉ lệ số đọc sai bị gắn cờ "chưa xác nhận"; tỉ lệ số đúng bị gắn cờ nhầm | Bắt ≥ 80%, gắn nhầm ≤ 5%. Số bị gắn cờ không bao giờ hiện mà không có nhãn |
| Hạn mức | Bắn liên tục từ một tài khoản; nhiều tài khoản cùng lúc | Vượt hạn mức trả 429 kèm thời gian chờ; người khác không bị ảnh hưởng |
| Dữ liệu cá nhân | Bộ mẫu chứa CCCD, di động, email, MST, tài khoản công ty | Che 100% định danh cá nhân; không che MST, tài khoản công ty, số liệu |
| Nhãn và Copilot | Độ phủ nhãn trên file Data Room. Tài khoản deal team vừa mở file Data Room thử hỏi Copilot | 100%; Copilot không trả nội dung |
| Độ phủ AI | Tỉ lệ file AI tìm được trên số file người hỏi mở được, theo thư mục | Đạt mục tiêu chủ Data Room đặt |
| Nhật ký | Độ trễ bản lưu on-prem; tỉ lệ lần đọc khớp với nhật ký Purview | < 24 giờ; 100% |
| Neo WORM | Dùng tài khoản quản trị xóa hoặc sửa checkpoint | Bản gốc còn trong Preservation Hold Library; phép kiểm neo phát hiện được |
| Runbook | RB-1 đến RB-7 (mục 10.1) mỗi cái được tập một lần | Đã tập, có biên bản |
| Bản 2: trích trường | Độ chính xác trường quan trọng; độ phủ bản ghi | ≥ 99% với độ tin cậy 95%: ≥ 300 trường không lỗi, hoặc ≥ 500 trường tối đa 1 lỗi |
| Bản 2: đếm | Chạy bằng tài khoản khách, kiểm tra trực tiếp đang bật, có giả lập 429 | Khớp tuyệt đối, hoặc từ chối rõ ràng; không bao giờ trả một tổng thiếu |
| Hiệu quả | 20 việc tra cứu thật, có AI so với thủ công | Giảm từ 50% thời gian trung vị, không giảm độ đúng |
| Pháp lý | Ý kiến bằng văn bản của luật sư | Có trước khi thử nội bộ |

## 8. Lộ trình

Đây là ước lượng của tôi cho đội 4–5 người, cộng một kỹ sư vận hành chuyên trách từ tuần 14.

| Giai đoạn | Tuần | Kết quả |
|---|---|---|
| 0. Pilot tích hợp + PoC | 1–3 | 9 phép thử ở mục 9.1 (xong tuần 1–2); script nạp tối giản cho PoC; PoC độ chính xác trên GPU thuê; cổng BOD |
| 1. Nạp và quyền | 4–8 | Connector, bản chép quyền, tập thu hồi, ngưỡng tươi, nạp, chỉ mục phân vùng. Thiết kế chế độ dự phòng nếu phép thử 3 thất bại |
| 2. Truy vấn | 9–13 | Gateway, kiểm tra trực tiếp, giao diện qua DMZ, L5, nhật ký, lưu nhật ký Purview, neo WORM (policy chưa khóa). Tuần 12: chạy thử ma trận rò rỉ và phần 100 câu của bộ giữ riêng |
| 3a. Kiểm thử | 14–15 | Khóa Preservation Lock rồi thử WORM; ma trận rò rỉ; thu hồi; đo tải; red-team; kiểm thử xâm nhập; chấm bộ giữ riêng; tập runbook |
| 3b. Sửa và kiểm lại | 16–17 | Sửa mọi phát hiện; kiểm thử xâm nhập lại; chạy lại các cổng liên quan |
| 4. Thử nội bộ | 18–19 | Nhân viên và cố vấn dùng với quyền production thật; test rò rỉ theo nhóm chạy hằng ngày |
| 5. Go-live | 20 | Mở đồng thời cho cả nhóm nhà đầu tư; ngày mở gắn với lịch IPO, có khoảng đệm |
| Hypercare | 21–24 | Ca trực có tên (≥ 2 người), khung giờ hỗ trợ theo múi giờ nhà đầu tư, ngừng thay đổi trừ bản vá bảo mật |

**Quy tắc dời lịch:** một phát hiện rò rỉ hay một cổng ở mục 7 trượt thì dời go-live ít nhất 2 tuần. Không mở một phần cho một số nhà đầu tư.

**Phương án nếu cổng độ chính xác trượt.** Nếu các cổng về rò rỉ, trích dẫn, con số và trả lời nhầm đều đạt, có thể mở với `Investor.AI.Summarize` tắt (chỉ tìm và trích nguyên văn), sau khi chạy lại các cổng đó ở chế độ này.

**Dời sang Bản 1.1 hoặc Bản 2:**

- bộ phân loại injection tự tinh chỉnh;
- olmOCR đối chiếu (Bản 1 đưa trang scan nhiều bảng hoặc điểm thấp vào hàng chờ duyệt);
- Gemma 4 12B (dùng model chính chạy ban đêm);
- Langfuse;
- tính năng tổng hợp (đặt sau cờ, tắt nếu BOD chưa duyệt trước tuần 6).

**Bản 2 (8–10 tuần, sau hypercare):** kho bản ghi, câu hỏi đếm (mục 4.5), liên kết chéo bằng khóa, bảng trong scan có người duyệt.

**Thời gian của người nghiệp vụ.** Khoảng 50 ngày công, gồm 150 câu phát triển, ≥ 500 câu giữ riêng có hai người chấm, 1.000 ô số chép lại, chấm thử hai model và 20 việc tra cứu bấm giờ. Mốc:

- tập phát triển xong tuần 3;
- tập giữ riêng đóng băng tuần 10, kỹ sư không được xem.

## 9. Pilot tích hợp và PoC

### 9.1 Chín phép thử tích hợp (tuần 1–2): cổng đi tiếp

| # | Phép thử | Nếu thất bại |
|---|---|---|
| 1 | Chỉ với `Sites.Selected` read: drive delta, `/versions`, `/content`, `?format=pdf` (ghi lại host chuyển hướng); trường list item; đổi riêng `AI_Use` có hiện trong delta không; quyền cấp ở mức site có tới được thư mục có quyền riêng không | `Sites.Selected` với vai trò cao hơn, chỉ trên đúng site (code vẫn chỉ đọc, có cảnh báo khi ghi). Riêng `format=pdf` thất bại thì dùng LibreOffice |
| 2 | acl-reader: thử vai trò thấp nhất trước fullcontrol. Đọc toàn bộ quyền của item. REST (role assignment, nhóm SharePoint, getchanges) với token cho `<tenant>.sharepoint.com` | Đối soát đầy đủ thường xuyên hơn. Nếu vẫn không đủ thì dừng và trình BOD/quản trị bảo mật. **Không xin `Sites.FullControl.All`** |
| 3 | Trước hết xác nhận dataroom-ai-api đã được cấp quyền site. Sau đó chạy OBO, tách (a) đọc metadata driveItem và (b) `/content`; cho khách OTP-B2B, khách Entra và nhân viên; trên thiết bị được quản lý và không được quản lý; site bật AllowLimitedAccess và RAC; có cả khách chưa từng vào SharePoint. **Đo X**: độ trễ từ lúc gỡ quyền item tới lúc AI chặn, so với trình duyệt | **Chuyển sang chế độ dự phòng (mục 3.6).** Coi là có khả năng xảy ra |
| 4 | Stream SSE qua reverse proxy tại DMZ, câu trả lời dài hơn 3 phút | Chỉnh proxy |
| 5 | File có nhãn mã hóa: tải về, `format=pdf`, kiểm byte | Siết bước kiểm byte |
| 6 | Khách trên thiết bị không được quản lý mở PDF scan dưới chế độ giới hạn | Đổi LimitedAccessFileType, hoặc chỉ hiển thị câu trích và vị trí |
| 7 | Lần đọc của app-only có hiện trong nhật ký Purview với app ID lọc được không | Đối chiếu theo thời gian và item |
| 8 | Throttling bằng tài khoản khách, trong giờ làm việc; đọc số license của tenant để biết bậc hạn mức | Hạ trần file; đặt giới hạn theo người |
| 9 | gVisor (runsc) với PaddleOCR-VL và bge-m3 trên đúng loại card và driver sẽ mua | Dùng Kata + VFIO |

### 9.2 PoC độ chính xác (3 tuần)

Tài liệu thử lấy bằng một script nạp tối giản (delta + tải file) từ site thử. GPU được thuê theo mục 6.7. Ngưỡng đạt và không đạt được ghi lại trước khi chạy.

- **Quy tắc dữ liệu:** không gửi tài liệu IPO thật ra bất kỳ dịch vụ nào ngoài Microsoft 365 và AI core.
- **OCR:**
  - Lấy mẫu từ 300 trang theo lớp: scan có dấu, scan có bảng, chữ ký hoặc viết tay.
  - Người chép lại từ 1.000 ô số làm đáp án.
  - Ngưỡng: ô số khớp ≥ 99,5%; tỉ lệ lỗi ký tự trên chữ có dấu tiếng Việt đặt trước khi chạy.
  - Đặt ngưỡng chất lượng lớp chữ quyết định khi nào phải OCR lại.
- **Bộ câu hỏi nhỏ:** 150 câu, có đủ các tầng loại nguồn.
- **Chọn LLM:** so Gemma 4 31B với Qwen 3.8 27B trên 200 câu. Tiêu chí: trích dẫn đúng, JSON hợp lệ, từ chối đúng.
- **Kho tìm kiếm:**
  - Đường cong độ phủ ở các trần 8, 12, 20, 30 file; chọn trần từ đường cong này.
  - recall@trần, tách theo câu có dấu, không dấu và trộn, và theo trang OCR với trang gốc.
  - Thời gian quét chính xác.
  - Test rò rỉ trên cả hai nhánh.
- **Thử trước cho Bản 2:** một loại hồ sơ, 10 câu đếm; kiểm luồng ở mục 4.5, kể cả trường hợp file của B bị chép thừa quyền.

Thư mục bàn giao: `09_Accuracy_Golden_Set/`, `10_OCR_Bakeoff/`, `11_Legal_Signoff/`, `12_LLM_Bakeoff/`, `13_M365_Integration_Pilot/`.

## 10. Quản trị tự động

- **Cấp và thu hồi quyền:** access package lo phê duyệt, hạn và xóa khách. AI core tự cập nhật bản chép quyền, tập thu hồi và danh sách chặn.
- **Cờ AI:** chủ Data Room gán và cập nhật `AI_Use` bằng script hàng loạt. AI core nạp hoặc xóa theo cờ, đối soát hằng đêm.
- **Thêm site Data Room mới:** chạy script cấp quyền cho cả ba app (content-reader, acl-reader, dataroom-ai-api), thêm site vào cấu hình RAC, thêm vào danh sách site của AI core.
- **Bảng điều khiển (sau RBAC, oid đã ẩn danh hóa):**
  - sổ nạp;
  - file bị loại kèm lý do;
  - độ phủ AI theo thư mục và theo nhóm;
  - tuổi của từng nguồn dữ liệu quyền;
  - drive đang bị cách ly;
  - cảnh báo cấp quyền lạ;
  - độ trễ nhật ký Purview;
  - neo WORM;
  - câu hỏi bị chặn;
  - báo cáo tiếp cận công bằng.
- **Kiểm tra như nhà đầu tư:** ở production, mỗi nhóm có một tài khoản khách thử. Bộ test rò rỉ chạy hằng ngày dưới danh tính đó.
- **Trước mỗi đợt mở cho nhà đầu tư mới:** báo cáo SAM, site access review, độ phủ nhãn, phép thử Copilot, bộ test rò rỉ.
- **Theo dõi thay đổi phía Microsoft:**
  - danh sách endpoint, hằng ngày;
  - Message Center về Graph, SharePoint, Entra và Purview;
  - thông báo bảo mật của các thành phần on-prem.

### 10.1 Runbook

Phải có trước go-live, mỗi runbook được tập một lần trong giai đoạn 3a. Mỗi runbook ghi rõ người chịu trách nhiệm, điều kiện kích hoạt, các bước và cách xác nhận.

- **RB-1 Certificate:**
  - cảnh báo trước hạn 60, 30 và 7 ngày;
  - certificate dự phòng đăng ký sẵn;
  - thời gian xử lý quản trị tenant cam kết.
- **RB-2 Cách ly và đồng bộ lại drive:**
  - thời gian liệt kê lại đo trong pilot;
  - trong lúc chờ hiện thông báo "phạm vi tạm thu hẹp", giống nhau cho mọi nhóm.
- **RB-3 Offboard nhà đầu tư, nhân viên hoặc cố vấn:**
  - gỡ access package hoặc assignment (nhóm nhà đầu tư, `Staff.AI`, `Reviewer`), `revokeSignInSessions`;
  - nhân viên nghỉ việc: tắt tài khoản theo quy trình nhân sự; cố vấn hết hợp đồng: gỡ khỏi ADVISERS;
  - kiểm bằng tài khoản thử (nhà đầu tư) hoặc tra danh sách chặn và tập thu hồi (nhân viên, cố vấn);
  - xóa lịch sử chat theo chính sách lưu.
- **RB-4 Nghi rò rỉ:**
  - kỹ sư trực bật công tắc toàn hệ thống, không cần xin duyệt;
  - báo trưởng deal team và luật sư trong vòng 1 giờ;
  - đóng băng chuỗi nhật ký, export nhật ký Purview;
  - chạy lại ma trận rò rỉ trước khi bật lại.
- **RB-5 Sự cố hoặc throttling phía Microsoft:**
  - hiện câu "tạm ngừng" trung tính;
  - theo dõi Service Health.
- **RB-6 Nhật ký bị gián đoạn:** lấy lại trong cửa sổ 7 ngày của blob; neo WORM bị trễ.
- **RB-7 GPU hoặc vLLM lỗi:** quay về phiên bản model trước.

## 11. Pháp lý và IPO

Đây là danh sách điểm cần luật sư xác nhận, không phải ý kiến pháp lý.

- **Nơi lưu dữ liệu.** Theo trang data location của Microsoft cập nhật 03/09/2026:
  - Việt Nam không phải Local Region và không thuộc diện Advanced Data Residency.
  - Dữ liệu SharePoint của tenant Việt Nam được suy ra là nằm ở vùng Asia Pacific. Microsoft không cam kết vị trí cụ thể, và vị trí có thể đổi.
  - Thẻ Data Location là bằng chứng duy nhất.

  Như vậy **tài liệu gốc vốn đã nằm ngoài Việt Nam**. AI core giữ dữ liệu phái sinh, câu hỏi và nhật ký ở Việt Nam.
- **Các văn bản về dữ liệu:** Luật Bảo vệ dữ liệu cá nhân 91/2025 cùng Nghị định 356/2025, Nghị định 165/2025, Nghị định 53/2022. Cần xác nhận cả việc lưu Data Room trên Microsoft 365 hiện nay lẫn việc dùng AI.
- **Công bố thông tin.** Chưa tìm được văn bản áp dụng quy tắc đối xử công bằng vào câu trả lời do AI tổng hợp. Cách mở đồng thời và báo cáo tiếp cận công bằng đã nằm trong kế hoạch.
- **Câu trích từ tài liệu chỉ-xem.** Chủ Data Room và luật sư cần chấp nhận việc AI hiển thị câu trích. Câu trích từ trang scan được ghi rõ là văn bản nhận dạng.
- **Bảng thời hạn lưu**, cho từng loại dữ liệu:
  - câu hỏi;
  - câu trả lời;
  - nhật ký on-prem (là bằng chứng duy nhất sau 180 ngày cho khách và app);
  - lịch sử chat;
  - site neo. Thời hạn của site neo phải chốt **trước** khi khóa Preservation Lock, vì sau đó không rút ngắn được.
- **Điều khoản sử dụng (NDA)** qua Conditional Access, có phần về AI.
- **Thông báo trên mỗi câu trả lời:** đây là công cụ hỗ trợ; tài liệu gốc và bản cáo bạch là căn cứ.
- **Trang "AI trong Data Room này":**
  - AI chỉ đọc tài liệu người xem mở được và đã được cho phép dùng AI; một số tài liệu xem được trên SharePoint có thể không nằm trong phạm vi AI;
  - độ phủ của riêng người xem, tính hằng đêm;
  - cách trích dẫn;
  - không dùng để huấn luyện;
  - đặt on-prem tại Việt Nam;
  - ghi log gì.
- **Hợp đồng với bên thứ ba:** tài liệu không được phép cho AI xử lý thì đặt `Excluded`.

## 12. Quyết định cần BOD chốt

1. **AI có được tổng hợp câu trả lời cho nhà đầu tư không**, hay chỉ tìm và trích nguyên văn. Quyết định này bật hoặc tắt `Investor.AI.Summarize`. Cần trước tuần 6.
2. **LLM cloud hay on-prem.** Hiện là on-prem. Cần tính đến việc tài liệu gốc vốn đã nằm ở vùng Asia Pacific của Microsoft.
3. **Hạn mức ngân sách GPU** ở tuần 0; cấu hình cụ thể chốt ở tuần 3 (mục 6.7).
4. **Các khoản phát sinh nhỏ ngoài E5** (mục 6.9).
5. **Lộ trình khoảng 20 tuần cho Bản 1** cộng 4 tuần hypercare, và quy tắc dời lịch ở mục 8.
6. **Thay "chính xác 100%", "bảo mật tuyệt đối" và "mọi loại file"** bằng câu: *"Trên các câu AI trả lời, độ đúng ≥ 99% với độ tin cậy 95%; AI từ chối nhầm không quá 15%; không có rò rỉ trong ma trận kiểm thử và kiểm thử xâm nhập độc lập"*, cùng các cổng ở mục 7.

## 13. Rủi ro còn mở

- **Phép thử 3.** Tài liệu Microsoft cho thấy lệnh gọi Graph ủy quyền của khách từ thiết bị không được quản lý có thể bị chặn. Khi đó phải dùng chế độ dự phòng, với năng lực thấp hơn (khoảng 9 câu/phút) và bắt buộc tách site theo nhóm.
- **OTP SharePoint kiểu cũ hết hiệu lực trước 31/10/2026**, giữa lúc pilot. Nhà đầu tư chưa được chuyển sang khách B2B sẽ mất quyền truy cập.
- **`Sites.Selected` với các API đang dùng** chưa được Microsoft ghi trong tài liệu (phép thử 1–2).
- **Độ trễ nội bộ khi SharePoint gỡ quyền item** chưa được đo (X trong phép thử 3).
- **Hạn mức throttling cho khách**, và mức dùng của các app khác chia chung hạn mức tenant.
- **Trình xem SharePoint** lỗi với PDF dưới chế độ giới hạn (phép thử 6).
- **Microsoft đổi nền tảng:** bắt buộc tích hợp B2B; ACS ngừng; RCD được mô tả là tạm thời; Restricted SharePoint Search ngừng hẳn ngày 31/01/2027.
- **Thẻ Data Location chưa được xem.**
- **License Copilot cho khách:** lý do lấy từ Microsoft Q&A, chưa thấy trong điều khoản sản phẩm.
- **Phụ thuộc người ngoài đội:** quản trị tenant, chủ Data Room, BOD, luật sư, người nghiệp vụ (mục 2.2).
- **RLS và chỉ mục toàn văn.** Dưới RLS, Postgres không dùng được chỉ mục cho toán tử không LEAKPROOF. Demo đã gặp với GIN `@@`. Cần kiểm lại với pg_textsearch, hoặc dùng hàm SECURITY DEFINER chỉ trả id như demo (mục 4.4).
- **OCR chữ viết tay** chỉ đúng khoảng 65% con số. Trường hợp cả hai bộ đọc cùng sai một kiểu vẫn lọt khoảng 20%. Trang có chữ viết tay hoặc số bị gắn cờ phải qua người duyệt (mục 4.2).
- **Bộ phát hiện injection** mới được đo trên tập tổng hợp. Recall giảm từ 97% (kiểm định chéo) xuống 78–85% khi gặp mẫu câu mới. Cần red-team thật và huấn luyện lại.
- **Các rủi ro kỹ thuật khác:**
  - không có benchmark trên hồ sơ doanh nghiệp tiếng Việt;
  - tốc độ vá các thành phần có lỗi bảo mật năm 2026;
  - Prefect đã mua Dagster Labs;
  - mã nguồn ITLR chưa được xem.

## 14. Kết quả bản demo local (07/10/2026)

**Bản demo.** Bản demo chạy trên một MacBook M3 Pro 18 GB (`~/Projects/dataroom-ai-demo`). SharePoint và Entra là bản giả lập, giữ đúng độ trễ nhóm, RAC, link và phiên bản. Model:
- LLM: qwen2.5:7b, thay cho Gemma 4 31B;
- embedding và rerank: bge-m3, bge-reranker-v2-m3;
- NLI: mDeBERTa;
- OCR: PaddleOCR-VL-1.6 qua MLX.

Dữ liệu gồm 540 tài liệu đủ 11 định dạng, có 40 bản scan khó. Số đo dưới đây là số trên dữ liệu tổng hợp, chưa phải cổng go-live.

| Hạng mục | Kết quả |
|---|---|
| Rò rỉ chéo | 0 trên 12.500 lần dò; 0 file bị thiếu so với SharePoint |
| Hỏi đáp end-to-end | Đúng 10/11 câu với người được phép; 8/8 không lộ với người không được phép |
| OCR, 52 trang scan khó (12 kiểu lỗi, 2.037 con số) | Số đúng tăng từ 95,9% lên **98,4%** khi có bước làm sạch. Xoay 90°: 79% → 100%. Độ phân giải thấp: 51% → 93%. Viết tay: 65%. Thêm ~2,3 s/trang |
| Đối chiếu số OCR | Bắt 16/20 số đọc sai (80%); gắn nhầm 3,7% số đúng |
| Tìm kiếm 1 triệu đoạn, Postgres x86 qua Rosetta | Nạp 23 phút, 10 GB. Tìm p50 160–535 ms, p95 ≤ 1,13 s. Recall vector 0,93–0,96, có dung sai |
| Bộ phát hiện injection, tập giữ riêng 300 tấn công + 150 câu hợp lệ | Phát hiện **85,3%**, chặn nhầm **0,7%** (câu bẫy 0/82). Chạy dưới 1 ms, câu dài thêm khoảng 0,1 s. Điểm vận hành được chọn sau khi đã xem tập thử, nên số này lạc quan |
| Injection end-to-end, tắt lớp L2, LLM thật | **0/30 rò rỉ**; 25 câu bị lớp sau từ chối; 5 câu trả lời chỉ từ tài liệu được phép, đã kiểm chứng |
| Thời gian một câu trả lời trên laptop | 16–31 s. Phần lớn là LLM 10–16 s; 4 cổng quyền chỉ khoảng 50 ms |

**Điểm demo khác production** (không mang lên production):
- Demo cache ảnh trang scan đã làm sạch trên đĩa để cắt ảnh trích dẫn. Production chỉ lưu tọa độ, ảnh dựng trong bộ nhớ theo mục 4.4.
- Demo đăng nhập bằng mật khẩu và token HMAC. Production dùng MSAL với Entra, Conditional Access và MFA.
- Demo có trang quản trị quyền ngay trong ứng dụng. Production cấu hình quyền trên SharePoint, Entra và access package (mục 2).
- Hạn mức để trong bộ nhớ một process; parser chưa chạy trong gVisor; chưa có ClamAV, YARA.

## Phụ lục A. Đối chiếu với kế hoạch bảo mật

### A.1 Mười hai domain của kế hoạch bảo mật

Danh sách gốc ở mục 5 của kế hoạch bảo mật chỉ có 11 mục và thiếu D08. Bản này đặt D08 là chuỗi cung ứng.

| Domain | Nội dung | Trong bản này |
|---|---|---|
| D01 Identity | Định danh, phiên | 3.1, 6.1 |
| D02 Authorization | Phân quyền, thu hồi | 3.3–3.6 |
| D03 Tenant Isolation | Cô lập giữa nhà đầu tư | 3.3, 5, 6.1 (RAC), 6.5 (phân vùng) |
| D04 Document/Data | Kiểm duyệt file, nội dung ẩn | 4.2, 6.3 |
| D05 Prompt/Injection | Injection trực tiếp và gián tiếp | 4.4, 6.5 |
| D06 RAG/Vector | Truy xuất trái phép, rò qua cache, rò qua phiên bản | 3.3, 4.2 (`is_current`), 5 |
| D07 Output | Lộ dữ liệu, lách qua tóm tắt | 4.4 (L5), 5 |
| D08 Supply chain (bổ sung) | Gói phần mềm, trọng số model | 5 |
| D09 Audit | Nhật ký riêng cho AI | 6.4 |
| D10 Infrastructure | API, bí mật | 4.1, 6.2, 6.10 |
| D11 Privacy/Compliance | Nơi lưu dữ liệu | 11 |
| D12 Availability | Từ chối dịch vụ, cạn token | 6.2 (ngân sách, hàng đợi), 6.10 |

### A.2 Giữ nguyên

| Mục của kế hoạch bảo mật | Ghi chú |
|---|---|
| §2 Nguyên tắc số 1: phân quyền trước truy xuất | Thêm bước kiểm tra trực tiếp với SharePoint |
| §2 Ba quyền AI | Ánh xạ ở mục 3.2 |
| §3 Kiến trúc 5 lớp | Nhãn L1–L5 trong pipeline |
| §6 Prompt với `<untrusted_document>` | Mở rộng cho văn bản OCR, ghi chú slide, sheet ẩn, tên file, kết quả công cụ |
| §4 Red-team đa ngôn ngữ, audit log riêng cho AI | Thêm tập lành tính |
| §2 Câu "không có an toàn tuyệt đối" | Đưa lên thành quyết định của BOD (mục 12) |

### A.3 Thay hoặc sửa

| Mục của kế hoạch bảo mật | Thay bằng |
|---|---|
| §3 Lớp 1: SSO, MFA, IAM | Khách Entra B2B, Conditional Access, entitlement management |
| §9 Tuần 6: nối API phân quyền | Graph và SharePoint REST với `Sites.Selected`; bốn cổng quyền |
| §9 Tuần 7: tự gán quyền AI | App role qua access package; `AI_Use` mặc định là Excluded |
| §7 Textract, Tesseract, LlamaParse, PyMuPDF, Unstructured | PaddleOCR-VL, Docling, pypdfium2, openpyxl |
| §4, §9 LLM Guard, Llama Guard; §4 NeMo Guardrails | Ngăn injection bằng cấu trúc; chuỗi kiểm soát trong Gateway; bộ phát hiện tự xây trên bge-m3 (Prompt Guard 2 bị khóa và không có tiếng Việt; LLM Guard chỉ có tiếng Anh) |
| §2 Lớp 2: lọc PII trước khi đưa vào hệ thống | Che định danh cá nhân trong câu hỏi, câu trả lời và nhật ký; giữ số liệu doanh nghiệp |
| §7 Excel sang Markdown | Đọc trực tiếp xlsx, giữ đơn vị và kỳ |
| §7 `allowed_investors` trên từng chunk | Bản chép quyền + kiểm tra trực tiếp + tập thu hồi |
| §8 FAISS, Dagster/Spark | PostgreSQL phân vùng; Dagster, bỏ Spark |
| §8, §9 Proxy tới OpenAI | LLM on-prem (D11, mục 11) |
| §9 Tuần 11: beta cho nhà đầu tư chiến lược | Thử nội bộ với nhân viên và cố vấn ở tuần 18–19; mở đồng thời |
| §9 Tuần 12: "chính xác 100%" | Định nghĩa và cổng ở mục 7 |
| §4 Ngày 4: đếm mẫu bị chặn | Đo trên tập lành tính |
