"""Builds the output PDF from a scanned PDF, one output page per input page.

Two output modes:
- MODE_TEXT:    a new PDF with only the extracted text, laid out where it was on the scan.
                Images, logos and other graphics are dropped.
- MODE_OVERLAY: the original scan with an invisible, searchable text layer on top.
"""
from __future__ import annotations

import html
import os
import re
import unicodedata
from pathlib import Path
from typing import Callable, Protocol

import pymupdf
from bidi import get_display

from .gemini_ocr import Line

MODE_TEXT = "text"
MODE_OVERLAY = "overlay"

# Fonts for the invisible (searchable) text layer, in order of preference: common Windows fonts,
# then the Noto fonts bundled inside MuPDF (one per script: Arabic, Devanagari, Bengali, Tamil,
# Thai, Hebrew, CJK, ...), so every script is covered even on PCs without extra fonts installed.
_WIN_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONT_FILES = [_WIN_FONTS / "arial.ttf", _WIN_FONTS / "segoeui.ttf"]
BUILTIN_SCRIPTS = range(1, 40)  # UCDN script codes; MuPDF has a bundled Noto font for most
_base_fonts: dict[str, pymupdf.Font | None] = {}
RENDER_INVISIBLE = 3
LINE_HEIGHT = 1.2          # CSS line-height used for visible text; font size = box height / this
SCAN_IMAGE_COVERAGE = 0.5  # a page whose images cover this much of it is treated as a scan
MAX_RENDER_PIXELS = 3500   # longest side of the image sent to OCR, whatever the DPI setting
_WHITESPACE = re.compile(r"\s+")


class Ocr(Protocol):
    def extract_page(self, png: bytes) -> list[Line]: ...


class Cancelled(Exception):
    pass


class _Font:
    def __init__(self, name: str, font: pymupdf.Font):
        self.name = name
        self.font = font
        # glyph id -> character actually written with it; used to repair the ToUnicode map
        self.used: dict[int, str] = {}

    def covers(self, text: str) -> bool:
        return all(ch == " " or self.font.has_glyph(ord(ch)) for ch in text)

    def ensure_on(self, page: pymupdf.Page) -> None:
        if not any(f[4] == self.name for f in page.get_fonts()):
            page.insert_font(fontname=self.name, fontbuffer=self.font.buffer)

    def record(self, text: str) -> None:
        for ch in text:
            gid = self.font.has_glyph(ord(ch))
            if gid:
                self.used.setdefault(gid, ch)


def _base_font(key: str) -> pymupdf.Font | None:
    if key not in _base_fonts:
        kind, value = key.split(":", 1)
        try:
            _base_fonts[key] = pymupdf.Font(fontfile=value) if kind == "file" else pymupdf.Font(script=int(value))
        except Exception:
            _base_fonts[key] = None
    return _base_fonts[key]


class FontSet:
    """The text-layer fonts of one output document, loaded lazily in order of preference."""

    def __init__(self):
        self._keys = [f"file:{p}" for p in FONT_FILES if p.exists()]
        self._keys += [f"script:{n}" for n in BUILTIN_SCRIPTS]
        self._next_key = 0
        self._names: set[str] = set()
        self.loaded: list[_Font] = []

    def _candidates(self):
        yield from self.loaded
        while self._next_key < len(self._keys):
            base = _base_font(self._keys[self._next_key])
            self._next_key += 1
            if base is None or base.name in self._names:
                continue
            self._names.add(base.name)
            font = _Font(f"ocr{len(self.loaded)}", base)
            self.loaded.append(font)
            yield font

    def for_text(self, text: str) -> _Font:
        """The first font that covers all of `text`, else the one for its first character."""
        for font in self._candidates():
            if font.covers(text):
                return font
        return self.for_char(text.strip()[:1] or " ")

    def for_char(self, ch: str) -> _Font:
        for font in self._candidates():
            if font.font.has_glyph(ord(ch)):
                return font
        return self.loaded[0]

    def runs(self, text: str) -> list[tuple[_Font, str]]:
        """Split `text` into runs that can each be written with a single font."""
        runs: list[tuple[_Font, str]] = []
        for ch in text:
            if runs and (ch == " " or runs[-1][0].font.has_glyph(ord(ch))):
                runs[-1] = (runs[-1][0], runs[-1][1] + ch)
            else:
                runs.append((self.for_char(ch), ch))
        return runs

# ---- conversion ------------------------------------------------------------------------------


