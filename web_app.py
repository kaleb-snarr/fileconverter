from flask import Flask, request, send_file, jsonify, render_template, abort, Response, redirect, url_for
import os
from werkzeug.utils import secure_filename
import uuid
import datetime
import threading
import time

from converters.image_converter import convert_image
from converters.pdf_compressor import compress_pdf
from converters.video_compressor import compress_video_message_fast, ALLOWED_VIDEO_EXTENSIONS

app = Flask(__name__, template_folder="templates/templates")

SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")

UPLOAD_FOLDER = "uploads"
MAX_IMAGE_UPLOAD_MB = 25
MAX_PDF_UPLOAD_MB = 25
MAX_VIDEO_UPLOAD_MB = 1024  # 1GB

ALLOWED_INPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_PDF_EXTENSIONS = {".pdf"}
ALLOWED_OUTPUT_FORMATS = {"jpg", "png", "webp"}
ALLOWED_VIDEO_OUTPUTS = {"message"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# Flask's MAX_CONTENT_LENGTH is app-wide. Set it to the largest limit we support
# (video uploads) and enforce smaller caps per endpoint for other tools.
app.config["MAX_CONTENT_LENGTH"] = MAX_VIDEO_UPLOAD_MB * 1024 * 1024

# In-memory async job store for long-running video compression.
# Note: This is process-local (won't persist across restarts / multiple workers).
_video_jobs_lock = threading.Lock()
_video_jobs: dict[str, dict] = {}
_VIDEO_JOB_TTL_SECONDS = 60 * 30


def _video_jobs_cleanup() -> None:
    now = time.time()
    to_delete: list[str] = []
    with _video_jobs_lock:
        for job_id, job in list(_video_jobs.items()):
            created_at = job.get("created_at", 0)
            if created_at and now - created_at > _VIDEO_JOB_TTL_SECONDS:
                to_delete.append(job_id)
        for job_id in to_delete:
            job = _video_jobs.pop(job_id, None) or {}
            for path in (job.get("input_path"), job.get("output_path")):
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

TEMPLATE_LASTMOD = {
    "home": os.path.join("templates", "templates", "landing.html"),
    "converter": os.path.join("templates", "templates", "index.html"),
    "pdf_compressor": os.path.join("templates", "templates", "pdf_compress.html"),
    "word_counter": os.path.join("templates", "templates", "word_counter.html"),
    "video_compressor": os.path.join("templates", "templates", "video_compress.html"),
}

SEO_PAGES = [
    # Core pages
    ("/", 1.0),

    # Tool pages (high priority)
    ("/jpeg-to-png", 0.9),
    ("/pdf-compressor", 0.9),
    ("/word-counter", 0.9),
    ("/video-compressor", 0.9),

]

def _site_url():
    if SITE_URL:
        return SITE_URL
    return request.url_root.rstrip("/")


def _canonical_url(path: str):
    return f"{_site_url()}{path}"


@app.route("/")
def home():
    return render_template("landing.html")

@app.route("/favicon.ico")
def favicon_ico():
    return send_file("snarrtoolsfavicon.png", mimetype="image/png")

@app.route("/snarrtoolsfavicon.png")
def favicon_png():
    return send_file("snarrtoolsfavicon.png", mimetype="image/png")

@app.route("/jpeg-to-png")
def converter():
    return render_template("index.html", canonical_url=_canonical_url("/jpeg-to-png"))

@app.route("/pdf-compressor")
def pdf_compressor():
    return render_template("pdf_compress.html", canonical_url=_canonical_url("/pdf-compressor"))

@app.route("/word-counter")
def word_counter():
    return render_template("word_counter.html", canonical_url=_canonical_url("/word-counter"))

@app.route("/video-compressor")
def video_compressor():
    return render_template("video_compress.html", canonical_url=_canonical_url("/video-compressor"))


@app.route("/jpeg-to-png/")
def converter_slash_redirect():
    return redirect(url_for("converter"), code=301)


@app.route("/pdf-compressor/")
def pdf_compressor_slash_redirect():
    return redirect(url_for("pdf_compressor"), code=301)


@app.route("/word-counter/")
def word_counter_slash_redirect():
    return redirect(url_for("word_counter"), code=301)


@app.route("/pdf_compressor.html")
@app.route("/pdf_compressor")
@app.route("/pdf_compress.html")
def pdf_compressor_legacy_redirects():
    return redirect(url_for("pdf_compressor"), code=301)

@app.route("/converter")
def converter_redirect():
    return redirect(url_for("converter"), code=301)

@app.route("/compress-pdf")
def pdf_compressor_redirect():
    return redirect(url_for("pdf_compressor"), code=301)

@app.route("/wordcounter")
def word_counter_redirect():
    return redirect(url_for("word_counter"), code=301)


@app.route("/compress-video", methods=["POST"])
def compress_video():
    if request.content_length and request.content_length > MAX_VIDEO_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"File too large. Max size is {MAX_VIDEO_UPLOAD_MB}MB."}), 413

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    mode = request.form.get("mode", "message").lower().strip()

    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    filename = secure_filename(file.filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return jsonify({"error": "Unsupported input file type."}), 400

    if mode not in ALLOWED_VIDEO_OUTPUTS:
        return jsonify({"error": "Unsupported compression mode."}), 400

    unique_id = uuid.uuid4().hex[:12]
    name_root = os.path.splitext(filename)[0]
    safe_root = secure_filename(name_root) or f"video_{unique_id}"
    safe_name = f"{safe_root}_{unique_id}{ext}"
    input_path = os.path.join(UPLOAD_FOLDER, safe_name)

    file.save(input_path)

    output_path = None
    try:
        output_path = compress_video_message_fast(input_path)
        download_name = f"{safe_root}_message.mp4"
        return send_file(output_path, as_attachment=True, download_name=download_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        for path in (input_path, output_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


@app.route("/compress-video/job", methods=["POST"])
def compress_video_job_create():
    _video_jobs_cleanup()

    if request.content_length and request.content_length > MAX_VIDEO_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"File too large. Max size is {MAX_VIDEO_UPLOAD_MB}MB."}), 413

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    mode = request.form.get("mode", "message").lower().strip()

    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    if mode not in ALLOWED_VIDEO_OUTPUTS:
        return jsonify({"error": "Unsupported compression mode."}), 400

    filename = secure_filename(file.filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return jsonify({"error": "Unsupported input file type."}), 400

    unique_id = uuid.uuid4().hex[:12]
    name_root = os.path.splitext(filename)[0]
    safe_root = secure_filename(name_root) or f"video_{unique_id}"
    safe_name = f"{safe_root}_{unique_id}{ext}"
    input_path = os.path.join(UPLOAD_FOLDER, safe_name)

    file.save(input_path)

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "created_at": time.time(),
        "status": "queued",
        "mode": mode,
        "target_mb": None,
        "target_height": None,
        "safe_root": safe_root,
        "input_path": input_path,
        "output_path": None,
        "error": None,
    }

    with _video_jobs_lock:
        _video_jobs[job_id] = job

    def _worker():
        output_path = None
        try:
            with _video_jobs_lock:
                if job_id in _video_jobs:
                    _video_jobs[job_id]["status"] = "processing"

            # Single preset: fast, full-length, messaging-friendly MP4.
            output_path = compress_video_message_fast(input_path)

            with _video_jobs_lock:
                if job_id in _video_jobs:
                    _video_jobs[job_id]["output_path"] = output_path
                    _video_jobs[job_id]["status"] = "done"
        except Exception as e:
            with _video_jobs_lock:
                if job_id in _video_jobs:
                    _video_jobs[job_id]["error"] = str(e)
                    _video_jobs[job_id]["status"] = "error"
            # Best-effort cleanup of partial output
            try:
                if output_path and os.path.exists(output_path):
                    os.remove(output_path)
            except Exception:
                pass
        finally:
            # Always remove input
            try:
                if input_path and os.path.exists(input_path):
                    os.remove(input_path)
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()

    return jsonify({"job_id": job_id}), 202


@app.route("/compress-video/job/<job_id>", methods=["GET"])
def compress_video_job_status(job_id: str):
    _video_jobs_cleanup()
    with _video_jobs_lock:
        job = _video_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(
            {
                "job_id": job_id,
                "status": job.get("status"),
                "error": job.get("error"),
                "download_url": f"/compress-video/job/{job_id}/download" if job.get("status") == "done" else None,
            }
        )


@app.route("/compress-video/job/<job_id>/download", methods=["GET"])
def compress_video_job_download(job_id: str):
    _video_jobs_cleanup()
    with _video_jobs_lock:
        job = _video_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("status") != "done" or not job.get("output_path"):
            return jsonify({"error": "Job not ready."}), 409
        output_path = job.get("output_path")
        safe_root = job.get("safe_root") or "video"
        mode = job.get("mode") or "quality"
        if mode == "sms":
            download_name = f"{safe_root}_sms.mp4"
        elif mode == "target":
            target_height = job.get("target_height") or 480
            target_mb = job.get("target_mb") or 2.5
            download_name = f"{safe_root}_{target_height}p_{str(target_mb).replace('.', '_')}MB.mp4"
        else:
            download_name = f"{safe_root}_quality.mp4"

    # Send outside the lock
    resp = send_file(output_path, as_attachment=True, download_name=download_name)

    # Best-effort cleanup after download is initiated
    try:
        with _video_jobs_lock:
            job = _video_jobs.pop(job_id, None) or {}
        for path in (job.get("output_path"),):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
    except Exception:
        pass

    return resp


@app.route("/sitemap.xml")
def sitemap():
    from flask import request, Response
    import datetime

    base = _site_url()

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    today = datetime.date.today().isoformat()

    for path, priority in SEO_PAGES:
        lines.append("  <url>")
        lines.append(f"    <loc>{base}{path}</loc>")
        lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")

    lines.append("</urlset>")

    return Response("\n".join(lines), mimetype="application/xml")


@app.route("/robots.txt")
def robots_txt():
    base = _site_url()
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {base}/sitemap.xml",
        ]
    )
    return Response(body + "\n", mimetype="text/plain")

