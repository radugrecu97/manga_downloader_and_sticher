import os
import argparse
import requests
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

def natural_key(s):
    # Split string into list of ints and strs for natural sorting
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def download_image(img_url, save_path):
    try:
        resp = requests.get(img_url, stream=True, timeout=15)
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(1024):
                f.write(chunk)
        print(f"Downloaded: {save_path}")
    except Exception as e:
        print(f"Failed to download {img_url}: {e}")

def find_next_url_comicvine(soup, current_url):
    # Find the current active slide, then get the next one in the list
    slides = soup.select(".issue-slide li")
    if not slides:
        return None
    active_idx = None
    for idx, li in enumerate(slides):
        if 'on' in li.get('class', []):
            active_idx = idx
            break
    if active_idx is None:
        active_idx = 0
    next_idx = active_idx + 1
    if next_idx >= len(slides):
        return None
    next_a = slides[next_idx].find('a')
    if next_a and next_a.has_attr('href'):
        next_url = next_a['href']
        return urljoin(current_url, next_url)
    return None

def get_cover_img_url(soup):
    # ComicVine: <div class="issue-cover"><img src="..."></div>
    cover_div = soup.find("div", class_="issue-cover")
    if cover_div:
        img = cover_div.find("img")
        if img and img.has_attr("src"):
            return img["src"]
    return None

def prompt_confirm(prompt):
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp == "y" or resp == "yes"

def fetch_cover_url(start_url, idx, max_volumes):
    # Crawl from start_url, following next links, and collect cover URLs for each volume
    covers = []
    url = start_url
    visited = set()
    for i in range(max_volumes):
        if not url or url in visited:
            covers.append(None)
            url = None
            continue
        visited.add(url)
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            img_url = get_cover_img_url(soup)
            covers.append(img_url)
            url = find_next_url_comicvine(soup, url)
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            covers.append(None)
            url = None
    return covers

def main():
    parser = argparse.ArgumentParser(description="Download volume covers by crawling ComicVine volume pages.")
    parser.add_argument("manga_folder", help="Folder containing all volume folders (e.g., ./manga_downloads/Vagabond/)")
    parser.add_argument("keyword", help="Keyword to filter subfolders (e.g., 'Vol.')")
    parser.add_argument("start_url", help="Starting URL of the first volume page.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (seconds, only used for moving covers)")
    parser.add_argument("--max_workers", type=int, default=8, help="Number of parallel downloads")
    args = parser.parse_args()

    covers_dir = os.path.join(os.getcwd(), "covers")
    os.makedirs(covers_dir, exist_ok=True)

    # Find all volume folders containing the keyword, sorted by natural key
    volume_folders = sorted(
        [f for f in os.listdir(args.manga_folder)
         if os.path.isdir(os.path.join(args.manga_folder, f)) and args.keyword in f],
        key=natural_key
    )
    print(f"Found {len(volume_folders)} folders with keyword '{args.keyword}': {volume_folders}")

    # Crawl and collect all cover URLs in order
    print("Collecting cover URLs...")
    cover_urls = fetch_cover_url(args.start_url, 0, len(volume_folders))

    # Download covers in parallel
    print("Downloading covers in parallel...")
    cover_paths = [None] * len(volume_folders)
    cover_names = [None] * len(volume_folders)
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {}
        for idx, img_url in enumerate(cover_urls):
            if img_url:
                ext = os.path.splitext(img_url)[1]
                if not ext or len(ext) > 5:
                    ext = ".png"
                cover_name = f"{args.keyword} {idx+1}{ext}"
                save_path = os.path.join(covers_dir, cover_name)
                cover_names[idx] = cover_name
                futures[executor.submit(download_image, img_url, save_path)] = (idx, save_path)
            else:
                cover_names[idx] = None
                cover_paths[idx] = None
        for future in as_completed(futures):
            idx, save_path = futures[future]
            cover_paths[idx] = save_path if os.path.exists(save_path) else None

    # For each volume folder, find the first chapter folder (sorted by natural key)
    move_plan = []
    for vol_idx, vol_folder in enumerate(volume_folders):
        vol_path = os.path.join(args.manga_folder, vol_folder)
        if not os.path.isdir(vol_path):
            move_plan.append((None, None, None))
            continue
        chapter_folders = sorted(
            [f for f in os.listdir(vol_path)
             if os.path.isdir(os.path.join(vol_path, f))],
            key=natural_key
        )
        if chapter_folders:
            first_chapter = chapter_folders[0]
            first_chapter_path = os.path.join(vol_path, first_chapter)
            move_plan.append((cover_paths[vol_idx], first_chapter_path, vol_folder))
        else:
            move_plan.append((cover_paths[vol_idx], None, vol_folder))

    # Print mapping
    print("\nPlanned cover moves:")
    for idx, (cover_path, chapter_path, vol_folder) in enumerate(move_plan):
        if cover_path and chapter_path:
            print(f"Cover {os.path.basename(cover_path)} -> {chapter_path}/000.png")
        elif cover_path:
            print(f"Cover {os.path.basename(cover_path)} -> [NO CHAPTER FOLDER in {vol_folder}]")
        else:
            print(f"[NO COVER] for {vol_folder}")

    if not prompt_confirm("\nProceed with moving covers as above?"):
        print("Aborted by user.")
        return

    # Move and rename covers
    for cover_path, chapter_path, vol_folder in move_plan:
        if cover_path and chapter_path:
            dest_path = os.path.join(chapter_path, "000.png")
            try:
                os.makedirs(chapter_path, exist_ok=True)
                os.replace(cover_path, dest_path)
                print(f"Moved {os.path.basename(cover_path)} -> {dest_path}")
            except Exception as e:
                print(f"Failed to move cover to {dest_path}: {e}")

    print("Done.")

if __name__ == "__main__":
    main()
