from __future__ import annotations

import os
import subprocess
from subprocess import CalledProcessError

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def build_pdflatex_bibtex(path_to_tex_file: str):
    """
    Parameters
    ----------
    path_to_tex_file

    Returns
    -------

    """
    cwd = os.path.dirname(path_to_tex_file)
    tex_file_name = os.path.basename(path_to_tex_file)
    file_name_alone, _ = os.path.splitext(tex_file_name)
    print(cwd, tex_file_name)
    try:
        subprocess.run(
            f"pdflatex -synctex=1 -interaction=nonstopmode {file_name_alone}.tex",
            cwd=cwd,
            capture_output=True,
        )
        subprocess.run(f"bibtex {file_name_alone}", cwd=cwd, capture_output=True)
        subprocess.run(
            f"pdflatex -synctex=1 -interaction=nonstopmode {file_name_alone}.tex",
            cwd=cwd,
            capture_output=True,
        )
    except CalledProcessError as error:
        msg = f"compile resulted in error:\n{error.stdout}\n{error.stderr}"
        return msg

    return "compile success"  # 这里可以考虑替换成具体的compile log等等


class MyHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".tex"):
            print(f"File {event.src_path} has been modified!")

            build_pdflatex_bibtex(event.src_path)


# Create observer and event handler
observer = Observer()
event_handler = MyHandler()

# Set up observer to watch a specific directory
directory_to_watch = "./templates"
observer.schedule(event_handler, directory_to_watch, recursive=True)

# Start the observer
observer.start()

# Keep the script running
try:
    while True:
        pass
    # if __name__ == "__main__":
    #     print(build_pdflatex_bibtex(os.path.join("simple_article", "simple_article.tex")))

except KeyboardInterrupt:
    observer.stop()

observer.join()
