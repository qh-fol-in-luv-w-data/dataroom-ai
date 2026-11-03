# Tăng độ chính xác trên mocktest CT Group: đã làm gì, kết quả, cách chạy tiếp trên server

- Nhánh: `ctg-dataroom`.
- Thời gian: 30/10 – 04/11/2026.
- Phạm vi tài liệu này: chỉ có số đếm và mã câu (MTxxx), không chép nội dung tài liệu CT Group.
- Bộ câu, kết quả từng lượt và dữ liệu nằm trong `data/ctg/` (không commit). Cách chuyển sang server: xem mục 6.

## 1. Bối cảnh

Hệ thống là RAG on-prem:
- Ứng dụng: FastAPI, Postgres/pgvector (có RLS).
- Model: Ollama chạy `qwen3:4b` và `bge-m3`; reranker `bge-reranker-v2-m3`; NLI mDeBERTa.
- Kiểm chứng tất định trong `dr/core/verify.py`.

Mocktest gồm 481 câu trên khoảng 5.300 tài liệu thật:
- 350 câu sự kiện, chia theo loại tài liệu: văn bản 90, scan/ảnh OCR 110, bảng Excel 70, bảng 40, slide 40.
- 81 câu phân quyền: hỏi bằng tài khoản không được đọc tài liệu nguồn.
- 50 câu ngoài phạm vi: hỏi về dự án hoặc người không có trong data room.

Đáp án mẫu do model sinh tự động, **chưa có người duyệt**.

Cách chấm (`scripts/ctg_mocktest_eval.py`):
- **Đúng:** câu trả lời chứa đủ các con số của đáp án mẫu. So theo giá trị: 06 = 6; 1,4 tỷ = 1.400.000.000.
- **Lộ:** câu phân quyền mà câu trả lời chứa đáp án.
- **Bịa:** câu ngoài phạm vi mà hệ thống vẫn có câu trả lời.

**Tập sạch** được báo cáo RIÊNG, tập gốc giữ nguyên. Tập sạch bỏ 22 câu đề lỗi:
- 9 câu `gold_bad` (đáp án mẫu không có trong file nguồn): MT010 MT023 MT039 MT064 MT248 MT302 MT314 MT315 MT316.
- 13 câu `leaky` (câu hỏi đã chứa sẵn đáp án): MT007 MT054 MT166 MT179 MT186 MT201 MT233 MT234 MT240 MT245 MT261 MT282 MT284.
- MT357 (câu phân quyền bị chấm "lộ") là báo động nhầm: số liệu đó cũng có trong tài liệu người hỏi được đọc, đã xác nhận khi so theo giá trị.

## 2. Kết quả các lượt đầy đủ (481 câu)

| Lượt | Cấu hình | Đúng /350 | Sai | Từ chối | Tập sạch /328 | Câu nêu tên tài liệu /104 | Đúng và trích đúng file nguồn | Ngoài phạm vi vẫn trả lời /50 | Lộ thật | Giây/câu |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen3-binding (gốc) | 8979b92 | 170 (49%) | 104 | 76 | 160 (49%) | 52 | 80 | 30 | 0 | 20,6 |
| qwen3-fix1 | 238e740 | 222 (63%) | 86 | 42 | 213 (65%) | 69 | 104 | 3 | 0 | 20,3 |
| qwen3-fix2 | f2828e8 | 233 (67%) | 78 | 39 | 223 (68%) | 81 | 119 | 4 | 0 | 20,7 |
| **qwen3-fix3a** | 6baba2c + `DR_LLM_FALLBACK=qwen3:8b DR_EXPAND_TOP_FILE=20` | **250 (71%)** | 90 | 10 | **238 (73%)** | 83 | 130 | 9 | 0 | 22,9 |
| qwen3-fix3b (**dở dang, 194/481 câu**) | 05fd291 + `DR_LLM=qwen3:8b DR_EXPAND_TOP_FILE=20` | 147/194 câu fact (cùng các câu, lượt A: 147) | 43 (A: 44) | 4 (A: 3) | — | — | — | — | — | 33,5 (A trên cùng câu: 20,5) |

