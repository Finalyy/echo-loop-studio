---
title: Echo Loop Studio - Audio & Subtitle Generator
emoji: 🎧
colorFrom: indigo
colorTo: green
sdk: gradio
sdk_version: 6.32.0
app_file: app.py
pinned: false
license: mit
---

# 🎧 Echo Loop Studio - Ứng dụng Tạo Audio & Phụ đề chuẩn cho Echo Loop

Ứng dụng Web thân thiện với thiết bị di động (Mobile-First, hỗ trợ ghim ra màn hình chính) giúp bạn tự động tải âm thanh, trích xuất hoặc tạo phụ đề chuẩn xác bằng AI và đóng gói file `.zip` sẵn sàng nạp trực tiếp vào ứng dụng di động **Echo Loop**.

---

## 🌟 Tính năng nổi bật

1. **Chuẩn hóa cho Echo Loop (Local Upload)**:
   - Xuất cặp file `<Tên_bài>.mp3` và `<Tên_bài>.srt` đặt tên **hoàn toàn trùng khớp**.
   - Tự động đóng gói file `<Tên_bài>_EchoLoop.zip` để tải về điện thoại chỉ bằng 1 chạm, giúp Echo Loop tự động liên kết audio và phụ đề khi import.
2. **Âm thanh tối ưu**:
   - Tự động chuyển đổi sang MP3 chuẩn **96kbps** (chất lượng giọng nói rõ ràng, dung lượng file nhẹ, dưới giới hạn 25MB của Groq API và tiết kiệm bộ nhớ điện thoại).
3. **Trích xuất phụ đề thông minh**:
   - Tự động nhận diện và ưu tiên tải phụ đề thủ công của video (YouTube, BBC, v.v.).
   - Tự động fallback sang phụ đề tự động của nền tảng nếu không có phụ đề thủ công.
   - Hỗ trợ làm sạch các thẻ HTML (`<font>`, `<b>`, `<i>`, `<c>`, etc.) và loại bỏ hiện tượng dòng lặp (rolling captions).
4. **Siêu AI Groq Whisper Turbo (`whisper-large-v3-turbo`)**:
   - Khi video không có phụ đề hoặc khi bạn bật chế độ **"Ép dùng Groq AI"**, hệ thống sẽ dùng Groq API với tốc độ cực nhanh (nhanh gấp 5-10 lần thời gian thực).
   - Tự động chia nhỏ audio nếu vượt quá 25MB và ghép nối mốc thời gian hoàn hảo.
5. **Thuật toán Auto-Merge (4–7s)**:
   - Mô phỏng tính năng *Auto-merge short sentences* của Echo Loop: nối các mẩu câu vụn vặt thành câu hoàn chỉnh 4.0 – 8.5 giây dựa trên dấu câu (`. ? !`) và khoảng lặng ngừng nói (gap >= 1.5s).
6. **Mobile-First Responsive**:
   - Tối ưu hiển thị và cảm ứng trên trình duyệt điện thoại (iOS Safari, Android Chrome).
   - Tích hợp `manifest.json` cho phép **Ghim ra màn hình chính (Add to Home Screen)** dùng như ứng dụng native.

---

## 🚀 Hướng dẫn cài đặt & Chạy cục bộ (Local)

### 1. Yêu cầu hệ thống
- Python 3.10+
- FFmpeg (đã được cài đặt và thêm vào PATH hệ thống)

### 2. Cài đặt thư viện
```bash
pip install -r requirements.txt
```

### 3. Cấu hình biến môi trường
Tạo file `.env` (hoặc sao chép từ `.env.example`):
```bash
cp .env.example .env
```
Điền khóa Groq API của bạn:
```env
GROQ_API_KEY=gsk_your_groq_api_key_here
```
*(Bạn có thể lấy khóa miễn phí tại: [Groq Console](https://console.groq.com/keys))*

### 4. Khởi chạy ứng dụng
```bash
python app.py
```
Mở trình duyệt tại địa chỉ: `http://localhost:7860`

---

## 🌐 Triển khai miễn phí lên Hugging Face Spaces

1. Tạo một Space mới trên [Hugging Face Spaces](https://huggingface.co/spaces).
2. Chọn SDK: **Gradio**, Phần cứng: **CPU Basic (Miễn phí)**.
3. Đẩy toàn bộ mã nguồn của dự án này lên repository của Space:
   - `app.py`
   - `config.py`
   - `requirements.txt`
   - `packages.txt` (Hugging Face sẽ tự động cài `ffmpeg`)
   - Thư mục `core/` và `static/`
4. Vào mục **Settings** -> **Variables and secrets** trong Space của bạn:
   - Thêm Secret mới: Tên `GROQ_API_KEY`, giá trị là khóa API Groq của bạn.
5. Space sẽ tự động build và chạy trực tiếp trên web!

---

## 📱 Cách nạp vào ứng dụng Echo Loop

1. Mở ứng dụng web này trên điện thoại (iPhone hoặc Android).
2. Dán link video bạn muốn học nghe/nói -> Bấm **🚀 BẮT ĐẦU XỬ LÝ**.
3. Sau khi xử lý xong, nhấn **📦 Tải File ZIP trọn bộ** (hoặc tải riêng lẻ cả 2 file `.mp3` và `.srt`).
4. Mở ứng dụng **Echo Loop** -> Chọn **Local Upload** (Nạp file cục bộ).
5. Nạp file Audio và Subtitle vào. Echo Loop sẽ tự động ghép cặp câu hoàn chỉnh để bạn bắt đầu luyện nghe và lặp lại (Shadowing)!

---

## 📲 Ghim ra màn hình chính điện thoại (PWA)

- **iPhone / iPad (Safari)**: Nhấn biểu tượng **Chia sẻ (Share)** -> Chọn **"Thêm vào MH chính" (Add to Home Screen)**.
- **Android (Chrome)**: Nhấn biểu tượng **3 chấm** ở góc trên bên phải -> Chọn **"Thêm vào màn hình chính" (Add to Home screen)**.
