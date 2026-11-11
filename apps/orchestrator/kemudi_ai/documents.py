"""Contract files (PDF, DOCX) to numbered sections the AI can cite."""

import io
import re
from collections import Counter

from pydantic import BaseModel


class Section(BaseModel):
    ref: str
    title: str
    text: str


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(data))
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(lines)
    raise ValueError(f"unsupported file type: {filename} (PDF or DOCX only)")


# OCR on scanned contracts reads a capital I as a lowercase l. No Indonesian
# or English word starts with "ln", so "lntegrasi" is always "Integrasi".
_OCR_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bln(?=[a-z])"), "In"),
    (re.compile(r"\bTennin\b"), "Termin"),
    (re.compile(r"\bORIS\b"), "QRIS"),
    (re.compile(r"(\d) \.(\d{3})"), r"\1.\2"),  # "Rp 35 .000.000"
]


def normalize(text: str) -> str:
    for pattern, repl in _OCR_FIXES:
        text = pattern.sub(repl, text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines())


def _drop_page_headers(lines: list[str]) -> list[str]:
    """Running headers repeat on every page, with OCR noise in each copy."""
    keys = Counter(line[:24].lower() for line in lines if len(line) > 30)
    return [l for l in lines if not (len(l) > 30 and keys[l[:24].lower()] >= 3)]


_HEADING = re.compile(r"^[A-Z0-9&/(),.\- ]{6,70}$")


def _is_heading(line: str) -> bool:
    words = [w for w in line.split() if re.search(r"[A-Z]{2,}", w)]
    return bool(_HEADING.match(line)) and len(words) >= 2 and not re.search(
        r"\d{3}", line
    )


def split_sections(text: str) -> list[Section]:
    lines = _drop_page_headers([l for l in text.splitlines() if l.strip()])
    sections: list[tuple[str, list[str]]] = []
    title, body = "", []
    for line in lines:
        if _is_heading(line):
            if body or title:
                sections.append((title, body))
            title, body = line, []
        else:
            body.append(line)
    if body or title:
        sections.append((title, body))
    return [
        Section(ref=f"S{i}", title=t or "Pembuka", text="\n".join(b).strip())
        for i, (t, b) in enumerate(sections, 1)
    ]


def extract_sections(filename: str, data: bytes) -> list[Section]:
    return split_sections(normalize(extract_text(filename, data)))
