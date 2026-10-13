# Scanned PDF OCR (Gemini)

A Windows desktop app that takes scanned PDFs from an **input folder**, uses **Google Gemini** to read the text, and saves a **PDF with the same file name** in an **output folder**.

The output always has the same number of pages as the scan, and each page holds only the text from that page. There are two output types (see **Settings**):

- **Plain text** (default): a new PDF with just the text of each page, written as plain lines from the top of the page. The layout of the scan, photos, logos, stamps, signatures, lines and other graphics are all dropped.
- **Searchable scan**: the original scan, unchanged, with an invisible text layer on top.

In both types you can search the text with Ctrl+F and copy it. This works for English, Urdu/Arabic, Hindi and other Indic scripts, and Chinese, Japanese and Korean.

## Setup

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

1. Paste your Gemini API key in the **Gemini API key** box and click **Save** (get one at https://aistudio.google.com/apikey). To check it, open **Settings…** and click **Test key**.
   The key is stored in Windows Credential Manager, not in a plain file.
2. Pick the **Input folder** and the **Output folder**. They must be different folders.
3. Click **Process now** to convert every PDF in the input folder, or turn on
   **Watch input folder** to convert new PDFs automatically as they arrive.

Files that already exist in the output folder are skipped unless you turn on **Overwrite** in Settings.
Pages that are already digital text (not scans) reuse their own text and are not sent to Gemini.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Model | `gemini-3.8-flash` | Click **Refresh list** to see the models available to your key. |
| Output PDF | Plain text | Choose **Plain text** (only the text of each page) or **Searchable scan** (keeps the original look). |
| Page render DPI | 200 | Use a higher value for small print. Higher values are slower and cost more tokens. |
| Overwrite | off | Re-create output PDFs that already exist. |

Settings are saved in `%APPDATA%\PdfOcr\settings.json`.

## Build a standalone .exe

```bat
build.bat
```

This creates `dist\PdfOcr.exe`. Copy it anywhere; it does not need Python installed.

## How it works

- `app/gemini_ocr.py`: sends one page image per request, so text can never move to another page. The prompt tells Gemini to return only text (ignoring images, logos, stamps, signatures, lines and noise) as JSON lines with bounding boxes and a bold flag. Rate-limit and server errors are retried with backoff.
- `app/pdf_builder.py`: creates one output page per input page.
  - **Plain text:** Gemini returns the page as plain text; the lines are stacked from the top of the page (long ones wrapped, the font shrunk only if the page would overflow) and drawn with MuPDF's HTML engine, so Arabic, Urdu and Indic scripts are shaped correctly, and then drawn as vector outlines.
  - **Both modes:** an invisible text layer with the exact Unicode sits on top. Search and copy use this layer.
  - **No positions from Gemini:** the text is still added, but without its original layout.
- `app/worker.py`: background queue, so the window stays responsive.
- `app/watcher.py`: watches the input folder and waits until a file has finished copying before queuing it.
