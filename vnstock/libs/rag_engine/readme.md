Tuyệt vời! Sau khi đã sửa hết các lỗi và tối ưu hóa hệ thống, dưới đây là **Hướng dẫn sử dụng toàn tập** cho hệ thống Financial RAG của bạn.

Hệ thống này hiện đang chạy trên kiến trúc: **Python Package (`rag_engine`)** + **LightRAG (Graph + Vector)** + **DeepSeek-V3 (Reasoning)** + **Ragas (Evaluation)** + **GTX 1650 (Local Embedding)**.

---

### 1. Chuẩn bị trước khi chạy

Đảm bảo cấu trúc thư mục của bạn đúng như sau:

```text
project_root/
├── .env                        # Chứa API Key (CLIPROXY_API_KEY=...)
├── rag_storage/                # (Tự động tạo) Nơi chứa database của LightRAG
├── data/                       # Thư mục dữ liệu
│   ├── golden_dataset.json     # File câu hỏi mẫu để chấm điểm
│   └── financial_reports/      # Thư mục chứa các file .txt báo cáo tài chính
│       ├── CTG-Q3-2025.ocr_text.txt
│       └── ...
```

---

### 2. Lệnh Index dữ liệu (Nạp kiến thức)

Đây là bước quan trọng nhất để biến văn bản thô thành Đồ thị tri thức (Graph) và Vector.

**Lưu ý:** Với card GTX 1650, quá trình này sẽ tốn thời gian. Chúng ta đã set `timeout=600s` để tránh lỗi.

#### Cách 1: Index toàn bộ thư mục theo mẫu tên file
Dùng lệnh này để quét tất cả các file có đuôi `.ocr_text.txt` trong thư mục báo cáo.

```bash
python -m rag_engine index --dir data/financial_reports --pattern "*.ocr_text.txt"
```

#### Cách 2: Index một file cụ thể
Dùng khi bạn mới tải thêm 1 báo cáo mới và muốn thêm vào hệ thống (LightRAG hỗ trợ nạp thêm - incremental update).

```bash
python -m rag_engine index --dir "data/financial_reports/BID-Q3-2025.ocr_text.txt"
```

**Dấu hiệu thành công:**
*   Terminal hiện: `Loading embedding model... (CUDA enabled)`
*   Terminal hiện: `✅ Indexed: <tên_file>`

---

### 3. Lệnh Hỏi đáp (Ask)

Dùng để kiểm tra thử xem hệ thống trả lời có đúng không trước khi chạy đánh giá hàng loạt.

#### Chế độ Hybrid (Khuyên dùng cho BCTC)
Kết hợp cả tìm kiếm từ khóa chính xác (số liệu) và quan hệ thực thể (ngữ cảnh).

```bash
python -m rag_engine ask "Lợi nhuận trước thuế của VietinBank quý 3/2025 là bao nhiêu?" --mode hybrid
```

#### Chế độ Local (Tập trung chi tiết)
Dùng khi hỏi về một con số rất cụ thể nằm sâu trong bảng biểu.

```bash
python -m rag_engine ask "Chi phí dự phòng rủi ro tín dụng cụ thể là bao nhiêu?" --mode local
```

#### Chế độ Global (Tập trung tổng quan)
Dùng cho các câu hỏi tóm tắt, đánh giá chung.

```bash
python -m rag_engine ask "Tình hình tài chính chung của CTG trong báo cáo này thế nào?" --mode global
```

---

### 4. Lệnh Đánh giá (Evaluate)

Dùng để chấm điểm hệ thống dựa trên bộ `golden_dataset.json`. Quá trình này sẽ sử dụng model `qwen3-coder-plus` (Judge) để so sánh câu trả lời của LightRAG với đáp án mẫu.

```bash
python -m rag_engine eval --dir data
```

**Kết quả đầu ra:**
1.  Hiển thị bảng điểm trung bình trên màn hình:
    *   **Faithfulness:** Độ trung thực (Câu trả lời có bịa đặt so với ngữ cảnh không?).
    *   **Answer Correctness:** Độ chính xác (Câu trả lời có khớp ý và số liệu với đáp án mẫu không?).
    *   **Answer Relevancy:** Độ liên quan (Câu trả lời có đúng trọng tâm câu hỏi không?).
    *   **Context Recall:** Khả năng tìm kiếm (Hệ thống có tìm thấy thông tin đúng trong đống tài liệu không?).
2.  File `ragas_report.csv`: Lưu chi tiết điểm số từng câu hỏi để bạn phân tích.

---

### 5. Các mẹo vận hành & Xử lý sự cố

#### 1. Làm sạch dữ liệu (Reset)
Nếu bạn index sai file hoặc muốn làm lại từ đầu sạch sẽ:
*   **Cách làm:** Xóa thư mục `rag_storage`.
*   **Lệnh:** `rmdir /s /q rag_storage` (Windows) hoặc xóa thủ công trong Explorer.
*   Sau đó chạy lệnh `index` lại từ đầu.

#### 2. GPU GTX 1650 bị chậm/đơ
*   Nếu máy quá lag khi chạy `index`, hãy vào file `rag_engine/embedding.py`, đổi `batch_size=2` thành `batch_size=1`.
*   Nếu lỗi bộ nhớ (OOM), đổi `device="cuda"` thành `device="cpu"` (chậm hơn nhưng ổn định tuyệt đối).

#### 3. Cập nhật dữ liệu Golden Dataset
*   File `data/golden_dataset.json` là chuẩn mực để chấm điểm.
*   Hãy đảm bảo `ground_truth_answer` trong file này có định dạng **ngắn gọn, chính xác** (Ví dụ: "100 tỷ đồng" thay vì "Khoảng 100 tỷ"). Code tối ưu prompt tôi vừa viết sẽ cố gắng ép LightRAG trả lời ngắn gọn để khớp với file này.

Chúc dự án của bạn thành công! Hệ thống này hiện tại đã khá mạnh mẽ để xử lý báo cáo tài chính tiếng Việt.