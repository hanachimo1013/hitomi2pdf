import os
import re
import asyncio
import random
import aiohttp
import aiofiles
import pikepdf
import shutil
from typing import Dict
from tqdm.asyncio import tqdm
from functools import wraps
from PIL import Image
from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

# --- RETRY DECORATOR ---
def retry_on_failure(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt == max_retries - 1: return None
                    await asyncio.sleep((base_delay * (2 ** attempt)) + random.uniform(0, 1))
            return None
        return wrapper
    return decorator

class Hitomi2PDF:
    def __init__(self, output_dir="outputs", concurrency_limit=5, target_width=1600, target_height=2260):
        self.base_url = "https://hitomi.la"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        }
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        
        self.output_dir = output_dir
        self.target_width = target_width
        self.target_height = target_height
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            print(f"[*] Target directory '{self.output_dir}' inaccessible: {e}. Falling back to 'outputs'.")
            self.output_dir = "outputs"
            os.makedirs(self.output_dir, exist_ok=True)

    def _sanitize(self, text):
        return re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")

    async def get_rendered_metadata(self, gallery_id: str) -> Dict:
        """Uses Playwright to let the site's own JS resolve image URLs."""
        async with async_playwright() as p:
            print(f"[*] Launching headless browser for {gallery_id}...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            reader_url = f"{self.base_url}/reader/{gallery_id}.html"
            print(f"[*] Navigating to {reader_url}...")
            
            try:
                # Wait for core variables to be defined in the page context
                await page.goto(reader_url, wait_until="networkidle")
                
                # Extract solved data using the page's own JS functions
                # Wait for 'galleryinfo' script to load
                await page.wait_for_function("window.galleryinfo !== undefined")
                
                metadata = await page.evaluate("""
                    () => {
                        const info = window.galleryinfo;
                        const solved_files = info.files.map((file, index) => {
                            let avif_url = "";
                            let webp_url = "";
                            try {
                                if (typeof url_from_url_from_hash === 'function') {
                                    if (file.hasavif) avif_url = url_from_url_from_hash(info.id, file, 'avif');
                                    if (file.haswebp) webp_url = url_from_url_from_hash(info.id, file, 'webp');
                                }
                            } catch (e) { }
                            
                            return {
                                ...file,
                                avif_url: avif_url,
                                webp_url: webp_url
                            };
                        });
                        return {
                            id: info.id,
                            title: info.title || info.japanese_title || "Untitled",
                            tags: info.tags || [],
                            files: solved_files
                        };
                    }
                """)
                
                return metadata
            finally:
                await browser.close()

    @retry_on_failure(max_retries=3, base_delay=1)
    async def _fetch_image(self, session, url, headers, path):
        if not url: return False
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                content = await resp.read()
                if len(content) < 500: # Sanity check for too small files (junk)
                    return False
                async with aiofiles.open(path, "wb") as f:
                    await f.write(content)
                return True
            else:
                # Print specifically for 404 or other errors to see which files are failing
                if resp.status != 404:
                    print(f"\n[!] Error ({resp.status}) requesting: {url}")
            return False

    async def download_page(self, session, gallery_id, index, img_data, temp_path):
        async with self.semaphore:
            headers = self.headers.copy()
            safe_gallery_id = re.sub(r'\D', '', str(gallery_id))
            headers["Referer"] = f"{self.base_url}/reader/{safe_gallery_id}.html"

            # Try AVIF first
            url_avif = img_data.get('avif_url')
            if url_avif:
                file_path = os.path.join(temp_path, f"{index:04d}.avif")
                if await self._fetch_image(session, url_avif, headers, file_path):
                    return True

            # Fallback to WEBP
            url_webp = img_data.get('webp_url')
            if url_webp:
                file_path = os.path.join(temp_path, f"{index:04d}.webp")
                if await self._fetch_image(session, url_webp, headers, file_path):
                    return True
            
            # Final Fallback to Jpeg (original) if available in hash but rare on Hitomi
            return False

    async def execute(self, gallery_id):
        print(f"\n[*] Querying Hitomi Gallery ID: {gallery_id} via DOM rendering...")
        
        try:
            meta = await self.get_rendered_metadata(gallery_id)
            if not meta.get("files"):
                print("[!] No files found. Gallery may be empty or invalid.")
                return False
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            print(f"[!] Rendering Error: {e}")
            print("[TIP] Make sure you have run: python -m playwright install chromium")
            return False

        files = meta.get("files", [])
        raw_title = meta.get("title", f"Hitomi Gallery {gallery_id}")
        title = self._sanitize(raw_title)
        tags = [t.get('tag', '') for t in meta.get("tags", []) if isinstance(t, dict)]
        
        total_pages = len(files)
        print("=" * 60)
        print(f"  TARGET   : {title}")
        print(f"  VOLUME   : {total_pages} Pages")
        print("=" * 60)
        
        confirm = await asyncio.to_thread(input, f"Compile this entry? [Enter to Continue / n to Cancel]: ")
        if confirm.lower() == 'n':
            print("[!] Operation scrubbed.")
            return False

        temp_path = f"temp_hitomi_{gallery_id}"
        os.makedirs(temp_path, exist_ok=True)

        try:
            async with aiohttp.ClientSession() as session:
                tasks = []
                for index, img_data in enumerate(files, 1):
                    tasks.append(self.download_page(session, gallery_id, index, img_data, temp_path))
                
                await tqdm.gather(*tasks, desc=f"Progress [{gallery_id}]", unit="pg")

        except Exception as e:
            print(f"[!] Network error: {e}")
            shutil.rmtree(temp_path)
            return False

        img_files = []
        for f in sorted(os.listdir(temp_path)):
            if f.lower().endswith(('.jpg', '.png', '.webp', '.gif', '.avif')):
                img_files.append(os.path.join(temp_path, f))

        if not img_files:
            print("[!] No images downloaded. Aborting compilation.")
            shutil.rmtree(temp_path)
            return False

        if len(img_files) < total_pages:
            failed = total_pages - len(img_files)
            print(f"\n[!] WARNING: Integrity check failed. {failed} page(s) failed to download.")
            print(f"[*] Attempting to proceed with {len(img_files)} pages...")

        final_filename = os.path.join(self.output_dir, f"{gallery_id}_{title}.pdf")
        
        print(f"[*] Normalizing and Compiling ({self.target_width}x{self.target_height})...")
        TARGET_W, TARGET_H = self.target_width, self.target_height
        processed_img_files = []

        for img_path in img_files:
            try:
                # Pillow might need pillow-avif-plugin for .avif files
                with Image.open(img_path) as img:
                    img = img.convert('RGB')
                    ratio = min(TARGET_W / img.width, TARGET_H / img.height)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    resized_img = img.resize(new_size, Image.Resampling.LANCZOS)
                    canvas = Image.new('RGB', (TARGET_W, TARGET_H), (255, 255, 255))
                    canvas.paste(resized_img, ((TARGET_W - new_size[0]) // 2, (TARGET_H - new_size[1]) // 2))
                    
                    proc_path = img_path + ".jpg" # Save as intermediate JPG
                    canvas.save(proc_path, "JPEG", quality=90)
                    processed_img_files.append(proc_path)
                    
                    # Prevent memory ballooning by explicitly releasing image buffers
                    img.close()
                    resized_img.close()
                    canvas.close()
            except Exception as e:
                print(f"[!] Error processing {img_path}: {e}")

        if processed_img_files:
            images = []
            first_img = None
            try:
                # Re-sort to ensure correct PDF order
                processed_img_files.sort()
                first_img = Image.open(processed_img_files[0])
                for p in processed_img_files[1:]:
                    images.append(Image.open(p))
                    
                first_img.save(
                    final_filename, 
                    save_all=True, 
                    append_images=images, 
                    resolution=100.0, 
                    quality=90
                )
            except (OSError, ValueError) as e:
                print(f"[!] PDF Compilation Error: {e}")
                shutil.rmtree(temp_path)
                return False
            finally:
                if first_img:
                    first_img.close()
                for i in images:
                    i.close()
        
        print(f"[*] Finalizing metadata and linearization...")
        for attempt in range(5):
            if os.path.exists(final_filename):
                try:
                    with pikepdf.open(final_filename, allow_overwriting_input=True) as pdf:
                        with pdf.open_metadata() as pdf_meta:
                            pdf_meta['dc:title'] = f"{title}"
                            pdf_meta['dc:subject'] = tags + ["Hitomi", gallery_id]
                        pdf.save(final_filename, linearize=True)
                    break 
                except Exception as e:
                    if attempt == 4:
                        print(f"[!] Warning: Failed to inject metadata: {e}")
                    await asyncio.sleep(1)
            else:
                if attempt == 4:
                    print(f"[!] Warning: File not found for metadata injection: {final_filename}")
                await asyncio.sleep(1)
        
        shutil.rmtree(temp_path)
        print("=" * 60)
        print(f"   -> Success: [{title}]")
        print(f"      Archive completed: {os.path.basename(final_filename)}")
        print(f"      Location: {self.output_dir}")
        print("=" * 60)
        return True
