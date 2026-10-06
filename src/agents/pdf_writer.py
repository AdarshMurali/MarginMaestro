"""A minimal PDF writer for the margin-call notice (MM-144). Pure Python, no
dependency: text only, in the PDF standard fonts Helvetica and
Helvetica-Bold (every viewer has them, so nothing is embedded), WinAnsi
encoding, A4 pages, word wrap, two-column figure tables and a footer on
every page. Content streams are uncompressed: a notice is a few KB and the
tests can read the text straight out of the file.

Not a general PDF library -- the notice is the only document it lays out.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

PAGE_WIDTH = 595.0  # A4, points
PAGE_HEIGHT = 842.0
MARGIN = 56.0
FOOTER_Y = 32.0
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
REGULAR, BOLD = "F1", "F2"
# Helvetica-Bold is wider than Helvetica; measuring bold text 10% wide keeps
# wrapped bold lines inside the margin without a second width table.
BOLD_FACTOR = 1.1

# Helvetica advance widths (1/1000 em) for WinAnsi codes 32-126, from the
# Adobe core-14 font metrics. Anything else is measured as 556 (a digit).
_HELVETICA = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]  # fmt: skip
_DEFAULT_WIDTH = 556


def text_width(text: str, size: float, bold: bool = False) -> float:
    units = 0
    for byte in _encode(text):
        units += _HELVETICA[byte - 32] if 32 <= byte <= 126 else _DEFAULT_WIDTH
    return units * size / 1000 * (BOLD_FACTOR if bold else 1.0)


def _encode(text: str) -> bytes:
    return text.encode("cp1252", errors="replace")


def _literal(text: str) -> bytes:
    """A PDF string literal: (..) with \\, ( and ) escaped, and anything
    outside printable ASCII as an octal escape."""
    out = bytearray(b"(")
    for byte in _encode(text):
        if byte in (0x5C, 0x28, 0x29):
            out += b"\\" + bytes([byte])
        elif 32 <= byte <= 126:
            out.append(byte)
        else:
            out += f"\\{byte:03o}".encode("ascii")
    out += b")"
    return bytes(out)


def wrap(text: str, size: float, width: float, bold: bool = False) -> list[str]:
    """Greedy word wrap; a word longer than the line is broken."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if text_width(candidate, size, bold) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        while text_width(word, size, bold) > width:
            cut = len(word)
            while cut > 1 and text_width(word[:cut], size, bold) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


@dataclass
class _Page:
    ops: list[bytes] = field(default_factory=list)


class PdfDocument:
    """Lays text out top to bottom, starting a new page when one is full."""

    def __init__(self, title: str, footer: str) -> None:
        self.title = title
        self.footer = footer
        self._pages: list[_Page] = []
        self._y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self._pages.append(_Page())
        self._y = PAGE_HEIGHT - MARGIN

    def _ensure(self, height: float) -> None:
        if self._y - height < FOOTER_Y + 24:
            self._new_page()

    def _text_at(self, x: float, y: float, text: str, size: float, bold: bool) -> None:
        font = BOLD if bold else REGULAR
        self._pages[-1].ops.append(
            b"BT /%s %.1f Tf %.2f %.2f Td %s Tj ET" % (font.encode(), size, x, y, _literal(text))
        )

    def space(self, height: float) -> None:
        self._y -= height

    def paragraph(
        self, text: str, size: float = 10, bold: bool = False, indent: float = 0.0
    ) -> None:
        leading = size * 1.35
        for line in wrap(text, size, CONTENT_WIDTH - indent, bold):
            self._ensure(leading)
            self._y -= leading
            self._text_at(MARGIN + indent, self._y, line, size, bold)

    def heading(self, text: str, size: float = 13) -> None:
        self._ensure(size * 3)  # keep a heading with the line after it
        self.space(size * 0.6)
        self.paragraph(text, size=size, bold=True)
        self.space(size * 0.3)

    def rule(self) -> None:
        self._ensure(8)
        self._y -= 6
        self._pages[-1].ops.append(
            b"0.6 w %.2f %.2f m %.2f %.2f l S" % (MARGIN, self._y, PAGE_WIDTH - MARGIN, self._y)
        )
        self._y -= 4

    def figures(
        self, rows: Sequence[tuple[str, str]], size: float = 10, bold_last: bool = False
    ) -> None:
        """Label on the left (wrapped), value right-aligned on the right."""
        value_width = max((text_width(v, size, True) for _, v in rows), default=0.0)
        label_width = CONTENT_WIDTH - value_width - 16
        leading = size * 1.45
        for index, (label, value) in enumerate(rows):
            bold = bold_last and index == len(rows) - 1
            label_lines = wrap(label, size, label_width, bold)
            self._ensure(leading * len(label_lines))
            for line_no, line in enumerate(label_lines):
                self._y -= leading
                self._text_at(MARGIN, self._y, line, size, bold)
                if line_no == 0:
                    x = PAGE_WIDTH - MARGIN - text_width(value, size, bold)
                    self._text_at(x, self._y, value, size, bold)

    def render(self) -> bytes:
        """The finished file: catalog, page tree, two fonts, one content
        stream per page (with the footer and page number), info, xref."""
        total = len(self._pages)
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")  # filled in once the page tree's number is known
        pages_obj = add(b"")
        font_regular = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
        font_bold = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        page_ids: list[int] = []
        for number, page in enumerate(self._pages, start=1):
            footer = f"{self.footer}  |  page {number} of {total}"
            ops = [
                *page.ops,
                b"BT /%s 8.0 Tf %.2f %.2f Td %s Tj ET"
                % (REGULAR.encode(), MARGIN, FOOTER_Y, _literal(footer)),
            ]
            stream = b"\n".join(ops)
            content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
            page_ids.append(
                add(
                    b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                    b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                    % (pages_obj, PAGE_WIDTH, PAGE_HEIGHT, font_regular, font_bold, content)
                )
            )
        kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
        objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, total)
        objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
        info = add(b"<< /Title %s /Producer (MarginMaestro) >>" % _literal(self.title))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1,
            catalog,
            info,
            xref,
        )
        return bytes(out)
