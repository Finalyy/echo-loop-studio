import base64
import io
import os
import shutil
import socket
import tempfile
import uuid
from pathlib import Path
import gradio as gr
from dotenv import load_dotenv
import qrcode

from config import (
    AUDIO_BITRATE,
    BASE_TEMP_DIR,
    DEFAULT_GROQ_API_KEY,
    DEFAULT_MAX_DURATION,
    DEFAULT_MIN_DURATION,
    DEFAULT_SILENCE_GAP,
    GROQ_MODEL,
    LANGUAGES,
)
from core.ai_segmenter import ai_optimize_sentences
from core.diarizer import diarize_and_label_speakers
from core.downloader import download_media_and_subtitles, process_uploaded_media
from core.groq_whisper import transcribe_with_groq
from core.merger import merge_short_segments
from core.subtitle import parse_srt_content, segments_to_srt
from core.utils import create_echoloop_zip, find_ffmpeg, sanitize_filename

# Ensure environment variables are loaded
load_dotenv()


def get_local_ip() -> str:
    """Detects primary local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_qr_base64(url: str) -> str:
    """Generates a base64 encoded PNG QR code."""
    try:
        qr = qrcode.QRCode(box_size=5, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#10b981", back_color="#0f172a")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def format_duration(seconds: float) -> str:
    """Formats seconds into mm:ss or hh:mm:ss string."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def process_audio_or_video(
    input_source_type: str,
    video_url: str,
    uploaded_file,
    language: str,
    prefer_ai: bool,
    ai_sentence_split: bool,
    auto_merge: bool,
    enable_diarization: bool,
    speaker_style: str,
    groq_api_key: str,
    cookies_file,
    min_duration: float,
    max_duration: float,
    silence_gap: float,
    progress=gr.Progress(track_tqdm=True),
):
    """
    Unified processing pipeline supporting both URL and direct file uploads:
    1. Downloads or converts media to 96kbps MP3.
    2. Retrieves or generates subtitles via Groq Whisper Turbo.
    3. Auto-merges short segments (4-7s).
    4. Labels speakers A, B, C... if diarization is enabled.
    5. Outputs .mp3, .srt, and .zip with identical names.
    """
    job_id = str(uuid.uuid4())[:8]
    job_dir = os.path.join(BASE_TEMP_DIR, f"job_{job_id}")
    os.makedirs(job_dir, exist_ok=True)

    # Resolve Groq API Key
    active_key = (groq_api_key or "").strip() or os.environ.get("GROQ_API_KEY", "").strip()

    try:
        mp3_path = None
        srt_content = None
        clean_title = ""
        duration = 0.0
        sub_source = "none"

        # ---------------------------------------------------------
        # Branch 1: Video/Audio from URL
        # ---------------------------------------------------------
        if input_source_type == "url":
            if not video_url or not video_url.strip():
                raise gr.Error("Vui lòng dán link video (YouTube, TikTok, BBC...) vào ô nhập!")

            url = video_url.strip()
            cookies_path = None
            if cookies_file is not None:
                if isinstance(cookies_file, str):
                    cookies_path = cookies_file
                elif hasattr(cookies_file, "name"):
                    cookies_path = cookies_file.name

            progress(0.15, desc="Đang kết nối & tải âm thanh MP3 (96kbps)...")
            mp3_path, srt_content, clean_title, duration, sub_source = download_media_and_subtitles(
                url=url,
                output_dir=job_dir,
                language=language,
                skip_subtitles=prefer_ai,
                cookies_path=cookies_path,
                progress_callback=lambda msg: progress(0.25, desc=msg),
            )

        # ---------------------------------------------------------
        # Branch 2: File Upload (MP3, WAV, M4A, MP4, etc.)
        # ---------------------------------------------------------
        else:
            if uploaded_file is None:
                raise gr.Error("Vui lòng chọn hoặc kéo thả file âm thanh / video cần tạo phụ đề!")

            input_path = uploaded_file.name if hasattr(uploaded_file, "name") else str(uploaded_file)
            progress(0.2, desc="Đang xử lý file tải lên và chuyển đổi sang MP3 96kbps...")
            mp3_path, clean_title, duration = process_uploaded_media(
                uploaded_file_path=input_path,
                output_dir=job_dir,
                progress_callback=lambda msg: progress(0.3, desc=msg),
            )
            # Uploaded files always use Groq Whisper AI for transcription
            srt_content = None
            sub_source = "none"

        segments = []
        final_source_label = ""

        # Step 2: Extract or Transcribe Subtitles
        if srt_content and not prefer_ai:
            progress(0.5, desc="Đang làm sạch phụ đề gốc từ video...")
            segments = parse_srt_content(srt_content)
            if sub_source == "manual":
                final_source_label = "✅ Phụ đề chuẩn do tác giả cung cấp"
            else:
                final_source_label = "🤖 Phụ đề tự động từ nền tảng (Đã làm sạch thẻ HTML)"

        # Fallback to Groq Whisper AI
        if not segments or prefer_ai:
            progress(0.55, desc=f"Đang phiên âm bằng Groq AI ({GROQ_MODEL})...")
            if not active_key:
                raise gr.Error(
                    "Cần có Groq API Key để phiên âm âm thanh! "
                    "Vui lòng nhập Groq API Key vào phần Cài đặt nâng cao hoặc thiết lập biến môi trường GROQ_API_KEY."
                )

            segments = transcribe_with_groq(
                audio_path=mp3_path,
                api_key=active_key,
                language=language,
                progress_callback=lambda msg: progress(0.7, desc=msg),
            )
            final_source_label = f"✨ Phiên âm AI Groq ({GROQ_MODEL})"

        if not segments:
            raise gr.Error("Không tìm thấy hoặc không tạo được phụ đề cho nội dung này!")

        original_segments_count = len(segments)

        # Step 3: AI Smart Sentence Optimization (Phân tích chia câu trọn vẹn, không ngắt nửa chừng)
        if ai_sentence_split and active_key:
            progress(0.75, desc="🧠 AI đang phân tích ngữ cảnh và chia câu trọn vẹn (không ngắt nghỉ nửa chừng)...")
            segments = ai_optimize_sentences(
                segments=segments,
                api_key=active_key,
                language=language,
                progress_callback=lambda msg: progress(0.78, desc=msg),
            )
            final_source_label += " + 🧠 AI chia câu trọn vẹn"

        # Step 4: Auto-merge short segments (Cân chỉnh thời lượng và nhịp điệu 4–7s)
        if auto_merge:
            progress(0.82, desc="Đang cân chỉnh thời lượng câu hoàn chỉnh (4–7s)...")
            segments = merge_short_segments(
                segments=segments,
                min_duration=min_duration,
                max_duration=max_duration,
                silence_gap_threshold=silence_gap,
            )

        # Step 5: Speaker Diarization (A, B, C...)
        if enable_diarization:
            progress(0.88, desc="Đang phân tích và gán nhãn người nói (A, B, C...)...")
            segments = diarize_and_label_speakers(
                segments=segments,
                api_key=active_key,
                style=speaker_style,
                progress_callback=lambda msg: progress(0.92, desc=msg),
            )
            final_source_label += " + 👥 Phân biệt người nói (A, B, C)"

        final_segments_count = len(segments)
        final_srt_text = segments_to_srt(segments)

        # Step 5: Write final .srt file
        final_srt_path = os.path.join(job_dir, f"{clean_title}.srt")
        with open(final_srt_path, "w", encoding="utf-8") as f:
            f.write(final_srt_text)

        # Step 6: Package matching files into Echo Loop ZIP
        progress(0.95, desc="Đang đóng gói file ZIP cho Echo Loop...")
        final_zip_path = os.path.join(job_dir, f"{clean_title}_EchoLoop.zip")
        create_echoloop_zip(mp3_path, final_srt_path, final_zip_path)

        progress(1.0, desc="Hoàn tất xử lý!")

        # File stats
        mp3_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
        duration_str = format_duration(duration)

        status_html = f"""
        <div class="result-card">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
                <span style="font-weight: 700; font-size: 1.1rem; color: #10b981;">🎉 Đã tạo thành công!</span>
                <span style="background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 2px 10px; border-radius: 9999px; font-size: 0.8rem; font-weight: 600;">Chuẩn Echo Loop</span>
            </div>
            <div style="font-size: 0.95rem; font-weight: 600; margin-bottom: 6px; word-break: break-word;">📄 Tiêu đề: {clean_title}</div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; font-size: 0.82rem; color: #cbd5e1; margin-top: 10px;">
                <div>⏱️ Thời lượng: <b>{duration_str}</b></div>
                <div>📊 Dung lượng MP3: <b>{mp3_size_mb:.2f} MB</b></div>
                <div>🎵 Bitrate: <b>{AUDIO_BITRATE}bps</b></div>
                <div>💬 Số câu: <b>{final_segments_count}</b> (gốc: {original_segments_count})</div>
            </div>
            <div style="margin-top: 10px; font-size: 0.82rem; color: #94a3b8;">
                Nguồn: <b style="color: #6ee7b7;">{final_source_label}</b>
            </div>
        </div>
        """

        preview_lines = final_srt_text.splitlines()[:60]
        preview_text = "\n".join(preview_lines)
        if len(final_srt_text.splitlines()) > 60:
            preview_text += "\n\n... (tải file .srt để xem toàn bộ danh sách câu) ..."

        return (
            status_html,
            mp3_path,         # Audio preview
            final_zip_path,   # ZIP download
            mp3_path,         # MP3 download
            final_srt_path,   # SRT download
            preview_text,     # Subtitle text preview
            gr.update(visible=True),  # Show results container
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise gr.Error(f"Lỗi xử lý: {str(e)}")


def build_app():
    """Constructs the Gradio application UI."""
    css_path = os.path.join(os.path.dirname(__file__), "static", "style.css")
    custom_css = ""
    if os.path.isfile(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            custom_css = f.read()

    local_ip = get_local_ip()
    local_url = f"http://{local_ip}:7860"
    qr_data_uri = generate_qr_base64(local_url)

    has_env_groq_key = bool(os.environ.get("GROQ_API_KEY", "").strip())
    groq_status_badge = (
        "🟢 Đã nhận diện GROQ_API_KEY từ hệ thống"
        if has_env_groq_key
        else "⚪ Chưa có biến môi trường (nhập thủ công bên dưới nếu cần)"
    )

    with gr.Blocks(title="Echo Loop Studio - Audio & Subtitle Generator") as demo:
        # Injected CSS & Mobile Viewport
        gr.HTML(
            f"""
            <style>{custom_css}</style>
            <div class="app-header">
                <div class="app-title">🎧 Echo Loop Studio</div>
                <div class="app-desc">Tạo cặp file <b>.mp3</b> (96kbps) + <b>.srt</b> chuẩn chỉ với 1 cú click để nạp trực tiếp vào ứng dụng <b>Echo Loop</b></div>
                <div class="badge-row">
                    <span class="badge">🚀 Nhanh & Nhẹ (96kbps)</span>
                    <span class="badge">🧠 AI chia câu trọn vẹn</span>
                    <span class="badge">👥 Phân biệt người nói A, B</span>
                    <span class="badge">📁 Hỗ trợ Upload File</span>
                    <span class="badge">⚡ Auto-merge 4–7s</span>
                </div>
            </div>
            """
        )

        # Smooth Mobile Access Card (Wi-Fi Local IP + QR Code)
        with gr.Accordion("📲 Hướng dẫn truy cập trên Điện thoại mượt mà (Không lo mất kết nối)", open=False):
            gr.HTML(
                f"""
                <div style="background: rgba(30, 41, 59, 0.6); padding: 16px; border-radius: 12px; border: 1px solid rgba(99, 102, 241, 0.3);">
                    <div style="display: flex; flex-wrap: wrap; gap: 16px; align-items: center;">
                        {"<img src='" + qr_data_uri + "' style='width: 110px; height: 110px; border-radius: 8px;' alt='QR Code' />" if qr_data_uri else ""}
                        <div style="flex: 1; min-width: 200px;">
                            <h4 style="margin: 0 0 6px 0; color: #34d399;">📶 Kết nối mượt mà qua Wi-Fi nhà bạn (Khuyên dùng):</h4>
                            <p style="margin: 0 0 8px 0; font-size: 0.88rem; color: #cbd5e1;">
                                Khi điện thoại và máy tính kết nối <b>cùng mạng Wi-Fi</b>, hãy mở link dưới hoặc quét mã QR:
                            </p>
                            <a href="{local_url}" target="_blank" style="display: inline-block; background: #6366f1; color: #fff; padding: 6px 14px; border-radius: 6px; font-weight: bold; text-decoration: none; font-size: 0.95rem;">
                                🌐 {local_url}
                            </a>
                            <p style="margin: 8px 0 0 0; font-size: 0.78rem; color: #94a3b8;">
                                ⭐ Link này <b>không bao giờ hết hạn</b>, truy cập cực nhanh và không bao giờ bị báo lỗi "No interface is running"!
                            </p>
                        </div>
                    </div>
                </div>
                """
            )

        # Input Tabs: URL vs File Upload
        input_type_state = gr.State(value="url")

        with gr.Tabs():
            with gr.TabItem("🔗 Dán Link Video / Audio") as tab_url:
                url_input = gr.Textbox(
                    label="Đường dẫn Video",
                    placeholder="Dán link YouTube, TikTok, Facebook, BBC, podcast...",
                    lines=1,
                    max_lines=2,
                )

            with gr.TabItem("📁 Tải File Âm Thanh / Video Từ Máy") as tab_file:
                file_input = gr.File(
                    label="Chọn hoặc kéo thả file âm thanh / video từ máy của bạn",
                    file_types=["audio", "video", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mov", ".mkv", ".webm"],
                )
                gr.Markdown("<small style='color: #94a3b8;'>Hỗ trợ: MP3, WAV, M4A, AAC, FLAC, OGG, MP4, MOV, MKV... Hệ thống sẽ tự động tách tiếng và xuất file 96kbps chuẩn Echo Loop.</small>")

        # Tab switch callbacks to keep input_type_state updated
        tab_url.select(fn=lambda: "url", outputs=[input_type_state])
        tab_file.select(fn=lambda: "file", outputs=[input_type_state])

        with gr.Row():
            language_dropdown = gr.Dropdown(
                choices=LANGUAGES,
                value="en",
                label="🌐 Ngôn ngữ nhận diện",
                scale=2,
            )
            ai_sentence_split_checkbox = gr.Checkbox(
                label="🧠 AI chia câu trọn vẹn (Không ngắt nửa chừng)",
                value=True,
                info="Phân tích ngữ cảnh, điểm ngắt nghỉ hợp lý, giữ câu hoàn chỉnh",
                scale=2,
            )
            auto_merge_checkbox = gr.Checkbox(
                label="⚡ Cân chỉnh nhịp (4–7s)",
                value=True,
                info="Mô phỏng Auto-merge Echo Loop",
                scale=1,
            )
            prefer_ai_checkbox = gr.Checkbox(
                label="🤖 Ép dùng Groq AI",
                value=False,
                info="Bỏ qua sub gốc, dùng Whisper AI",
                scale=1,
            )

        # Speaker Diarization Section
        with gr.Row():
            diarize_checkbox = gr.Checkbox(
                label="👥 Phân biệt rõ người nói (A, B, C...)",
                value=True,
                info="Tự động nhận diện đối thoại và gán nhãn người nói",
                scale=2,
            )
            speaker_style_dropdown = gr.Dropdown(
                choices=[
                    ("Tiếng Việt: [Người nói A], [Người nói B]", "vietnamese"),
                    ("Tiếng Anh: [Speaker A], [Speaker B]", "english"),
                    ("Ngắn gọn: [A], [B]", "short"),
                ],
                value="vietnamese",
                label="Định dạng tên người nói",
                scale=2,
            )

        # Advanced Settings Accordion
        with gr.Accordion("⚙️ Cài đặt nâng cao & Groq API Key", open=False):
            gr.Markdown(f"**Trạng thái Groq API:** `{groq_status_badge}`")
            groq_key_input = gr.Textbox(
                label="Groq API Key (Tùy chọn)",
                placeholder="gsk_... (Để trống nếu đã lưu trong file .env)",
                type="password",
            )
            with gr.Row():
                min_dur_slider = gr.Slider(
                    minimum=2.0,
                    maximum=6.0,
                    value=DEFAULT_MIN_DURATION,
                    step=0.5,
                    label="Độ dài tối thiểu mỗi câu (giây)",
                )
                max_dur_slider = gr.Slider(
                    minimum=5.0,
                    maximum=12.0,
                    value=DEFAULT_MAX_DURATION,
                    step=0.5,
                    label="Độ dài tối đa mỗi câu (giây)",
                )
                gap_slider = gr.Slider(
                    minimum=0.8,
                    maximum=3.0,
                    value=DEFAULT_SILENCE_GAP,
                    step=0.1,
                    label="Khoảng lặng ngắt câu (giây)",
                )
            cookies_input = gr.File(
                label="Tải lên file cookies.txt (Tùy chọn - khi video YouTube bị chặn hoặc giới hạn độ tuổi)",
                file_types=[".txt"],
            )

        # Action Submit Button
        submit_btn = gr.Button(
            "🚀 BẮT ĐẦU XỬ LÝ (TẠO AUDIO & PHỤ ĐỀ)",
            variant="primary",
            elem_classes=["action-btn"],
        )

        # Output Section
        with gr.Column(visible=False) as results_container:
            gr.Markdown("---")
            status_output = gr.HTML()

            with gr.Row():
                audio_preview = gr.Audio(
                    label="🎧 Nghe thử Audio (96kbps)",
                    interactive=False,
                    elem_id="audio-player",
                )

            gr.Markdown("### 📥 Tải về máy điện thoại")
            with gr.Row():
                zip_download = gr.File(
                    label="📦 Tải File ZIP trọn bộ (.mp3 + .srt trùng tên - Khuyên dùng)",
                    elem_classes=["zip-download-btn"],
                )
            with gr.Row():
                mp3_download = gr.File(label="🎵 Tải File Audio (.mp3)")
                srt_download = gr.File(label="📝 Tải File Phụ đề (.srt)")

            with gr.Accordion("👁️ Xem trước nội dung phụ đề", open=False):
                srt_preview_box = gr.Textbox(
                    label="Nội dung phụ đề (.srt)",
                    lines=12,
                    interactive=False,
                )

        # Instructions Section
        with gr.Accordion("📖 Hướng dẫn nạp vào Echo Loop & Sử dụng", open=False):
            gr.Markdown(
                """
                <div class="guide-content">
                    <h4 style="margin-top: 6px; color: #a5b4fc;">📱 Cách nạp vào ứng dụng Echo Loop:</h4>
                    <div class="guide-step">
                        <span class="step-num">1</span>
                        <span>Nhấn nút <b>📦 Tải File ZIP trọn bộ</b> ở trên (chứa cả 2 file trùng tên 100%).</span>
                    </div>
                    <div class="guide-step">
                        <span class="step-num">2</span>
                        <span>Mở ứng dụng <b>Echo Loop</b> trên điện thoại -> Chọn <b>Local Upload</b>.</span>
                    </div>
                    <div class="guide-step">
                        <span class="step-num">3</span>
                        <span>Chọn file tải về. Echo Loop sẽ tự động khớp audio và phụ đề theo mốc thời gian và hiển thị tên từng người nói (Người nói A, Người nói B...) để bạn luyện tập!</span>
                    </div>
                </div>
                """
            )

        # Connect click event
        submit_btn.click(
            fn=process_audio_or_video,
            inputs=[
                input_type_state,
                url_input,
                file_input,
                language_dropdown,
                prefer_ai_checkbox,
                ai_sentence_split_checkbox,
                auto_merge_checkbox,
                diarize_checkbox,
                speaker_style_dropdown,
                groq_key_input,
                cookies_input,
                min_dur_slider,
                max_dur_slider,
                gap_slider,
            ],
            outputs=[
                status_output,
                audio_preview,
                zip_download,
                mp3_download,
                srt_download,
                srt_preview_box,
                results_container,
            ],
        )

    return demo


# Create app instance
app = build_app()

if __name__ == "__main__":
    ffmpeg_found = find_ffmpeg()
    local_ip = get_local_ip()
    port = int(os.environ.get("PORT", 7860))
    local_url = f"http://{local_ip}:{port}"
    is_cloud = bool(os.environ.get("RENDER") or os.environ.get("SPACE_ID"))

    print("=" * 65)
    print("      🎧 ECHO LOOP STUDIO - AUDIO & SUBTITLE GENERATOR")
    print("=" * 65)
    print(f"[*] FFmpeg detected at: {ffmpeg_found}")
    print(f"[*] Server Port: {port}")
    if not is_cloud:
        print(f"[*] Local Wi-Fi URL (Mở trên điện thoại cùng mạng Wi-Fi): {local_url}")
        print("[*] Quét mã QR dưới đây bằng camera điện thoại để mở ứng dụng:")
        print("=" * 65)
        try:
            qr = qrcode.QRCode()
            qr.add_data(local_url)
            qr.print_ascii(invert=True)
        except Exception:
            pass
    print("=" * 65)

    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=not is_cloud,
    )
