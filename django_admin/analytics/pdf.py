"""A very small PDF writer for tabular reports.

Deliberately dependency-free: report exports shouldn't drag reportlab (and a
C toolchain on some platforms) into the deployment just to draw a table of
text. It supports exactly what the reports need — a title block, a header
row, paginated rows, page numbers — using the base-14 Helvetica fonts every
PDF reader has built in.

Text is encoded as WinAnsi (cp1252), which has no rupee sign, so callers
write amounts as "INR 1,234.00" rather than "₹1,234.00".
"""
from datetime import datetime

PAGE_SIZES = {"a4": (595.28, 841.89), "letter": (612.0, 792.0)}


def _escape(text: str) -> bytes:
    """PDF string literal: backslash-escape the delimiters, drop what
    WinAnsi can't represent (rather than raising mid-report)."""
    encoded = str(text).encode("cp1252", "replace")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _width(text: str, size: float, bold: bool = False) -> float:
    """Rough string width in points. Helvetica averages ~0.5 em per character
    (~0.55 when bold), which is close enough to decide truncation."""
    return len(str(text)) * size * (0.55 if bold else 0.5)


def _truncate(text: str, size: float, limit: float, bold: bool = False) -> str:
    text = str(text)
    if _width(text, size, bold) <= limit:
        return text
    while text and _width(text + "…", size, bold) > limit:
        text = text[:-1]
    return text + "…" if text else ""


class PdfReport:
    """Build a landscape table report.

    columns: list of (heading, width_in_points, align) where align is
    "left" or "right".
    """

    def __init__(self, title, subtitle="", columns=(), page_size="a4", landscape=True):
        width, height = PAGE_SIZES[page_size]
        self.page_w, self.page_h = (height, width) if landscape else (width, height)
        self.title = title
        self.subtitle = subtitle
        self.margin = 36
        # Column widths are requested in points, but a report whose columns
        # add up to more than the page has runs off the right edge and its
        # text collides. Scale them all down to fit instead.
        requested = sum(width for _heading, width, _align in columns) or 1
        available = self.page_w - 2 * self.margin
        scale = min(1.0, available / requested)
        self.columns = [(heading, width * scale, align) for heading, width, align in columns]
        self.row_height = 16
        self.font_size = 9
        self._pages = []          # each page is a list of content operators
        self._current = None
        self._y = 0

    # ---- drawing helpers -------------------------------------------------
    def _text(self, x, y, value, size=9, bold=False, gray=0.0):
        self._current.append(
            b"BT /%s %g Tf %g g %g %g Td (%s) Tj ET"
            % (b"F2" if bold else b"F1", size, gray, x, y, _escape(value))
        )

    def _line(self, y, gray=0.8):
        self._current.append(
            b"%g G 0.5 w %g %g m %g %g l S" % (gray, self.margin, y, self.page_w - self.margin, y)
        )

    def _new_page(self):
        self._current = []
        self._pages.append(self._current)
        self._y = self.page_h - self.margin

        self._text(self.margin, self._y - 14, self.title, size=16, bold=True)
        self._y -= 32
        if self.subtitle:
            self._text(self.margin, self._y, self.subtitle, size=9, gray=0.35)
            self._y -= 18
        self._header_row()

    def _header_row(self):
        x = self.margin
        for heading, width, align in self.columns:
            value = _truncate(heading, self.font_size, width - 6, bold=True)
            offset = width - 6 - _width(value, self.font_size, True) if align == "right" else 0
            self._text(x + offset, self._y, value, size=self.font_size, bold=True)
            x += width
        self._y -= 6
        self._line(self._y)
        self._y -= self.row_height

    # ---- public API ------------------------------------------------------
    def add_rows(self, rows):
        for row in rows:
            if self._current is None or self._y < self.margin + self.row_height:
                self._new_page()
            x = self.margin
            for value, (_heading, width, align) in zip(row, self.columns):
                text = _truncate(value, self.font_size, width - 6)
                offset = width - 6 - _width(text, self.font_size) if align == "right" else 0
                self._text(x + offset, self._y, text, size=self.font_size)
                x += width
            self._y -= self.row_height

    def add_summary(self, lines):
        """A block of "label: value" lines under the table."""
        if self._current is None:
            self._new_page()
        if self._y < self.margin + self.row_height * (len(lines) + 2):
            self._new_page()
        self._y -= 6
        self._line(self._y)
        self._y -= self.row_height + 2
        for line in lines:
            self._text(self.margin, self._y, line, size=10, bold=True)
            self._y -= self.row_height

    def render(self) -> bytes:
        if self._current is None:
            self._new_page()
            self._text(self.margin, self._y, "No rows matched this report.", size=10, gray=0.35)

        total = len(self._pages)
        for number, page in enumerate(self._pages, start=1):
            self._current = page
            footer = f"Page {number} of {total} · generated {datetime.utcnow():%Y-%m-%d %H:%M} UTC"
            self._text(self.margin, self.margin - 14, footer, size=8, gray=0.45)
        return self._assemble()

    # ---- file structure --------------------------------------------------
    def _assemble(self) -> bytes:
        objects = []            # 1-indexed list of object bodies

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        pages_id = add(b"")     # filled in once the page ids are known

        page_ids = []
        for page in self._pages:
            stream = b"\n".join(page)
            contents_id = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
            page_ids.append(add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %g %g] "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_id, self.page_w, self.page_h, font_regular, font_bold, contents_id)
            ))

        kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
        objects[pages_id - 1] = b"<< /Type /Pages /Count %d /Kids [%s] >>" % (len(page_ids), kids)
        catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
        info_id = add(
            b"<< /Title (%s) /Producer (Smart E-Commerce Platform) /CreationDate (D:%s) >>"
            % (_escape(self.title), datetime.utcnow().strftime("%Y%m%d%H%M%S").encode())
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (len(objects) + 1)
        for number, body in enumerate(objects, start=1):
            offsets[number] = len(out)
            out += b"%d 0 obj\n%s\nendobj\n" % (number, body)

        xref_at = len(out)
        out += b"xref\n0 %d\n" % (len(objects) + 1)
        out += b"0000000000 65535 f \n"
        for number in range(1, len(objects) + 1):
            out += b"%010d 00000 n \n" % offsets[number]
        out += (
            b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, catalog_id, info_id, xref_at)
        )
        return bytes(out)
