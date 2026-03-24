from utils import get_output_path
from PIL import Image, ImageOps

def _to_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None

def _clamp_quality(value, default=85):
    value = _to_int(value)
    if value is None:
        return default
    return max(1, min(100, value))

def convert_image(file_path, output_format, width=None, height=None, quality=85, keep_aspect=True):
    img = Image.open(file_path)
    img = ImageOps.exif_transpose(img)

    width = _to_int(width)
    height = _to_int(height)
    quality = _clamp_quality(quality)

    if width or height:
        if keep_aspect:
            if width and height:
                img = ImageOps.contain(img, (width, height))
            else:
                orig_w, orig_h = img.size
                if width:
                    height = max(1, round(orig_h * (width / orig_w)))
                else:
                    width = max(1, round(orig_w * (height / orig_h)))
                img = img.resize((width, height), Image.LANCZOS)
        else:
            width = width or img.size[0]
            height = height or img.size[1]
            img = img.resize((width, height), Image.LANCZOS)

    output = get_output_path(file_path, output_format)

    if output_format in {"jpg", "jpeg"}:
        img = img.convert("RGB")
        img.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
    elif output_format == "png":
        img.save(output, format="PNG", optimize=True)
    elif output_format == "webp":
        img.save(
            output,
            format="WEBP",
            quality=quality,
            method=6,
        )
    else:
        print("Unsupported format")
        return

    print(f"Converted to {output}")
