from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import botocore
from app.core.config import settings
from app.core.r2client import r2client
from loguru import logger


def compile_latex_with_latexmk(path_to_tex_file: str | Path, r2_remote_path: str) -> Optional[str]:
    """
    Compiles a LaTeX file using latexmk, uploads the resulting PDF to R2,
    and returns a presigned URL.

    Args:
        path_to_tex_file: The absolute path to the main .tex file.
        The cwd of the compiling service is at the the parent folder of path_to_tex_file

    Returns:
        A presigned URL for the generated PDF if successful, otherwise None.
    """
    if not os.path.exists(path_to_tex_file):
        logger.error(f"LaTeX file not found: {path_to_tex_file}")
        return None

    cwd = os.path.dirname(path_to_tex_file)
    tex_file_name = os.path.basename(path_to_tex_file)
    file_name_alone, _ = os.path.splitext(tex_file_name)
    pdf_file_name = f"{file_name_alone}.pdf"
    pdf_path = os.path.join(cwd, pdf_file_name)
    log_file_path = os.path.join(cwd, f"{file_name_alone}.log")

    latexmk_command = [
        "latexmk",
        "-pdf",
        "-synctex=1",  # Enable SyncTeX
        "-interaction=nonstopmode",  # Don't stop on errors within LaTeX run
        "-file-line-error",  # Produce file:line:error style messages
        "-halt-on-error",  # Exit latexmk immediately if LaTeX errors occur
        tex_file_name,
    ]

    logger.info(f"Running latexmk for {tex_file_name} in {cwd}")
    logger.debug(f"Executing command: {' '.join(latexmk_command)}")

    try:
        process = subprocess.run(
            latexmk_command,
            cwd=cwd,
            capture_output=True,
            text=True,  # Decode stdout/stderr as text
            check=False,  # Manually check return code instead of raising CalledProcessError
            timeout=120,  # Add a timeout (e.g., 2 minutes) to prevent hangs
        )

        # --- Check compilation result ---
        if process.returncode != 0:
            logger.error(f"latexmk failed for {tex_file_name} with return code {process.returncode}")
            logger.error(f"STDOUT:\n{process.stdout}")
            logger.error(f"STDERR:\n{process.stderr}")
            # Optionally, try to read and log relevant lines from the .log file
            # if os.path.exists(log_file_path):
            #      try:
            #          with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as log_f:
            #              log_content = log_f.read()[-2000:] # Get last 2000 chars as a snippet
            #              logger.error(f"Tail of log file ({log_file_path}):\n{log_content}")
            #      except Exception as log_err:
            #          logger.error(f"Could not read log file {log_file_path}: {log_err}")

            # Clean up potentially generated PDF from failed run if it exists
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except OSError as e:
                    logger.warning(f"Could not remove potentially incomplete PDF {pdf_path}: {e}")
            return None

        # --- Check if PDF was actually created ---
        if not os.path.exists(pdf_path):
            logger.error(f"latexmk completed successfully but PDF not found at: {pdf_path}")
            logger.error(f"STDOUT:\n{process.stdout}")  # Log output for debugging
            logger.error(f"STDERR:\n{process.stderr}")
            return None

        logger.info(f"Successfully compiled {pdf_file_name}")

        # --- Upload to R2 ---
        remote_key = r2_remote_path

        logger.info(f"Uploading {pdf_file_name} to R2 bucket {settings.R2_BUCKET} with key {remote_key}")

        try:
            with open(pdf_path, "rb") as pdf_file:
                r2client.upload_fileobj(
                    pdf_file,
                    Bucket=settings.R2_BUCKET,
                    Key=remote_key,
                    # Optional: Add metadata like ContentType
                    # ExtraArgs={'ContentType': 'application/pdf'}
                )

            # --- Generate Presigned URL ---
            presigned_url = r2client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": remote_key},
                ExpiresIn=settings.EXPIRATION_TIME,
            )
            logger.info(f"Generated presigned URL for {remote_key}")
            return presigned_url

        except botocore.exceptions.ClientError as error:
            logger.exception(f"R2 client error during upload or URL generation for {remote_key}: {error}")
            return None  # Indicate failure
        except Exception as e:  # Catch other potential file IO errors
            logger.exception(f"Error during file handling or R2 upload for {pdf_path}: {e}")
            return None

    except FileNotFoundError:
        logger.critical("Error: 'latexmk' command not found. Is TeX Live or MiKTeX installed and in the system PATH?")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"latexmk command timed out for {tex_file_name}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during LaTeX compilation for {path_to_tex_file}: {e}")
        return None
    finally:
        pass


if __name__ == "__main__":
    tex_file = "Path to Latex File"
    url = compile_latex_with_latexmk(tex_file)
    print(url)
