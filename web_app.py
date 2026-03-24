from flask import Flask, request, send_file, jsonify, render_template, abort
import os
from werkzeug.utils import secure_filename
import uuid

from converters.image_converter import convert_image

app = Flask(__name__, template_folder="templates/templates")

UPLOAD_FOLDER = "uploads"
MAX_UPLOAD_MB = 25

ALLOWED_INPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_OUTPUT_FORMATS = {"jpg", "png", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

@app.route("/")
def home():
    return render_template("index.html")


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


@app.errorhandler(413)
def request_entity_too_large(_):
    return jsonify({"error": f"File too large. Max size is {MAX_UPLOAD_MB}MB."}), 413


if __name__ == "__main__":
    app.run(debug=True)