Đọc bảng:
- **fix3a là cấu hình tốt nhất đã đo đủ.** So với fix2: được 21 câu, mất 4 (MT040 MT080 MT177 MT192).
- Đánh đổi của fix3a: khi 4b không trả lời được, model 8b dự phòng trả lời thay. Số câu đúng tăng (+17), nhưng số câu trả lời SAI cũng tăng (78 → 90) thay vì từ chối, và câu ngoài phạm vi vẫn trả lời tăng 4 → 9.
  - Commit ce2520a (luật tên riêng, mục 3) được làm sau lượt này để sửa vấn đề đó, nhưng **chưa chạy lượt đầy đủ** để xác nhận.
  - Ước tính offline trên dữ liệu fix3a: câu ngoài phạm vi vẫn trả lời 9 → 0, 7 câu sai chuyển thành từ chối, mất 1 câu đúng.
- fix3b (8b làm model chính) đến câu 194 vẫn ngang fix3a nhưng chậm hơn 1,6 lần. Chưa thấy lý do để dùng 8b làm model chính.
- Theo loại tài liệu (fix2 → fix3a):
  - bảng: 70% → 72%
  - bảng Excel: 60% → 66%
  - scan/OCR: 69% → 75%
  - slide: 52% → 60%
  - văn bản: 73% → 77%
- Có sự cố trong lượt fix1: máy ngủ giữa chừng, nên 121 câu bị cổng 4 từ chối an toàn (nguồn quyền quá hạn). Các câu này đã được chạy lại (xem `run-qwen3-fix1/rerun-ids.txt`). Từ đó, mọi lượt đều chạy dưới `caffeinate`.

## 3. Các thay đổi trong code (commit cục bộ, theo thứ tự)

Mỗi thay đổi có unit test hai chiều. Lần chạy gần nhất: **285 test xanh** (ban đầu 242).

