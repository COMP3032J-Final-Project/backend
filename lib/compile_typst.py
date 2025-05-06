from __future__ import annotations

import os
import subprocess
# import uuid # Not strictly needed for this function, unlike the original template
from pathlib import Path
from typing import Optional

import botocore
from app.core.config import settings # Assuming your R2 settings are here
from app.core.r2client import r2client # Assuming your Boto3 client instance is here
from loguru import logger


def compile_typst(path_to_typ_file: str | Path, r2_remote_path: str) -> Optional[str]:
    """
    Compiles a Typst file using the typst CLI, uploads the resulting PDF to R2,
    and returns a presigned URL.

    Args:
        path_to_typ_file: The absolute path to the main .typ file.
        r2_remote_path: The desired object key (path) for the PDF in the R2 bucket.
                        e.g., "previews/project_id/commit_sha/main.pdf"

    Returns:
        A presigned URL for the generated PDF if successful, otherwise None.
    """
    path_to_typ_file = Path(path_to_typ_file).resolve() # Ensure absolute path

    if not path_to_typ_file.is_file():
        logger.error(f"Typst file not found: {path_to_typ_file}")
        return None

    cwd = path_to_typ_file.parent # Directory containing the .typ file
    typ_file_name = path_to_typ_file.name # e.g., "document.typ"
    file_name_alone = path_to_typ_file.stem # e.g., "document"
    pdf_file_name = f"{file_name_alone}.pdf" # e.g., "document.pdf"
    pdf_path = cwd / pdf_file_name # Absolute path to the expected PDF output

    # Typst command: typst compile <input.typ> <output.pdf>
    # We run it in the directory containing the input file so imports work correctly.
    # Typst generally provides good diagnostics directly to stderr.
    typst_command = [
        "typst",
        "compile",
        typ_file_name, # Input file relative to cwd
        pdf_file_name, # Output file relative to cwd
        # '--diagnostic-format', 'short' # Optional: for potentially cleaner error logs
    ]

    logger.info(f"Running typst for {typ_file_name} in {cwd}")
    logger.debug(f"Executing command: {' '.join(typst_command)}")

    try:
        process = subprocess.run(
            typst_command,
            cwd=str(cwd), # subprocess expects string paths
            capture_output=True,
            text=True,  # Decode stdout/stderr as text
            check=False,  # Manually check return code
            timeout=60,  # Typst is often faster, adjust timeout as needed (e.g., 1 minute)
        )

        # --- Check compilation result ---
        if process.returncode != 0:
            logger.error(f"typst compile failed for {typ_file_name} with return code {process.returncode}")
            # Typst errors are usually printed to stderr
            logger.error(f"STDOUT:\n{process.stdout}")
            logger.error(f"STDERR:\n{process.stderr}")

            # Clean up potentially generated PDF from failed run if it exists
            if pdf_path.exists():
                try:
                    os.remove(pdf_path)
                    logger.warning(f"Removed potentially incomplete PDF: {pdf_path}")
                except OSError as e:
                    logger.warning(f"Could not remove potentially incomplete PDF {pdf_path}: {e}")
            return None

        # --- Check if PDF was actually created ---
        if not pdf_path.exists():
            # This might happen if compilation succeeded (return code 0) but somehow didn't produce the expected output
            logger.error(f"typst compile completed successfully but PDF not found at: {pdf_path}")
            logger.error(f"STDOUT:\n{process.stdout}") # Log output for debugging
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
                    ExtraArgs={'ContentType': 'application/pdf'} # Good practice to set content type
                )

            # --- Generate Presigned URL ---
            presigned_url = r2client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": remote_key},
                ExpiresIn=settings.EXPIRATION_TIME, # Use expiration time from settings
            )
            logger.info(f"Generated presigned URL for {remote_key}")
            return presigned_url

        except botocore.exceptions.ClientError as error:
            logger.exception(f"R2 client error during upload or URL generation for {remote_key}: {error}")
            return None
        except Exception as e: # Catch other potential file IO errors during upload
            logger.exception(f"Error during file handling or R2 upload for {pdf_path}: {e}")
            return None
        finally:
            # --- Clean up local PDF file after successful upload (optional) ---
            if pdf_path.exists():
                 try:
                     os.remove(pdf_path)
                     logger.debug(f"Cleaned up local file: {pdf_path}")
                 except OSError as e:
                     logger.warning(f"Could not clean up local file {pdf_path}: {e}")

    except FileNotFoundError:
        logger.critical("Error: 'typst' command not found. Is Typst installed and in the system PATH?")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"typst compile command timed out for {typ_file_name}")
        # Attempt to clean up potentially partial PDF if it exists
        if pdf_path.exists():
             try:
                 os.remove(pdf_path)
             except OSError as e:
                 logger.warning(f"Could not remove timed-out PDF artifact {pdf_path}: {e}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during Typst compilation for {path_to_typ_file}: {e}")
        return None
    # No 'finally' block needed here unless there's cleanup required even on non-upload paths


# Example Usage (similar to your LaTeX example)
if __name__ == "__main__":
    # Create dummy files and folders for testing
    TEST_DIR = Path("/tmp/test_typst")
    TEST_DIR.mkdir(exist_ok=True)
    TEST_TYP_FILE = TEST_DIR / "main.typ"
    # A minimal valid Typst document
    TEST_TYP_FILE.write_text("#set page(width: 10cm)\nHello, Hivey!")

    # Assuming R2 client and settings are configured correctly
    # You might need to mock r2client and settings for unit testing
    try:
        # Replace with a realistic remote path structure
        remote_path = f"compiled/{TEST_TYP_FILE.stem}.pdf"
        url = compile_typst(str(TEST_TYP_FILE), remote_path) # Pass path as string or Path

        if url:
            print(f"Successfully compiled and uploaded. Presigned URL:")
            print(url)
        else:
            print("Typst compilation or upload failed.")

    finally:
        # Clean up test files
        import shutil
        if TEST_DIR.exists():
             shutil.rmtree(TEST_DIR)
        print("Cleaned up test directory.")

