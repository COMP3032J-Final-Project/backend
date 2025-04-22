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
