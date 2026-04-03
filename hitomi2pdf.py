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
import concurrent.futures
from PIL import Image
from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

def process_image(img_path, target_w=1600, target_h=2260):
    try:
        # Pillow might need pillow-avif-plugin for .avif files
        with Image.open(img_path) as img:
            img = img.convert('RGB')
            ratio = min(target_w / img.width, target_h / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            resized_img = img.resize(new_size, Image.Resampling.LANCZOS)
            canvas = Image.new('RGB', (target_w, target_h), (255, 255, 255))
            canvas.paste(resized_img, ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2))

            proc_path = img_path + ".jpg" # Save as intermediate JPG
            canvas.save(proc_path, "JPEG", quality=90)

            # Prevent memory ballooning by explicitly releasing image buffers
            img.close()
            resized_img.close()
            canvas.close()
            return proc_path
    except Exception as e:
        print(f"[!] Error processing {img_path}: {e}")
        return None

# --- RETRY DECORATOR ---
def retry_on_failure(max_retries=5, base_delay=2):
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

    @retry_on_failure(max_retries=5, base_delay=2)
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
            elif resp.status in [403, 429, 500, 502, 503, 504]:
                print(f"[~] Rate limited ({resp.status}) on {url.split('/')[-1]}, retrying...")
                resp.raise_for_status()
            else:
                # Print specifically for 404 or other errors to see which files are failing
                if resp.status != 404:
                    print(f"\n[!] Error ({resp.status}) requesting: {url}")
            return False

    async def download_page(self, session, gallery_id, index, img_data, temp_path, delay=0):
        if delay > 0:
            await asyncio.sleep(delay)
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

    async def _fetch_metadata(self, gallery_id: str):
        print(f"\n[*] Querying Hitomi Gallery ID: {gallery_id} via DOM rendering...")
        try:
            meta = await self.get_rendered_metadata(gallery_id)
            if not meta or not meta.get("files"):
                print("[!] No files found. Gallery may be empty or invalid.")
                return None
            return meta
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            print(f"[!] Rendering Error: {e}")
            print("[TIP] Make sure you have run: python -m playwright install chromium")
            return None

    async def _download_images(self, gallery_id: str, files: list, temp_path: str):
        total_pages = len(files)
        try:
            async with aiohttp.ClientSession() as session:
                tasks = []
                for index, img_data in enumerate(files, 1):
                    # Optimized to theoretical Cloudflare WAF throttle curve (~3 req/s)
                    delay = (index - 1) * 0.33
                    tasks.append(asyncio.create_task(self.download_page(session, gallery_id, index, img_data, temp_path, delay)))
                
                await tqdm.gather(*tasks, desc=f"Progress [{gallery_id}]", unit="pg")

        except Exception as e:
            print(f"[!] Network error: {e}")
            return None

        img_files = []
        for f in sorted(os.listdir(temp_path)):
            if f.lower().endswith(('.jpg', '.png', '.webp', '.gif', '.avif')):
                img_files.append(os.path.join(temp_path, f))

        if not img_files:
            print("[!] No images downloaded. Aborting compilation.")
            return None

        if len(img_files) < total_pages:
            failed = total_pages - len(img_files)
            print(f"\n[!] WARNING: Integrity check failed. {failed} page(s) failed to download.")
            print(f"[*] Proceeding with {len(img_files)} pages...")

        return img_files

    async def _process_images(self, img_files: list):
        print(f"[*] Normalizing ({self.target_width}x{self.target_height})...")
        processed_img_files = []
        loop = asyncio.get_running_loop()
        
        with concurrent.futures.ProcessPoolExecutor() as executor:
            tasks = [
                loop.run_in_executor(executor, process_image, img_path, self.target_width, self.target_height) 
                for img_path in img_files
            ]
            results = await tqdm.gather(*tasks, desc="Processing images", unit="img")

            for res in results:
                if res:
                    processed_img_files.append(res)
        
        return processed_img_files

    def _compile_pdf(self, processed_img_files: list, final_filename: str) -> bool:
        if not processed_img_files:
            return False

        if os.path.exists(final_filename):
            try:
                os.remove(final_filename)
                print(f"[*] Overwriting existing file: {os.path.basename(final_filename)}")
            except OSError as e:
                print(f"[!] Target file exists but is locked: {e}")

        images = []
        first_img = None
        try:
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
            return True
        except Exception as e:
            print(f"[!] PDF Compilation Error: {e}")
            return False
        finally:
            if first_img:
                first_img.close()
            for i in images:
                i.close()

    def _inject_metadata_sync(self, final_filename: str, title: str, tags: list, gallery_id: str) -> bool:
        if not os.path.exists(final_filename):
            return False
        try:
            with pikepdf.open(final_filename, allow_overwriting_input=True) as pdf:
                with pdf.open_metadata() as pdf_meta:
                    pdf_meta['dc:title'] = title
                    pdf_meta['dc:subject'] = tags + ["Hitomi", str(gallery_id)]
                pdf.save(final_filename, linearize=True)
            return True
        except Exception as e:
            print(f"[!] Metadata Injection Error: {e}")
            return False

    async def _finalize_pdf(self, final_filename: str, title: str, tags: list, gallery_id: str):
        print(f"[*] Finalizing metadata and linearization...")
        for attempt in range(5):
            success = await asyncio.to_thread(self._inject_metadata_sync, final_filename, title, tags, gallery_id)
            if success:
                return True
            if attempt < 4:
                await asyncio.sleep(1)
        return False

    async def execute(self, gallery_id):
        meta = await self._fetch_metadata(gallery_id)
        if not meta:
            return False

        files = meta.get("files", [])
        title = self._sanitize(meta.get("title", f"Hitomi Gallery {gallery_id}"))
        tags = [t.get('tag', '') for t in meta.get("tags", []) if isinstance(t, dict)]
        
        print("=" * 60)
        print(f"  TARGET   : {title}")
        print(f"  VOLUME   : {len(files)} Pages")
        print("=" * 60)

        confirm = await asyncio.to_thread(input, "Compile this entry? [Enter/y to Continue, n to Cancel]: ")
        if confirm.lower() == 'n':
            print("[!] Operation aborted.")
            return False

        temp_path = f"temp_hitomi_{gallery_id}"
        os.makedirs(temp_path, exist_ok=True)

        try:
            img_files = await self._download_images(gallery_id, files, temp_path)
            if not img_files:
                shutil.rmtree(temp_path)
                return False

            processed_img_files = await self._process_images(img_files)
            if not processed_img_files:
                shutil.rmtree(temp_path)
                return False

            final_filename = os.path.join(self.output_dir, f"{gallery_id}_{title}.pdf")
            success = await asyncio.to_thread(self._compile_pdf, processed_img_files, final_filename)
            
            if success:
                await self._finalize_pdf(final_filename, title, tags, gallery_id)

            shutil.rmtree(temp_path)
            print("=" * 60)
            print(f"   -> Success: [{title}]")
            print(f"      Archive completed: {os.path.basename(final_filename)}")
            print(f"      Location: {self.output_dir}")
            print("=" * 60)
            return True
        except Exception as e:
            print(f"[!] Unexpected error during execution: {e}")
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path)
            return False
