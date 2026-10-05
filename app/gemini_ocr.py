"""Page OCR through the Gemini API."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT_MS = 180_000

_IGNORE = """Extract ONLY the text. Ignore everything on the page that is not text: photos, pictures,
logos, icons, illustrations, the graphics of charts and diagrams, stamps and seals, signatures,
barcodes and QR codes, watermarks, lines, borders, boxes, table rules, shading, background patterns
and scanner noise (specks, punch holes, shadows, page edges). Never describe an image.
Keep all real text: headings, paragraphs, lists, captions, labels, every table cell, headers,
footers, page numbers and clearly legible handwritten text (but not signatures).
Transcribe verbatim in the original language and script. Do not translate, summarise, correct,
complete or invent anything, and only include text that is visible on THIS page."""

LAYOUT_PROMPT = f"""You are an OCR engine reading one scanned page.
{_IGNORE}

Return a JSON array with one object per visual line of text, in natural reading order
(top to bottom; in multi-column layouts finish one column before starting the next;
in tables read row by row, with each cell as its own object). Each object has:
- "text": the exact text of that line.
- "box_2d": the bounding box of that line as [ymin, xmin, ymax, xmax], normalised to 0-1000
  relative to the page image.
- "bold": true if the line is bold or a heading, otherwise false.
If the page has no text, return []."""

PLAIN_PROMPT = f"""You are an OCR engine reading one scanned page.
{_IGNORE}

Output only the text, one line per visual line, in reading order, with no commentary."""


class OcrLine(BaseModel):
    text: str
    box_2d: list[int]
    bold: bool = False


@dataclass
class Line:
    text: str
    # (ymin, xmin, ymax, xmax) normalised 0-1000, or None when the position is unknown
    box: tuple[int, int, int, int] | None
    bold: bool = False


class OcrError(Exception):
    """`fatal` means every further request would fail the same way (bad key, no quota, ...)."""

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


def _client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))


def _api_error(e: errors.APIError) -> OcrError:
    message = e.message or ""
    if e.code == 429:
        return OcrError(f"Gemini rate limit or quota reached: {message}", fatal=True)
    if e.code in (401, 403) or (e.code == 400 and "API key" in message):
        return OcrError(f"Gemini rejected the API key: {message}", fatal=True)
    if e.code == 404:
        return OcrError(f"Gemini model not found (check the model in Settings): {message}", fatal=True)
    return OcrError(f"Gemini API error {e.code}: {message}")


class GeminiOcr:
    def __init__(self, api_key: str, model: str):
        self.client = _client(api_key)
        self.model = model
        # set by the caller: report a problem with the current page / ask whether to give up
        self.warn: Callable[[str], None] = lambda message: None
        self.cancelled: Callable[[], bool] = lambda: False

    def extract_page(self, png: bytes) -> list[Line]:
        """Return the text lines of a page image. Falls back to plain text if layout JSON fails."""
        image = types.Part.from_bytes(data=png, mime_type="image/png")
        response = self._generate(
            [image, LAYOUT_PROMPT],
            types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=list[OcrLine],
            ),
        )
        lines = _parse_layout(response)
        if lines is not None:
            return lines

        # Layout JSON was missing or truncated: fall back to plain text without positions.
        reason = _finish_reason(response)
        response = self._generate([image, PLAIN_PROMPT], types.GenerateContentConfig(temperature=0))
        text = (response.text or "").strip()
        if text:
            self.warn(f"no text positions from Gemini ({reason}); text added without its layout")
            return [Line(line, None) for line in text.splitlines() if line.strip()]
        self.warn(f"Gemini returned no text ({_finish_reason(response)}); page left blank")
        return []

    def _generate(self, contents, config):
        delay = 2.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.APIError as e:
                if e.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS:
                    raise _api_error(e) from e
            except httpx.TransportError as e:  # no internet, DNS failure, timeout
                if attempt == MAX_ATTEMPTS:
                    raise OcrError(f"Network error talking to Gemini: {e!r}", fatal=True) from e
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.cancelled():
                raise OcrError("cancelled")
            time.sleep(0.2)


def _finish_reason(response) -> str:
    """Why a response has no usable text, e.g. RECITATION, SAFETY, MAX_TOKENS."""
    try:
        if not response.candidates:
            feedback = response.prompt_feedback
            return f"blocked: {feedback.block_reason.name}" if feedback and feedback.block_reason else "empty response"
        reason = response.candidates[0].finish_reason
        return reason.name if reason else "unknown reason"
    except Exception:
        return "unknown reason"


def _parse_layout(response) -> list[Line] | None:
    items = response.parsed
    if items is None:
        try:
            items = [OcrLine(**d) for d in json.loads(response.text or "")]
        except (ValueError, TypeError):
            return None

    lines = []
    for item in items:
        text = item.text.strip()
        if not text:
            continue
        box = None
        if len(item.box_2d) == 4:
            ymin, xmin, ymax, xmax = (max(0, min(1000, v)) for v in item.box_2d)
            if ymax > ymin and xmax > xmin:
                box = (ymin, xmin, ymax, xmax)
        lines.append(Line(text, box, item.bold))
    return lines


def test_api_key(api_key: str, model: str) -> str:
    """Make a tiny request; returns the reply text or raises OcrError."""
    client = _client(api_key)
    try:
        response = client.models.generate_content(model=model, contents="Reply with the word OK.")
    except errors.APIError as e:
        raise _api_error(e) from e
    except httpx.TransportError as e:
        raise OcrError(f"Network error talking to Gemini: {e!r}") from e
    return (response.text or "").strip()


def list_models(api_key: str) -> list[str]:
    """Names of the models available to this key that support generateContent."""
    client = _client(api_key)
    names = []
    try:
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions and "gemini" in m.name:
                names.append(m.name.removeprefix("models/"))
    except errors.APIError as e:
        raise _api_error(e) from e
    except httpx.TransportError as e:
        raise OcrError(f"Network error talking to Gemini: {e!r}") from e
    return sorted(names)
