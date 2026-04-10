from pypdf import PdfReader, PdfWriter


def compress_pdf(file_path, level="medium"):
    level = (level or "medium").lower().strip()
    if level not in {"low", "medium", "high"}:
        level = "medium"

    base, _ = file_path.rsplit(".", 1)
    output = f"{base}_compressed.pdf"
    reader = PdfReader(file_path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)
        if level != "low":
            writer.pages[-1].compress_content_streams()

    with open(output, "wb") as f:
        writer.write(f)

    return output
