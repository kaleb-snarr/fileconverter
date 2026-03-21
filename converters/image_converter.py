from utils import get_output_path
from PIL import Image

def convert_image(file_path, output_format):
    img = Image.open(file_path)

    output = get_output_path(file_path, output_format)

    if output_format == "jpg":
        img.convert("RGB").save(output)

    elif output_format == "png":
        img.save(output)

    else:
        print("Unsupported format")
        return

    print(f"Converted to {output}")
