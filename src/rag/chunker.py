import re

from pydantic import BaseModel

_HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_EFFECTIVE_DATE_RE = re.compile(r"Effective date:\s*(\d{4}-\d{2}-\d{2})")


class Chunk(BaseModel):
    section: str
    text: str


def chunk_markdown(text: str, preamble_section: str = "Overview") -> list[Chunk]:
    """Header-based (structural) chunking: splits on `## ` headers, one chunk
    per section, rather than an arbitrary size boundary. Keeps clauses intact
    -- appropriate here because every document in this corpus is short and was
    written/generated with deliberate section headers (see docs/DATA_SOURCES.md
    Sec 4). Content before the first header (title, effective date) becomes
    its own chunk.
    """
    matches = list(_HEADER_RE.finditer(text))

    chunks: list[Chunk] = []
    preamble = text[: matches[0].start()].strip() if matches else text.strip()
    if preamble:
        chunks.append(Chunk(section=preamble_section, text=preamble))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunks.append(Chunk(section=match.group(1).strip(), text=text[start:end].strip()))

    return chunks


def extract_effective_date(text: str) -> str:
    match = _EFFECTIVE_DATE_RE.search(text)
    return match.group(1) if match else ""
