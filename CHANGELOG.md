# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-13

### Added
* **AI-Powered OCR Pipeline:**
  * Integrated Google Gemini AI (`google-genai` SDK) for single-page vision transcription.
  * Added default support for `gemini-3.8-flash`, `gemini-3.5-flash-lite`, and `gemini-3.1-pro-preview`.
  * Verbatim text transcription prompt eliminating scanner noise, graphical borders, logos, and artifacts.
  * Automatic retry mechanism with backoff for rate limits and server errors (HTTP 429, 500, 502, 503, 504).
* **Dual Output Modes:**
  * **Plain Text:** Rebuilds pages as clean text-only documents, styled with MuPDF's vector rendering engine.
  * **Searchable Scan (Overlay):** Embeds an invisible, selectable Unicode text layer atop the original scanned document for search and copy capability.
* **Complex Script & Multilingual Support:**
  * Added bidirectional text shaping using `python-bidi` and MuPDF font fallbacks for right-to-left scripts (Urdu, Arabic, Persian, Hebrew).
  * Native rendering support for Indic scripts (Hindi, Bengali, Tamil) and CJK character sets.
* **Smart Page Optimization:**
  * Added digital text page detection to automatically extract and reuse embedded text layers, bypassing Gemini API calls for digital pages to save tokens and processing costs.
* **Automated Processing & Folder Watcher:**
  * Background directory watcher (`watcher.py`) detecting incoming PDF files in real time.
  * File lock check ensuring file copies finish completely before queuing.
  * "Process now" button for instant batch processing of backlogged files.
* **Desktop UI & Secure Storage:**
  * Modern desktop interface built using PySide6 (Fusion theme) with real-time queue tracking and progress status.
  * Secure storage of the Google Gemini API key in **Windows Credential Manager** using `keyring`.
  * Dedicated **Settings Dialog** featuring API key validation, model selector with live key refresh, DPI configuration, and overwrite options.
* **Packaging & Deployment:**
  * Added PyInstaller standalone executable configuration (`PdfOcr.spec`) and automated compilation script (`build.bat`) generating a single portable `dist/PdfOcr.exe`.
  * Configured headless crash logging to `%APPDATA%/PdfOcr/app.log` with size-based rotation.
