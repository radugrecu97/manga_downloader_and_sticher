import requests
import os
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.notebook import tqdm  # Using notebook version for Colab
from IPython.display import display, HTML  # For Colab display
import subprocess
import sys
import argparse  # Add this import

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Check if running in Colab
IN_COLAB = 'google.colab' in sys.modules

# Install required packages for Colab
if IN_COLAB:
    def install_chrome():
        commands = [
            'apt-get update',
            'apt-get install -y chromium-chromedriver',
            'cp /usr/lib/chromium-browser/chromedriver /usr/bin',
            'chmod +x /usr/bin/chromedriver'
        ]
        for cmd in commands:
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if process.returncode != 0:
                print(f"Error running {cmd}:")
                print(process.stderr)
                return False
        return True

    # Install Chrome and ChromeDriver
    if not install_chrome():
        raise RuntimeError("Failed to install Chrome/ChromeDriver")
    
    # Import Selenium after installation
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
else:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

def natural_key(s):
    # Split string into list of strings and integers for natural sorting
    import re
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

class WeebCentralScraper:
    def __init__(self, manga_url, chapter_range=None, output_dir="downloads", delay=1, max_threads=4):
        self.base_url = "https://weebcentral.com"
        if not manga_url.startswith(('http://', 'https://')):
            manga_url = 'https://' + manga_url
        self.manga_url = manga_url
        self.chapter_range = chapter_range
        self.output_dir = output_dir
        self.delay = delay
        self.max_threads = max_threads
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Create output directory in Colab
        if IN_COLAB:
            try:
                from google.colab import drive
                drive.mount('/content/drive')
                self.output_dir = f'/content/drive/MyDrive/{output_dir}'
                os.makedirs(self.output_dir, exist_ok=True)
            except Exception as e:
                logger.error(f"Error setting up Google Drive: {e}")
                raise
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.chapters = []
        self.progress_callback = None
        self.stop_flag = lambda: False

    def get_chrome_driver(self):
        """Configure and return Chrome WebDriver with appropriate options"""
        import tempfile
        import uuid
        import shutil
        from datetime import datetime
        
        chrome_options = webdriver.ChromeOptions()
        
        # Create a unique temporary directory with timestamp and UUID
        temp_dir = os.path.join(
            tempfile.gettempdir(),
            f'chrome_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex}'
        )
        
        try:
            # Ensure the directory is clean
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)
            
            # Basic options for both environments
            chrome_options.add_argument('--headless=new')  # Use new headless mode
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument(f'--user-data-dir={temp_dir}')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-software-rasterizer')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--remote-debugging-port=0')  # Use random port
            
            if IN_COLAB:
                service = Service('/usr/bin/chromedriver')
                driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                driver = webdriver.Chrome(options=chrome_options)
            
            return driver, temp_dir
        
        except Exception as e:
            # Clean up on failure
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise Exception(f"Failed to create Chrome driver: {str(e)}")

    def cleanup_chrome(self, driver, temp_dir):
        """Properly cleanup Chrome instance and its temporary directory"""
        try:
            if driver:
                driver.quit()
                
                # Clean up the temporary directory
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error during Chrome cleanup: {e}")

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def set_stop_flag(self, stop_flag):
        self.stop_flag = stop_flag

    def get_manga_title(self, soup):
        """Extract the manga title from the page"""
        title_element = soup.select_one("section[x-data] > section:nth-of-type(2) h1")
        if title_element:
            return title_element.text.strip()
        return "unknown_manga"

    def get_chapter_list_url(self):
        """Generate the full chapter list URL from manga URL"""
        parsed_url = urlparse(self.manga_url)
        path_parts = parsed_url.path.split('/')
        chapter_list_path = f"{'/'.join(path_parts[:3])}/full-chapter-list"
        return f"{self.base_url}{chapter_list_path}"

    def get_chapters(self):
        """Get list of all chapter URLs"""
        chapter_list_url = self.get_chapter_list_url()
        logger.info(f"Fetching chapter list from: {chapter_list_url}")
        
        response = requests.get(chapter_list_url, headers=self.headers)
        if response.status_code != 200:
            logger.error("Failed to fetch chapter list")
            return []
            
        soup = BeautifulSoup(response.content, 'html.parser')
        chapters = []
        
        # Find all chapter links
        chapter_elements = soup.select("div[x-data] > a")
        
        # Process chapters in reverse order (oldest first)
        for element in reversed(chapter_elements):
            chapter_url = element.get('href')
            chapter_name = element.select_one("span.flex > span")
            chapter_name = chapter_name.text.strip() if chapter_name else "Unknown Chapter"
            
            if chapter_url:
                if not chapter_url.startswith(('http://', 'https://')):
                    chapter_url = urljoin(self.base_url, chapter_url)
                
                chapters.append({
                    'url': chapter_url,
                    'name': chapter_name
                })
        
        return chapters

    def get_chapter_images(self, chapter_url):
        """Get list of image URLs for a chapter"""
        logger.info("Loading page with Selenium...")
        
        driver = None
        temp_dir = None
        
        try:
            driver, temp_dir = self.get_chrome_driver()
            driver.get(chapter_url)
            
            # Wait for images to load with explicit wait
            try:
                WebDriverWait(driver, 20).until(
                    lambda x: x.find_elements(By.CSS_SELECTOR, "img[src*='/manga/']")
                )
            except Exception as e:
                logger.warning(f"Timeout waiting for images: {str(e)}")
            
            # Additional wait for dynamic content
            time.sleep(5)
            
            # Get all image elements
            image_elements = driver.find_elements(By.CSS_SELECTOR, "img[src*='/manga/']")
            image_urls = []
            
            for img in image_elements:
                url = img.get_attribute('src')
                if url and not url.startswith('data:'):
                    image_urls.append(url)
            
            logger.info(f"Found {len(image_urls)} images")
            return image_urls
        
        except Exception as e:
            logger.error(f"Error in get_chapter_images: {str(e)}")
            return []
        
        finally:
            try:
                if driver:
                    driver.quit()
                if temp_dir and os.path.exists(temp_dir):
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")

    def download_image(self, img_url, filepath, chapter_url):
        """Download a single image"""
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f"Skipping {os.path.basename(filepath)} - already exists")
            return True

        try:
            if not img_url.startswith(('http://', 'https://')):
                img_url = urljoin(chapter_url, img_url)

            # Add referer header for this specific request
            headers = self.headers.copy()
            headers['Referer'] = chapter_url

            # Try multiple times with increasing delays
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    img_response = self.session.get(
                        img_url,
                        headers=headers,
                        timeout=10,
                        allow_redirects=True
                    )
                    img_response.raise_for_status()
                    
                    # Verify we got an image
                    content_type = img_response.headers.get('content-type', '')
                    if not content_type.startswith('image/'):
                        raise ValueError(f"Received non-image content-type: {content_type}")

                    with open(filepath, 'wb') as f:
                        f.write(img_response.content)
                    logger.info(f"Successfully downloaded: {os.path.basename(filepath)}")
                    return True

                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # Progressive delay: 2s, 4s, 6s
                        logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        raise

        except Exception as e:
            logger.error(f"Failed to download {os.path.basename(filepath)}: {str(e)}")
            return False

    def download_chapter(self, chapter):
        """Download all images for a chapter"""
        if self.stop_flag():
            return 0
        
        chapter_name = re.sub(r'[\\/*?:"<>|]', '_', chapter['name'])
        chapter_dir = os.path.join(self.output_dir, chapter_name)
        os.makedirs(chapter_dir, exist_ok=True)
        
        logger.info(f"Downloading chapter: {chapter['name']}")
        image_urls = self.get_chapter_images(chapter['url'])
        
        if not image_urls:
            logger.warning(f"No images found for chapter: {chapter['name']}")
            return 0
            
        logger.info(f"Found {len(image_urls)} images")
        
        # Filter out unwanted images
        image_urls = [url for url in image_urls if not any(
            word in url.lower() for word in ['avatar', 'icon', 'logo', 'banner', 'brand']
        )]
        
        # Download images with multiple threads
        downloaded = 0
        if self.progress_callback:
            self.progress_callback(chapter['name'], 0)
        
        with tqdm(total=len(image_urls), desc=f"Chapter {chapter['name']}") as pbar:
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                future_to_url = {}
                
                for index, url in enumerate(image_urls, 1):
                    ext = url.split('.')[-1].lower()
                    if ext not in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
                        ext = 'jpg'
                    
                    filepath = os.path.join(chapter_dir, f"{index:03d}.{ext}")
                    future = executor.submit(self.download_image, url, filepath, chapter['url'])
                    future_to_url[future] = url
                    
                    # Small delay between starting downloads
                    time.sleep(0.2)
                
                for i, future in enumerate(as_completed(future_to_url)):
                    if self.stop_flag():
                        break
                    if future.result():
                        downloaded += 1
                        pbar.update(1)
                        if self.progress_callback:
                            progress = int((i + 1) / len(image_urls) * 100)
                            self.progress_callback(chapter['name'], progress)
        
        logger.info(f"Downloaded {downloaded}/{len(image_urls)} images for chapter: {chapter['name']}")
        return downloaded

    def download_cover_for_volume(self, volume_path, covers_output_folder=None):
        """
        Download the first image from the first chapter in the given volume folder.
        The cover will be saved as 000.png inside the first chapter folder.
        """
        chapter_folders = [d for d in os.listdir(volume_path) if os.path.isdir(os.path.join(volume_path, d))]
        if not chapter_folders:
            logger.info(f"No chapters found in volume: {volume_path}")
            return False
        chapter_folders_sorted = sorted(chapter_folders, key=natural_key)
        first_chapter = chapter_folders_sorted[0]
        chapter_path = os.path.join(volume_path, first_chapter)

        # Try to find a chapter URL from the folder name
        chapter_url = None
        for chapter in self.chapters:
            if chapter['name'] == first_chapter:
                chapter_url = chapter['url']
                break
        if not chapter_url:
            for chapter in self.chapters:
                if chapter['name'].replace(" ", "").lower() == first_chapter.replace(" ", "").lower():
                    chapter_url = chapter['url']
                    break
        if not chapter_url:
            logger.warning(f"Could not find URL for chapter '{first_chapter}' in volume '{os.path.basename(volume_path)}'")
            return False

        image_urls = self.get_chapter_images(chapter_url)
        if not image_urls:
            logger.warning(f"No images found for chapter '{first_chapter}' in volume '{os.path.basename(volume_path)}'")
            return False

        img_url = image_urls[0]
        ext = "png"
        # Always save as 000.png in the first chapter folder
        cover_path = os.path.join(chapter_path, "000.png")
        success = self.download_image(img_url, cover_path, chapter_url)
        if success:
            logger.info(f"Downloaded cover for volume '{os.path.basename(volume_path)}' to '{cover_path}'")
        return success

    def download_covers_only(self, input_folder, covers_output_folder=None):
        """
        For each volume in input_folder, download the first image from the first chapter as the cover.
        The cover will be saved as 000.png inside the first chapter folder.
        """
        self.chapters = self.get_chapters()
        if not self.chapters:
            logger.error("No chapters found for mapping.")
            return False

        volume_folders = [d for d in os.listdir(input_folder) if os.path.isdir(os.path.join(input_folder, d))]
        volume_folders_sorted = sorted(volume_folders, key=natural_key)
        total = len(volume_folders_sorted)
        logger.info(f"Found {total} volume folders in '{input_folder}'")
        count = 0
        for vol_name in volume_folders_sorted:
            if self.stop_flag():
                break
            vol_path = os.path.join(input_folder, vol_name)
            logger.info(f"Processing volume: {vol_name}")
            if self.download_cover_for_volume(vol_path):
                count += 1
        logger.info(f"Downloaded covers for {count}/{total} volumes.")
        return True

    def parse_chapter_range(self, total_chapters):
        """Parse chapter range and return list of indices to download"""
        if self.chapter_range is None:
            return list(range(total_chapters))
        
        if isinstance(self.chapter_range, (int, float)):
            # Single chapter
            # Convert chapter number to index by finding closest match
            target = float(self.chapter_range)
            for i, chapter in enumerate(self.chapters):
                chapter_num = self.extract_chapter_number(chapter['name'])
                if chapter_num == target:
                    return [i]
            logger.error(f"Chapter {self.chapter_range} not found")
            return []
        
        if isinstance(self.chapter_range, tuple):
            start, end = map(float, self.chapter_range)
            indices = []
            for i, chapter in enumerate(self.chapters):
                chapter_num = self.extract_chapter_number(chapter['name'])
                if start <= chapter_num <= end:
                    indices.append(i)
            if indices:
                return indices
            else:
                logger.error(f"No chapters found in range {start} to {end}")
                return []
        
        return []

    def extract_chapter_number(self, chapter_name):
        """Extract chapter number from chapter name, handling decimal points"""
        # Try to find a decimal number pattern (e.g., 23.5, 100.2, etc.)
        match = re.search(r'(?:chapter\s*)?(\d+\.?\d*)', chapter_name.lower())
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return 0.0

    def run(self):
        """Run the full scraping process"""
        logger.info(f"Starting to scrape manga from: {self.manga_url}")
        
        # Get manga page
        response = requests.get(self.manga_url, headers=self.headers)
        if response.status_code != 200:
            logger.error("Failed to fetch manga page")
            return False
            
        soup = BeautifulSoup(response.content, 'html.parser')
        manga_title = self.get_manga_title(soup)
        logger.info(f"Manga title: {manga_title}")
        
        # Update output directory to include manga title
        manga_title_clean = re.sub(r'[\\/*?:"<>|]', '_', manga_title)
        self.output_dir = os.path.join(self.output_dir, manga_title_clean)
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Get all chapters
        self.chapters = self.get_chapters()  # Store chapters in instance variable
        if not self.chapters:
            logger.error("No chapters found")
            return False
        
        # Get chapters to download based on range
        chapter_indices = self.parse_chapter_range(len(self.chapters))
        chapters_to_download = [self.chapters[i] for i in chapter_indices]
        
        if not chapters_to_download:
            logger.error("No chapters selected for download")
            return False
        
        logger.info(f"Will download {len(chapters_to_download)} chapters")
        
        # Add checkpoint file
        checkpoint_file = os.path.join(self.output_dir, '.checkpoint')
        downloaded_chapters = set()
        
        if os.path.exists(checkpoint_file):
            with open(checkpoint_file, 'r') as f:
                downloaded_chapters = set(f.read().splitlines())
        
        # Download chapters concurrently
        total_downloaded = 0
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:  # Limit to 3 concurrent chapter downloads
                future_to_chapter = {
                    executor.submit(self.download_chapter, chapter): chapter 
                    for chapter in chapters_to_download
                }
                
                for future in as_completed(future_to_chapter):
                    if self.stop_flag():
                        logger.info("Download stopped by user")
                        return False
                    
                    chapter = future_to_chapter[future]
                    try:
                        downloaded = future.result()
                        total_downloaded += downloaded
                        # Update checkpoint file
                        with open(checkpoint_file, 'a') as f:
                            f.write(f"{chapter['name']}\n")
                        time.sleep(self.delay)  # Small delay between chapters
                    except Exception as e:
                        logger.error(f"Error downloading chapter {chapter['name']}: {e}")
            
            logger.info(f"Completed downloading {manga_title}. Total images: {total_downloaded}")
            return True
        
        except Exception as e:
            logger.error(f"Error during download: {e}")
            return False

