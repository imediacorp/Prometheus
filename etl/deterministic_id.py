import hashlib


def generate_id(source: str, ext_id: str) -> str:
    raw = f"{source}:{ext_id}".encode("utf-8")
    return f"SRC-{hashlib.sha256(raw).hexdigest()[:12]}"