def convert(
    src: str | Path,
    dst: str | Path,
    ocr: Ocr,
    mode: str = MODE_TEXT,
    dpi: int = 200,
    should_stop: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> tuple[int, int]:
    """Convert `src` into `dst` (same number of pages). Returns (pages, pages sent to OCR)."""
    dst = Path(dst)
    tmp = dst.with_name(dst.name + ".tmp")
    fonts = FontSet()
    written: list[int] = []  # numbers of output pages that received a text layer
    ocr_count = 0

    with pymupdf.open(src) as doc:
        if doc.needs_pass:
            raise ValueError("the PDF is password-protected")
        out = pymupdf.open() if mode == MODE_TEXT else doc
        try:
            total = doc.page_count
            for index, page in enumerate(doc):
                if should_stop():
                    raise Cancelled()
                progress(index, total)

                has_text = bool(page.get_text("text").strip())
                if mode == MODE_TEXT:
                    if has_text and not _is_scan(page):
                        lines = existing_lines(page)  # born-digital page: reuse its text as is
                    else:
                        lines = ocr.extract_page(_render(page, dpi))
                        ocr_count += 1
                    target = out.new_page(width=page.rect.width, height=page.rect.height)
                    draw_visible_text(target, lines)
                else:
                    if has_text:
                        continue  # already searchable
                    lines = ocr.extract_page(_render(page, dpi))
                    ocr_count += 1
                    target = page
                add_text_layer(target, lines, fonts)
                written.append(target.number)
            progress(total, total)

            fix_to_unicode(out, written, fonts)
            out.subset_fonts()
            try:
                out.save(tmp, garbage=3, deflate=True)
                os.replace(tmp, dst)
            finally:
                tmp.unlink(missing_ok=True)
        finally:
            if out is not doc:
                out.close()
    return total, ocr_count


def _render(page: pymupdf.Page, dpi: int) -> bytes:
    longest = max(page.rect.width, page.rect.height) / 72 * dpi
    if longest > MAX_RENDER_PIXELS:  # very large sheets: keep the upload a sensible size
        dpi = max(36, int(dpi * MAX_RENDER_PIXELS / longest))
    return page.get_pixmap(dpi=dpi).tobytes("png")


def _is_scan(page: pymupdf.Page) -> bool:
    area = abs(page.rect)
    covered = sum(abs(pymupdf.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return area > 0 and covered / area >= SCAN_IMAGE_COVERAGE


def existing_lines(page: pymupdf.Page) -> list[Line]:
    """Text lines already present in a (born-digital) page, in the same form OCR returns them."""
    vis, rot = page.rect, page.rotation_matrix
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            r = (pymupdf.Rect(line["bbox"]) * rot) & vis
            if r.is_empty:
                continue
            box = (
                round((r.y0 - vis.y0) / vis.height * 1000),
                round((r.x0 - vis.x0) / vis.width * 1000),
                round((r.y1 - vis.y0) / vis.height * 1000),
                round((r.x1 - vis.x0) / vis.width * 1000),
            )
            bold = any(s["flags"] & pymupdf.TEXT_FONT_BOLD for s in spans)
            lines.append(Line(text, box, bold))
    return lines


# ---- text helpers ----------------------------------------------------------------------------


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _is_rtl(text: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)


def _box_rect(box: tuple[int, int, int, int], rect: pymupdf.Rect) -> pymupdf.Rect:
    ymin, xmin, ymax, xmax = box
    return pymupdf.Rect(
        rect.x0 + xmin / 1000 * rect.width,
        rect.y0 + ymin / 1000 * rect.height,
        rect.x0 + xmax / 1000 * rect.width,
        rect.y0 + ymax / 1000 * rect.height,
    )


# ---- visible text (text-only mode) -----------------------------------------------------------


def draw_visible_text(page: pymupdf.Page, lines: list[Line]) -> None:
    """Draw the lines as visible text at their positions on a blank, unrotated page.

    Text is laid out by MuPDF's HTML engine (correct shaping for Arabic, Urdu, Indic scripts, CJK),
    then converted to vector outlines. The outlines look like text but are not extractable, so
    search and copy use only the exact Unicode of the invisible layer from add_text_layer().
    """
    with pymupdf.open() as tmp:
        canvas = tmp.new_page(width=page.rect.width, height=page.rect.height)
        unplaced = []
        drawn = False
        for line in lines:
            text = _clean(line.text)
            if not text:
                continue
            if line.box is None:
                unplaced.append(text)
                continue
            rect = _box_rect(line.box, canvas.rect)
            canvas.insert_htmlbox(rect, _html_line(text, line.bold), css=_css(rect.height / LINE_HEIGHT), scale_low=0)
            drawn = True

        if unplaced:
            body = "".join(_html_line(t, False) for t in unplaced)
            canvas.insert_htmlbox(canvas.rect + (36, 36, -36, -36), body, css=_css(11, wrap=True), scale_low=0)
            drawn = True

        if not drawn:
            return
        svg = canvas.get_svg_image(text_as_path=True)

    with pymupdf.open("svg", svg.encode("utf-8")) as vector, pymupdf.open("pdf", vector.convert_to_pdf()) as pdf:
        page.show_pdf_page(page.rect, pdf, 0)


def _html_line(text: str, bold: bool) -> str:
    # MuPDF orders RTL text by itself; a dir="rtl" attribute would stop text-align from applying
    style = "text-align:right;" if _is_rtl(text) else ""
    if bold:
        style += "font-weight:bold;"
    return f'<p style="{style}">{html.escape(text)}</p>'


def _css(font_size: float, wrap: bool = False) -> str:
    return (
        f"* {{margin:0; padding:0; font-family:sans-serif; font-size:{font_size:.2f}px;"
        f" line-height:{LINE_HEIGHT}; white-space:{'normal' if wrap else 'nowrap'}; color:black}}"
    )


# ---- invisible, searchable text layer ---------------------------------------------------------


def add_text_layer(page: pymupdf.Page, lines: list[Line], fonts: FontSet) -> None:
    """Write the lines as invisible text. Call fix_to_unicode() afterwards, before saving."""
    rect = page.rect  # visible (rotated) page area
    derotate = page.derotation_matrix
    unplaced = []

    for line in lines:
        text = _clean(line.text)
        if not text:
            continue
        if line.box is None:
            unplaced.append(text)
            continue
        # PDFs store right-to-left text in visual order
        text = get_display(text) if _is_rtl(text) else text
        runs = fonts.runs(text)
        main = max(runs, key=lambda run: len(run[1]))[0].font
        r = _box_rect(line.box, rect)

        # Size the text so its ascender..descender span fills the box height, then stretch
        # horizontally so the whole line spans exactly the box width (keeps selection aligned).
        fontsize = r.height / max(main.ascender - main.descender, 0.5)
        widths = [font.font.text_length(part, fontsize=fontsize) for font, part in runs]
        if fontsize <= 0 or sum(widths) <= 0:
            continue
        stretch = r.width / sum(widths)
        # morph works in unrotated page space, where the text runs vertically on 90/270 pages
        scale = pymupdf.Matrix(1, stretch) if page.rotation in (90, 270) else pymupdf.Matrix(stretch, 1)
        x = r.x0
        for (font, part), width in zip(runs, widths):
            point = pymupdf.Point(x, r.y1 + main.descender * fontsize) * derotate
            font.ensure_on(page)
            page.insert_text(
                point,
                part,
                fontsize=fontsize,
                fontname=font.name,
                render_mode=RENDER_INVISIBLE,
                rotate=page.rotation,
                morph=(point, scale),
            )
            font.record(part)
            x += width * stretch

    if unplaced:
        _insert_unplaced(page, unplaced, fonts)


def _insert_unplaced(page: pymupdf.Page, texts: list[str], fonts: FontSet) -> None:
    """No positions available: put the text invisibly over the page so it is still searchable."""
    texts = [get_display(t) if _is_rtl(t) else t for t in texts]
    font = fonts.for_text(" ".join(texts))
    font.ensure_on(page)
    box = (page.rect + (36, 36, -36, -36)) * page.derotation_matrix
    for fontsize in (11, 8, 6, 4, 2, 1):
        rc = page.insert_textbox(
            box,
            "\n".join(texts),
            fontsize=fontsize,
            fontname=font.name,
            render_mode=RENDER_INVISIBLE,
            rotate=page.rotation,
        )
        if rc >= 0:
            font.record("".join(texts))
            return


def fix_to_unicode(doc: pymupdf.Document, pages: list[int], fonts: FontSet) -> None:
    """Rewrite the ToUnicode maps of the embedded text-layer fonts.

    PyMuPDF derives ToUnicode by reverse-looking-up each glyph in the font's cmap. When a glyph is
    shared by several code points (space / no-break space, Arabic letters / their presentation
    forms) it picks the wrong one, which breaks search and copy. We know exactly which character
    each glyph was written for, so map it back to that.
    """
    by_name = {f.name: f for f in fonts.loaded if f.used}
    done: set[int] = set()
    for pno in pages:
        for xref, _ext, ftype, _base, name, encoding in doc.get_page_fonts(pno):
            font = by_name.get(name)
            if font is None or xref in done or ftype != "Type0" or encoding != "Identity-H":
                continue
            done.add(xref)
            kind, value = doc.xref_get_key(xref, "ToUnicode")
            cmap = _to_unicode_cmap(font.used)
            if kind == "xref":
                doc.update_stream(int(value.split()[0]), cmap)
            else:
                new = doc.get_new_xref()
                doc.update_object(new, "<<>>")
                doc.update_stream(new, cmap)
                doc.xref_set_key(xref, "ToUnicode", f"{new} 0 R")


def _to_unicode_cmap(mapping: dict[int, str]) -> bytes:
    entries = [
        f"<{gid:04x}> <{ch.encode('utf-16-be').hex()}>" for gid, ch in sorted(mapping.items())
    ]
    blocks = []
    for i in range(0, len(entries), 100):
        chunk = entries[i : i + 100]
        blocks.append(f"{len(chunk)} beginbfchar\n" + "\n".join(chunk) + "\nendbfchar")
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        + "\n".join(blocks)
        + "\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii")
