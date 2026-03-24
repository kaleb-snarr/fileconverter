from converters.image_converter import convert_image

def main():
    file_path = input("Enter file path: ")
    if not file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        print("Unsupported file type. Please use an image (PNG/JPG/JPEG/WEBP).")
        return

    options = ["jpg", "png", "webp"]
    print(f"Convert to ({', '.join(options)}): ", end="")
    output_format = input().strip().lower()
    if output_format not in options:
        print("Unsupported output format")
        return

    width = input("Resize width in px (optional): ").strip()
    height = input("Resize height in px (optional): ").strip()
    quality = input("Quality 1-100 (default 85): ").strip() or "85"

    convert_image(file_path, output_format, width=width, height=height, quality=quality)

if __name__ == "__main__":
    main()