| Commit | Thay đổi | Bằng chứng |
|---|---|---|
| 94f6f2f | verify: luật "mã viết hoa" chỉ bắt mã thật (bỏ TNHH/TM/DV, chữ hoa không dấu từ tên file, gạch cuối); so khớp cả tên file/đường dẫn của passage; mã có gạch nối (CTG-01) nay được so | 37/60 câu bị loại nhầm thành đúng |
| da4769a | pii: che SĐT theo ngữ cảnh. Số của tổ chức (hotline, chi nhánh, công ty…) giữ nguyên; số cá nhân và số không có ngữ cảnh vẫn che | 9/20 thành đúng; 5 câu hỏi SĐT cá nhân vẫn che theo chính sách. **Cần pháp chế CT Group duyệt trước khi lên production** (Luật 91/2025/QH15, NĐ 356/2025/NĐ-CP; nguồn thứ cấp, chưa đối chiếu Công báo) |
| b8e1b2e | verify: loại claim chỉ lặp lại câu hỏi; thêm một dòng vào prompt | |
| 6d4dd8a, 238e740 | rút gọn câu: giữ thêm ≤4 câu (câu liền kề, câu có mã/số của câu hỏi, câu tốt nhất mỗi passage); dòng bảng dài được cắt quanh từ khóa câu hỏi | đáp án còn trong câu dài: 49 → 55/66 |
| a019ad6 | xếp hạng: bản cũ trong nhóm file trùng tên ×0,9 | |
| b0146d5 | lọc đúng trọng tâm: tài liệu được trích phải chứa ≥70% từ khóa câu hỏi (`DR_RELEVANCE_EVIDENCE`) | ngoài phạm vi vẫn trả lời: 30 → 3 |
| bb5af45, d3e8154, 7e978e2, 514f971 | script mocktest: build (đáp án phải `holds()` trong nguồn, perm so theo giá trị), eval (tập sạch, `--ids`, `--only`, `--record-relevance`, `--report-only`), diagnose, compare, A/B, dò số | |
| 90957a5 | **tìm theo tên tài liệu**: câu "Theo tài liệu “…”" trước đây bị `core_question()` cắt mất tên tài liệu; nay chỉ đọc file trùng tên (có RLS) | câu nêu tên tài liệu: 69 → 81/104 |
| 23d1127 | khi mọi claim chỉ lặp câu hỏi: hỏi lại model một lần, kèm lời nhắc | |
| f2828e8 | cờ `DR_THINK` (chế độ suy luận của qwen3), **mặc định tắt** | 1/11 câu cải thiện, 146 s/câu so với 26 s |
| 28caede | cờ `DR_EXPAND_TOP_FILE`: thêm tối đa N đoạn của file đứng đầu vào bước chọn câu | A/B: 38 so với 33 /121; không mất câu đúng |
| 6baba2c | verify: '05' và '5' là cùng một số (số 0 đứng đầu) | 3/11 số bị loại vì "không khớp" |
| 05fd291 | cờ `DR_BM25_CANDIDATES` (mặc định 1.500 như cũ): BM25 chỉ lấy ứng viên từ vài từ hiếm nhất của câu hỏi, nên file nguồn có thể bị loại từ đầu | file nguồn trong top 40 của tìm kiếm lai (BM25 + vector): 247 → 260/350 ở mức 3.000. **Chưa chạy lượt đầy đủ** |
| ce2520a | lọc đúng trọng tâm: câu hỏi nêu tên riêng (chữ viết hoa) phải được trả lời từ một tài liệu chứa ≥80% các từ của tên đó (`DR_RELEVANCE_NAMES`) | offline trên fix3a: ngoài phạm vi vẫn trả lời 9 → 0, câu đúng giữ 249/250. **Chưa chạy lượt đầy đủ** |

Lưu ý: các ngưỡng 0,7 (`DR_RELEVANCE_EVIDENCE`) và 0,8 (`DR_RELEVANCE_NAMES`) được hiệu chỉnh trên chính bộ test này, nên có rủi ro quá khớp. Cần một bộ câu khác để xác nhận.

## 4. Thí nghiệm trên tập con 121 câu

Tập con `data/ctg/mocktest/subset-8b.txt` gồm 91 câu chưa đạt ở fix2 và 30 câu đang đúng.

| Cấu hình | Đúng /121 | Kết luận |
|---|---|---|
| fix2 (tham chiếu, 4b) | 30 | |
| 4b chạy lại | 33 | nhiễu khoảng ±3 |
| `DR_LLM=qwen3:8b` | 50 | +10 câu chọn sai số, +10 câu bị kiểm chứng loại, +3 câu lặp câu hỏi. Trên 100 câu đúng khác: giữ 97/100 (mất ≈4,6%). 36,5 s/câu |
| `DR_LLM_FALLBACK=qwen3:8b` | 41 | +10 câu bị kiểm chứng loại, không mất câu đúng; 26,5 s/câu |
| `DR_EXPAND_TOP_FILE=20` | 38 | không mất câu đúng; +1,4 s/câu |
| `DR_FEWSHOT=1` | 34 | ≈ mức nền, không dùng |
| `DR_DOCTYPE=1` | ≈ nền | không dùng |
| `DR_MAX_PASSAGES=8` (A/B 80 câu) | 29 so với 29 | không dùng |
| `DR_THINK=fact,multi,table` (15 câu) | 1/11 câu sai số thành đúng | quá chậm, không dùng |

Đã thử nhưng bỏ: tiêu chí tự động "câu hỏi mơ hồ". Nó gắn cờ 145 câu, trong đó 87 câu hệ thống đang trả lời đúng, nên không phân biệt được. Không dùng nó để loại câu nào.

