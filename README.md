# Scanned PDF OCR (Gemini Desktop Application)

An intelligent, cross-lingual Windows desktop application that automates the conversion of scanned PDF files into clean, searchable, and copyable digital documents using Google Gemini Vision AI.

The application monitors an incoming folder or processes batches on-demand, transcribing scanned pages while preserving page counts, handling complex international scripts, and generating standard PDFs without requiring local machine learning hardware.

---

## 🌟 Key Features

* **AI-Powered OCR via Google Gemini:** Utilizes latest Gemini vision models (e.g., `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview`) for high-fidelity text transcription.
* **Global Script & Multi-Language Support:** Flawlessly transcribes complex scripts, including:
  * Right-to-Left (RTL): Urdu, Arabic, Persian, Hebrew (with bidirectional text shaping).
  * Indic scripts: Hindi, Bengali, Tamil, etc.
  * East Asian scripts: Chinese (Simplified/Traditional), Japanese, Korean.
  * Latin and Cyrillic scripts.
* **Dual Output Modes:**
  * **Plain Text PDF (Default):** Generates a brand-new, clean PDF containing only transcribed text, arranged from top to bottom. Removes scan noise, stamps, smudges, pictures, and artifacts.
  * **Searchable Scan (Overlay):** Preserves the original visual appearance of the scanned document while placing an invisible, selectable Unicode text layer directly over each line for search (Ctrl+F) and copy-paste.
* **Token & Cost Optimization:** Automatically detects pages that already contain digital text and reuses their text layer without querying the Gemini API.
* **Automated Folder Watching:** Background filesystem watcher detects newly added PDFs in the input folder and queues them as soon as file writes finish.
* **Secure Credential Management:** Stores your Google Gemini API key securely in **Windows Credential Manager** (via `keyring`), never exposing keys in plain-text configuration files.
* **Zero-Dependency Portable Build:** Can be compiled into a single, standalone Windows executable (`PdfOcr.exe`) that runs on any modern Windows PC without Python installed.

---

## 📋 System Requirements

* **Operating System:** Windows 10 or Windows 11 (64-bit)
* **Python Version:** Python 3.10 or higher (for running from source or building)
* **Internet Connection:** Required for Google Gemini API communication
* **Gemini API Key:** A free or paid key from [Google AI Studio](https://aistudio.google.com/apikey)

---

## 🚀 Setup & Installation (Run from Source)

### 1. Clone the Repository
```bash
git clone https://github.com/aasimghaffar/pdf-ocr-desktop-application.git
cd pdf-ocr-desktop-application
```

### 2. Create and Activate Virtual Environment
Open PowerShell or Command Prompt in the project root:

```bat
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Dependencies
```bat
pip install -r requirements.txt
```

### 4. Run the Application
```bat
python main.py
```
*(Or run directly with `.venv\Scripts\python.exe main.py`)*

---

## 🖥️ User Guide & Configuration

### Step 1: Set Your Gemini API Key
1. Obtain an API key from [Google AI Studio](https://aistudio.google.com/apikey).
2. Launch the application, paste your API key into the **Gemini API Key** field, and click **Save**.
3. To verify connectivity, open **Settings…** and click **Test key**.

### Step 2: Select Folders
* **Input Folder:** Select the folder containing incoming scanned PDF files.
* **Output Folder:** Select a separate destination folder where processed PDFs will be saved.

### Step 3: Choose Processing Mode
* **Process Now:** Immediately processes all unprocessed PDFs found in the input directory.
* **Watch Input Folder:** Enables real-time background monitoring to automatically process new documents as they are copied or downloaded into the input directory.

---

## ⚙️ Application Settings

Click **Settings…** in the main toolbar to customize behavior:

| Setting | Default | Description |
| :--- | :--- | :--- |
| **Model** | `gemini-3.8-flash` | Select your desired Gemini model. Click **Refresh list** to query models supported by your API key. |
| **Output PDF** | `Plain text` | Choose between **Plain text** (clean text-only layout) or **Searchable scan** (original scan with invisible selectable text). |
| **Page Render DPI** | `200` | Resolution used to render page images for OCR. Higher DPI improves clarity for small fonts but uses more processing time. |
| **Overwrite** | `Off` | When enabled, existing files in the output directory will be re-processed and overwritten. |

*Settings and logs are stored under `%APPDATA%\PdfOcr\` (`settings.json` and `app.log`).*

---

## 📦 Building Standalone Executable (.exe)

You can compile the application into a standalone Windows `.exe` using the included build script:

```bat
build.bat
```

This compiles a single-file portable binary located at:
```text
dist\PdfOcr.exe
```
This executable can be distributed to clients or end users and does not require Python or external packages to run.

---

## 🏗️ Project Architecture

```text
desktop-app-pdf-ocr/
├── app/
│   ├── ui/
│   │   ├── main_window.py       # Main Qt window, queue status, progress tracking
│   │   └── settings_dialog.py   # Settings modal and API key testing interface
│   ├── config.py                # Persistent settings (JSON) and secure Keyring helper
│   ├── gemini_ocr.py            # Gemini API client, rate limiting, and prompt orchestrator
│   ├── pdf_builder.py           # PyMuPDF rendering, text shaping (Bidi/Arabic), and PDF creation
│   ├── watcher.py               # Background directory observer for incoming files
│   └── worker.py                # Multi-threaded task worker queue
├── build.bat                    # Automated PyInstaller build script
├── main.py                      # Application entry point
├── PdfOcr.spec                  # PyInstaller specification file
├── requirements.txt             # Python dependencies
└── README.md                    # Project documentation
```

---

## 📝 Logging & Diagnostics

If an unexpected error occurs in the compiled `.exe` or during execution, logs are automatically recorded to:
```text
%APPDATA%\PdfOcr\app.log
```
Logs rotate automatically (1 MB limit, 1 backup file) to avoid consuming unnecessary disk space.

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
