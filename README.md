# 🏛️ hitomi2pdf: Luxurious Archive

A high-performance, asynchronous Python utility designed to fetch, normalize, and archive Hitomi.la galleries into a structured PDF format. Optimized for domestic Google Drive synchronization and high-fidelity viewing.

## ✨ Key Features
* **DOM-Rendering Integration:** Uses `playwright` to accurately resolve dynamic Hitomi image URLs (including AVIF/WebP) using the site's own JavaScript.
* **Asynchronous Downloads:** Utilizes `aiohttp` and `asyncio` for high-speed concurrent fetching.
* **Resilient Connectivity:** Automatically catches and retries failed downloads with exponential backoff.
* **Intelligent Fallback:** Automatically tries the `.webp` version of a page if the high-quality `.avif` version is missing on the server.
* **Aspect Ratio Normalization:** Every page is centered on a uniform 1600x2260 canvas to prevent "jumping" during reading.
* **Metadata Injection:** Bakes Title and Tags directly into the PDF metadata via `pikepdf`.
* **Smart Storage Management:** Automatically checks for your `G:\` Google Drive availability, seamlessly falling back to a local `outputs` folder if needed.
* **Linearized PDFs:** Final archives are linearized for extremely fast web viewing and scrolling.

## 🛠️ Prerequisites

Ensure you have the required Python packages installed:

```powershell
pip install -r requirements.txt
```

You must also install the Playwright browser dependencies:

```powershell
python -m playwright install chromium
```

## 🚀 Usage

Run the tool by providing a Hitomi gallery ID:

```powershell
python hitomi2pdf.py <gallery_id>
```

### Execution Flow:
1. **DOM Rendering Handshake:** Launches a headless browser to resolve the current minute's dynamic `gg.js` routing and fetch full metadata.
2. **Handshake:** Confirms the download via `[Enter to Continue / n to Cancel]`.
3. **Async Fetching:** Pages are downloaded in parallel with priority for `.avif` formats.
4. **Processing:** Images are normalized to a uniform `1600x2260` white canvas and compiled into a single PDF.
5. **PDF Finalization:** Metadata is injected and the file is linearized for performance.

## 📁 Project Structure
* `hitomi2pdf.py`: The core architect script.
* `requirements.txt`: Project dependencies list.
* `temp_hitomi_XXXXXX/`: Temporary storage for raw images (auto-cleaned).
* **Outputs:** Defaults to `./outputs`.

---
*Created for the Luxurious Chest Collection. 😏*