from converters.document_converter import convert_document
from converters.image_converter import convert_image
from converters.audio_converter import convert_audio
from converters.video_converter import convert_video

def get_format_options(file_path):
    lower = file_path.lower()
    if lower.endswith((".txt", ".csv")):
        return ["xlsx", "pdf"]
    if lower.endswith(".pdf"):
        return ["txt", "docx", "png", "jpg"]
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return ["jpg", "png"]
    if lower.endswith((".mp3", ".wav", ".ogg")):
        return ["mp3", "wav"]
    if lower.endswith((".mp4", ".avi", ".mov")):
        return ["mp4", "avi"]
    return []

def main():
    file_path = input("Enter file path: ")
    options = get_format_options(file_path)
    if not options:
        print("Unsupported file type")
        return

    print(f"Convert to ({', '.join(options)}): ", end="")
    output_format = input().strip().lower()
    if output_format not in options:
        print("Unsupported output format")
        return

    if file_path.endswith((".txt", ".csv", ".pdf")):
        convert_document(file_path, output_format)

    elif file_path.endswith((".png", ".jpg", ".jpeg", ".webp")):
        convert_image(file_path, output_format)

    elif file_path.endswith((".mp3", ".wav", ".ogg")):
        convert_audio(file_path, output_format)

    elif file_path.endswith((".mp4", ".avi", ".mov")):
        convert_video(file_path, output_format)

    else:
        print("Unsupported file type")

if __name__ == "__main__":
    main()