## 5. Những gì còn sai (chẩn đoán fix2: 122 câu chưa đạt)

| Nhóm | Số câu | Nhận định |
|---|---|---|
| wrong_claim | 35 | Đoạn đúng đã nằm trong đầu vào của model, nhưng model lấy số từ file khác. Trong 31 câu như vậy, 27 câu có file model trích khớp câu hỏi ngang hoặc hơn file nguồn. **Giả thuyết: câu hỏi sinh tự động không nói rõ tài liệu nào. Cần người duyệt.** 8b sửa được khoảng 1/3 nhóm này |
| verify_dropped | 23 | Gồm: lặp câu hỏi, số không khớp câu trích, mã thật (HMS, XLNT) không có trong passage. 8b (chính hoặc dự phòng) sửa được khoảng 10 câu |
| ranked_out | 11 | Phần lớn đã chọn đúng file nhưng đoạn chứa đáp án xếp thấp hơn |
| pii_masked | 11 | 5 câu hỏi SĐT cá nhân: che là đúng chính sách. 6 câu không có ngữ cảnh: che mặc định |
| gold_bad | 9 | Lỗi của bộ test |
| echo / focus_cut / not_retrieved | 9 / 8 / 5 | |

Trần thực tế: 22 câu đề lỗi và 5 câu SĐT cá nhân không thể tính là đúng, nên tối đa khoảng 323/350.

## 6. Chạy tiếp trên server

### 6.1 Chuyển code và dữ liệu

- **Code:** dùng git bundle của nhánh `ctg-dataroom`, như runbook `docs/BENCHMARK_SERVER.md` (server không vào được GitLab nội bộ). Ở máy có mạng nội bộ thì clone từ GitLab nội bộ.
  - **Không push nhánh này lên GitHub:** repo `qh-fol-in-luv-w-data/dataroom-ai` đang public, mà nhánh chứa cấu hình, prompt và thông tin vận hành của CT Group.

  ```bash
  git bundle create dataroom.bundle ctg-dataroom      # trên máy có code
  git clone -b ctg-dataroom dataroom.bundle dataroom  # trên server
  ```

- **Dữ liệu:** không có trong git. Người vận hành chuyển qua kênh đã phê duyệt:
  - dump Postgres `ctg_dataroom.dump` và `ctg_tenant.tgz`, theo runbook mục 1 và mục 6;
  - thư mục `data/ctg/mocktest/`: bộ câu `mocktest_500.jsonl`, các thư mục `run-*` (kết quả để so sánh), các file tập con `subset-*.txt`.

  Đây là dữ liệu MẬT, không tải lên dịch vụ ngoài.

### 6.2 Cài đặt

Làm theo `docs/BENCHMARK_SERVER.md` các mục 2–7. Điểm khác so với runbook:
- **Model Ollama cần:** `bge-m3`, `qwen3:4b`, `qwen3:8b` (thêm `qwen3:14b` nếu GPU ≥ 16 GB để thử, xem 6.4).
- **Biến môi trường:** dùng `DR_DATA=data/ctg`, `DR_PGDATA=<ổ lớn>/pgdata`, `DR_PG_PORT=55433`, `DR_PG_BIN=$(pg_config --bindir)`.
- **Mỗi lần chỉ chạy một lượt** (các lượt dùng chung luồng quyền và Ollama).
- Dùng `tmux` hoặc `nohup`.
- Máy chủ không được ngủ hoặc tạm dừng giữa lượt. Nếu xảy ra, các câu sẽ bị từ chối "tạm ngừng"; khi đó xoá các dòng đó khỏi `results.jsonl` và chạy lại cùng tag.

### 6.3 Lệnh