@app.route("/convert", methods=["POST"])
def convert():
    if request.content_length and request.content_length > MAX_IMAGE_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"File too large. Max size is {MAX_IMAGE_UPLOAD_MB}MB."}), 413

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    output_format = request.form.get("format", "").lower().strip()

    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    if not output_format:
        return jsonify({"error": "Output format is required."}), 400

    filename = secure_filename(file.filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in ALLOWED_INPUT_EXTENSIONS:
        return jsonify({"error": "Unsupported input file type."}), 400

    if output_format not in ALLOWED_OUTPUT_FORMATS:
        return jsonify({"error": "Unsupported output format."}), 400

    width = request.form.get("width")
    height = request.form.get("height")
    quality = request.form.get("quality")

    def _as_positive_int(value):
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    width = _as_positive_int(width)
    height = _as_positive_int(height)

    unique_id = uuid.uuid4().hex[:12]
    name_root = os.path.splitext(filename)[0]
    safe_root = secure_filename(name_root) or f"file_{unique_id}"
    safe_name = f"{safe_root}_{unique_id}{ext}"
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    input_path = os.path.join(UPLOAD_FOLDER, safe_name)

    file.save(input_path)

    output_path = None
    try:
        convert_image(
            input_path,
            output_format,
            width=width,
            height=height,
            quality=quality,
        )

        # assume same filename but new extension
        output_path = input_path.rsplit(".", 1)[0] + "." + output_format

        if width or height:
            size_tag = f"_{width or ''}x{height or ''}".rstrip("x")
        else:
            size_tag = ""
        download_name = f"{safe_root}{size_tag}.{output_format}"
        return send_file(output_path, as_attachment=True, download_name=download_name)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Best-effort cleanup
        for path in (input_path, output_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


@app.route("/compress", methods=["POST"])
def compress():
    if request.content_length and request.content_length > MAX_PDF_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"File too large. Max size is {MAX_PDF_UPLOAD_MB}MB."}), 413

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    level = request.form.get("level", "medium").lower().strip()

    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    filename = secure_filename(file.filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in ALLOWED_PDF_EXTENSIONS:
        return jsonify({"error": "Unsupported input file type."}), 400

    unique_id = uuid.uuid4().hex[:12]
    name_root = os.path.splitext(filename)[0]
    safe_root = secure_filename(name_root) or f"file_{unique_id}"
    safe_name = f"{safe_root}_{unique_id}{ext}"
    input_path = os.path.join(UPLOAD_FOLDER, safe_name)

    file.save(input_path)

    output_path = None
    try:
        output_path = compress_pdf(input_path, level=level)
        download_name = f"{safe_root}_compressed.pdf"
        return send_file(output_path, as_attachment=True, download_name=download_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Best-effort cleanup
        for path in (input_path, output_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


@app.errorhandler(413)
def request_entity_too_large(_):
    max_len = app.config.get("MAX_CONTENT_LENGTH")
    max_mb = int(max_len / (1024 * 1024)) if isinstance(max_len, (int, float)) and max_len else None
    if max_mb:
        return jsonify({"error": f"File too large. Max size is {max_mb}MB."}), 413
    return jsonify({"error": "File too large."}), 413


if __name__ == "__main__":
    app.run(debug=True)
