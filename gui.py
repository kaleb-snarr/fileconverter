import os

# Ensure Tk can find tkdnd from a readable location (ProgramData).
_tkdnd_dir = r"C:\ProgramData\tkdnd\win-x64"
_tcllibpath = os.environ.get("TCLLIBPATH", "")
if os.path.isdir(_tkdnd_dir) and _tkdnd_dir not in _tcllibpath:
    os.environ["TCLLIBPATH"] = f"{_tcllibpath} {_tkdnd_dir}".strip()

import customtkinter as ctk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD

from converters.document_converter import convert_document
from converters.image_converter import convert_image
from converters.audio_converter import convert_audio
from converters.video_converter import convert_video

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()

        self.title("File Converter Pro")
        self.geometry("600x400")

        self.selected_file = ""
        self.selected_format = ctk.StringVar()

        # Title
        self.title_label = ctk.CTkLabel(self, text="File Converter", font=("Segoe UI", 24))
        self.title_label.pack(pady=20)

        # Drag & Drop Area (boxed)
        self.drop_box = ctk.CTkFrame(
            self,
            width=420,
            height=140,
            corner_radius=12,
            border_width=2,
            border_color="#7a7a7a"
        )
        self.drop_box.pack(pady=10)
        self.drop_box.pack_propagate(False)

        self.drop_area = ctk.CTkLabel(
            self.drop_box,
            text="Drag & Drop File Here",
            width=400,
            height=120,
            corner_radius=8
        )
        self.drop_area.pack(expand=True)

        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind("<<Drop>>", self.handle_drop)

        # File label
        self.file_label = ctk.CTkLabel(self, text="No file selected")
        self.file_label.pack(pady=5)

        # Dropdown label
        self.format_label = ctk.CTkLabel(self, text="Convert to")
        self.format_label.pack(pady=(5, 0))

        # Dropdown
        self.format_dropdown = ctk.CTkComboBox(self, variable=self.selected_format, values=[])
        self.format_dropdown.pack(pady=10)

        # Buttons
        self.convert_button = ctk.CTkButton(self, text="Convert File", command=self.convert_file)
        self.convert_button.pack(pady=10)

        self.folder_button = ctk.CTkButton(self, text="Select a Folder", command=self.convert_folder)
        self.folder_button.pack(pady=5)

        # Progress bar
        self.progress = ctk.CTkProgressBar(self, width=300)
        self.progress.pack(pady=15)
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(self, text="0%")
        self.progress_label.pack()


    def handle_drop(self, event):
        self.selected_file = event.data.strip("{}")
        self.file_label.configure(text=self.selected_file)
        self.set_format_options()

    def set_format_options(self):
        if self.selected_file.endswith((".png", ".jpg", ".jpeg", ".webp")):
            options = ["jpg", "png"]

        elif self.selected_file.endswith((".mp3", ".wav", ".ogg")):
            options = ["mp3", "wav"]

        elif self.selected_file.endswith((".mp4", ".avi", ".mov")):
            options = ["mp4", "avi"]

        elif self.selected_file.endswith((".csv", ".txt")):
            options = ["xlsx", "pdf"]

        elif self.selected_file.endswith(".pdf"):
            options = ["txt", "docx", "png", "jpg"]

        else:
            options = []

        self.format_dropdown.configure(values=options)

        if options:
            self.selected_format.set(options[0])

    def convert_file(self):
        if not self.selected_file:
            messagebox.showerror("Error", "No file selected")
            return

        fmt = self.selected_format.get()

        try:
            self.update_progress(0)

            if self.selected_file.endswith((".txt", ".csv")):
                convert_document(self.selected_file, fmt)

            elif self.selected_file.endswith((".png", ".jpg", ".jpeg", ".webp")):
                convert_image(self.selected_file, fmt)

            elif self.selected_file.endswith((".mp3", ".wav", ".ogg")):
                convert_audio(self.selected_file, fmt, self.update_progress)

            elif self.selected_file.endswith((".mp4", ".avi", ".mov")):
                convert_video(self.selected_file, fmt, self.update_progress)

            self.update_progress(1.0)

            messagebox.showinfo("Success!", f"Converted to {fmt}")

        except Exception as e:
            self.update_progress(0)
            messagebox.showerror("Error", str(e))


    def convert_folder(self):
        folder = filedialog.askdirectory()

        if not folder:
            return

        fmt = self.selected_format.get()

        try:
            self.progress.start()

            for file in os.listdir(folder):
                path = os.path.join(folder, file)

                if path.endswith((".txt", ".csv", ".pdf")):
                    convert_document(path, fmt)

                elif path.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    convert_image(path, fmt)

                elif path.endswith((".mp3", ".wav", ".ogg")):
                    convert_audio(path, fmt)

                elif path.endswith((".mp4", ".avi", ".mov")):
                    convert_video(path, fmt)

            self.progress.stop()
            self.progress.set(1)

            messagebox.showinfo("Success!", "Folder converted")

        except Exception as e:
            self.progress.stop()
            messagebox.showerror("Error", str(e))

    def update_progress(self, value):
        self.progress.set(value)
        self.progress_label.configure(text=f"{int(value * 100)}%")
        self.update_idletasks()



if __name__ == "__main__":
    app = App()
    app.mainloop()
