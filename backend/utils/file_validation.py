from pathlib import Path

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}


def validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def validate_size(size: int, max_bytes: int) -> None:
    if size > max_bytes:
        mb = max_bytes / (1024 * 1024)
        raise ValueError(f"File exceeds maximum size of {mb:.0f} MB")
