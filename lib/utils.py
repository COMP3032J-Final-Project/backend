import base64

def decode_base64url(s: str) -> bytes:
    """
    Decodes a Base64URL string (which might be missing padding) by
    adding the required padding before decoding.
    """
    missing_padding = len(s) % 4
    if missing_padding != 0:
        s += '=' * (4 - missing_padding)
    return base64.urlsafe_b64decode(s)




def is_likely_binary(data: bytes) -> bool:
    """
    Checks if the data likely represents a binary file by searching for null bytes.

    Binary files very often contain null bytes, which are extremely rare in plain text
    files (except potentially in specific encodings like UTF-16/UTF-32, but even then,
    their presence often indicates non-text data).
    """
    return b'\x00' in data
