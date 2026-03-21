from utils import get_output_path
from pydub import AudioSegment

def convert_audio(file_path, output_format, progress_callback=None):
    audio = AudioSegment.from_file(file_path)

    output = get_output_path(file_path, output_format)

    if progress_callback:
        progress_callback(0.3)

    audio.export(output, format=output_format)

    if progress_callback:
        progress_callback(1.0)

    print(f"Converted to {output}")
