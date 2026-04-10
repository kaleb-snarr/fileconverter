from flask import Flask, request, send_file, jsonify, render_template, abort, Response, redirect, url_for
import os
from werkzeug.utils import secure_filename
import uuid
import datetime

from converters.image_converter import convert_image
from converters.pdf_compressor import compress_pdf

app = Flask(__name__, template_folder="templates/templates")

UPLOAD_FOLDER = "uploads"
MAX_UPLOAD_MB = 25

ALLOWED_INPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_PDF_EXTENSIONS = {".pdf"}
ALLOWED_OUTPUT_FORMATS = {"jpg", "png", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

TEMPLATE_LASTMOD = {
    "home": os.path.join("templates", "templates", "landing.html"),
    "converter": os.path.join("templates", "templates", "index.html"),
    "pdf_compressor": os.path.join("templates", "templates", "pdf_compress.html"),
    "word_counter": os.path.join("templates", "templates", "word_counter.html"),
}

SEO_PAGES = [
    # Core pages
    ("/", 1.0),

    # Tool pages (high priority)
    ("/jpeg-to-png", 0.9),
    ("/pdf-compressor", 0.9),
    ("/word-counter", 0.9),
]

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
    return render_template("index.html")

@app.route("/pdf-compressor")
def pdf_compressor():
    return render_template("pdf_compress.html")

@app.route("/word-counter")
def word_counter():
    return render_template("word_counter.html")

@app.route("/converter")
def converter_redirect():
    return redirect(url_for("converter"), code=301)

@app.route("/compress-pdf")
def pdf_compressor_redirect():
    return redirect(url_for("pdf_compressor"), code=301)

@app.route("/wordcounter")
def word_counter_redirect():
    return redirect(url_for("word_counter"), code=301)


@app.route("/sitemap.xml")
def sitemap():
    from flask import request, Response
    import datetime

    base = request.url_root.rstrip("/")

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

@app.route("/convert", methods=["POST"])
def convert():
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
    return jsonify({"error": f"File too large. Max size is {MAX_UPLOAD_MB}MB."}), 413


if __name__ == "__main__":
    app.run(debug=True)
