from __future__ import annotations

import logging

logger = logging.getLogger("uvicorn.error")
import os
import subprocess
from subprocess import CalledProcessError
from watchdog.events import FileSystemEventHandler

from .config import settings


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
            logger.info(f"Tex file has been modified: {event.src_path} ")

            build_pdflatex_bibtex(event.src_path)