def main():
    """Main function for Colab interface and CLI"""
    parser = argparse.ArgumentParser(description="WeebCentral Manga Downloader (Colab/CLI)")
    parser.add_argument("--covers-only", action="store_true", help="Download only covers for each volume in a folder")
    parser.add_argument("--input-folder", type=str, help="Input folder containing volume folders (for --covers-only)")
    parser.add_argument("--covers-output-folder", type=str, help="Output folder for covers (if not set, covers are saved in-place)")
    # ...existing code...
    args, unknown = parser.parse_known_args()

    if args.covers_only:
        # Prompt for manga URL and input folder if not provided
        manga_url = input("Enter manga URL: ") if not hasattr(args, "manga_url") or not args.input_folder else None
        input_folder = args.input_folder or input("Enter input folder containing volumes: ")
        covers_output_folder = args.covers_output_folder
        output_dir = input_folder  # Not used for covers-only, but required by constructor
        scraper = WeebCentralScraper(
            manga_url=manga_url,
            output_dir=output_dir
        )
        scraper.download_covers_only(input_folder, covers_output_folder=covers_output_folder)
        return

    # ...existing code...
    display(HTML("<h2>WeebCentral Manga Downloader</h2>"))
    # ...existing code...
    manga_url = input("Enter manga URL: ")
    # ...existing code...

if __name__ == "__main__":
    main()