```bash
source bench.env
# lượt đầy đủ với cấu hình đề xuất (mục 6.4); --tag mới; chạy lại đúng lệnh sẽ tiếp tục từ câu chưa có
DR_LLM_FALLBACK=qwen3:8b DR_EXPAND_TOP_FILE=20 DR_BM25_CANDIDATES=3000 \
  .venv/bin/python -u scripts/ctg_mocktest_eval.py --tag qwen3-fix4 2>&1 | tee data/ctg/mocktest/fix4.log
# so sánh với lượt trước, theo loại tài liệu, tập sạch, nhóm lỗi, perm, oos, thời gian
.venv/bin/python scripts/ctg_mocktest_compare.py --before qwen3-fix3a --after qwen3-fix4
# chẩn đoán các câu chưa đạt (ghi run-<tag>/diagnose.jsonl, chỉ in id/nhóm)
.venv/bin/python scripts/ctg_mocktest_diagnose.py --tag qwen3-fix4
# thí nghiệm trên tập con, rồi bảng A/B
DR_LLM=qwen3:14b .venv/bin/python scripts/ctg_mocktest_eval.py --tag sub-14b --ids data/ctg/mocktest/subset-8b.txt
.venv/bin/python scripts/ctg_mocktest_ab.py --ids subset-8b.txt --diagnosis qwen3-fix2 qwen3-fix2 sub-8b sub-4b-fb8b sub-14b
# hiệu chỉnh lại ngưỡng lọc trọng tâm: một lượt ghi điểm, rồi phát lại các luật
.venv/bin/python scripts/ctg_mocktest_eval.py --tag cal --only fact,oos --record-relevance
.venv/bin/python scripts/ctg_relevance_calibrate.py --tag cal
```

Nếu muốn dùng lại kết quả lượt fix3b đang dở (194/481) thì chạy tiếp đúng cấu hình của nó: `DR_LLM=qwen3:8b DR_EXPAND_TOP_FILE=20 … --tag qwen3-fix3b`.

### 6.4 Việc nên làm tiếp (theo thứ tự)

1. **Lượt đầy đủ `qwen3-fix4`.** Cấu hình gồm fix3a, `DR_BM25_CANDIDATES=3000`, và luật tên riêng (ce2520a, đã bật mặc định). Mục đích: xác nhận ba thay đổi chưa đo đủ, đặc biệt là câu ngoài phạm vi về lại ~0 và số câu SAI giảm. Nếu tốt, đổi giá trị mặc định trong `dr/config.py`:
   - `DR_LLM_FALLBACK=qwen3:8b`
   - `DR_EXPAND_TOP_FILE=20`
   - `DR_BM25_CANDIDATES=3000`
2. **Model lớn hơn trên GPU server** (`qwen3:14b`, hoặc lớn hơn nếu VRAM cho phép), làm model chính hoặc dự phòng. Thử trên tập con trước. Trên Mac M3 Pro 18 GB, 8b đã chậm 1,6 lần; trên GPU NVIDIA thì độ trễ khác hẳn.
3. **Người duyệt 57 câu:** 35 câu wrong_claim, 9 câu gold_bad, 13 câu leaky. Câu nào mơ hồ thì sửa (ghi rõ tài liệu) trong một **bộ test v2 báo cáo riêng**. Không sửa lặng lẽ bộ v1.
4. **Xếp hạng trong cùng file** cho 11 câu ranked_out. Có thể thử tăng `DR_RERANK_TOP` lên 60–80: recall file nguồn trong top 80 là 264/350, so với 252 ở top 40, nhưng thời gian rerank gấp đôi.
5. Bộ câu thứ hai do người viết, để xác nhận các ngưỡng 0,7 và 0,8 không quá khớp.

## 7. Chưa kiểm chứng

- Ba thay đổi sau fix3a (6baba2c chỉ đo qua A/B; 05fd291; ce2520a) chưa có lượt đầy đủ.
- Giả thuyết "câu hỏi mơ hồ" chưa có người duyệt.
- Các ngưỡng lọc mới chỉ hiệu chỉnh trên bộ này.
- Quy tắc che SĐT cần pháp chế duyệt.
- Đáp án mẫu chưa có người duyệt.
