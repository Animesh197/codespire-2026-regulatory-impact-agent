from pathlib import Path

import fitz  # PyMuPDF
from docx import Document

from backend.utils.text_clean import clean_text


def extract_from_pdf(path: Path) -> str:
    doc = fitz.open(path)
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text"))
    doc.close()
    return clean_text("\n\n".join(parts))


def extract_from_txt(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return clean_text(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return clean_text(raw.decode("utf-8", errors="replace"))


def extract_from_docx(path: Path) -> str:
    document = Document(path)
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return clean_text("\n\n".join(paragraphs))


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_from_pdf(path)
    if suffix == ".txt":
        return extract_from_txt(path)
    if suffix == ".docx":
        return extract_from_docx(path)
    raise ValueError(f"Unsupported extraction for {suffix}")
