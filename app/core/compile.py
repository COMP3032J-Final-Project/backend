from __future__ import annotations

import logging

logger = logging.getLogger("uvicorn.error")
import logging
import os
import subprocess
from subprocess import CalledProcessError
from uuid import UUID

import botocore
from watchdog.events import FileSystemEventHandler

from .config import settings
from .r2client import r2client

logger = logging.getLogger("uvicorn.error")


def build_pdflatex_bibtex(path_to_tex_file: str) -> str:
    """
    Parameters
    ----------
    path_to_tex_file

    Returns
    -------
    url

    """
    cwd = os.path.dirname(path_to_tex_file)
    tex_file_name = os.path.basename(path_to_tex_file)
    file_name_alone, _ = os.path.splitext(tex_file_name)

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
        logger.info(msg)
        return ""

    pdf_path = f"{file_name_alone}.pdf"
    remote_path = f"compiled/{UUID}"
    # frp = FileDAO.get_remote_file_path(file_id)

    if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as file:
            try:
                r2client.upload_fileobj(file, Bucket=settings.R2_BUCKET, Key=remote_path)
                response = r2client.generate_presigned_url(
                    "get_object", Params={"Bucket": settings.R2_BUCKET, "Key": remote_path}, ExpiresIn=3600
                )
                return response

            except botocore.exceptions.ClientError as error:
                logger.error(error)

    return ""


class MyHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".tex"):
            logger.info(f"Tex file has been modified: {event.src_path} ")
            url = build_pdflatex_bibtex(event.src_path)

            # todo: something to alert the sccket
