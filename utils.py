import os

def get_output_path(input_path, new_extension):
    base = os.path.splitext(input_path)[0]
    return f"{base}.{new_extension}"

def file_exists(path):
    return os.path.exists(path)