from utils import get_output_path
from moviepy import VideoFileClip

def convert_video(file_path, output_format, progress_callback=None):
    clip = VideoFileClip(file_path)
    duration = clip.duration  # total seconds

    def progress_bar(current_time):
        if progress_callback:
            percent = current_time / duration
            progress_callback(percent)

    output = get_output_path(file_path, output_format)

    clip.write_videofile(
        output,
        logger=None,
        verbose=False,
        progress_bar=False,
        callback=progress_bar
    )

    if progress_callback:
        progress_callback(1.0)

    print(f"Converted to {output}")
