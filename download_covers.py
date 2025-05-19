import os
import argparse
import requests
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin

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

def main():
    parser = argparse.ArgumentParser(description="Download volume covers by crawling ComicVine volume pages.")
    parser.add_argument("folder", help="Folder to look for subfolders containing the keyword.")
    parser.add_argument("keyword", help="Keyword to filter subfolders (e.g., 'Vol.')")
    parser.add_argument("start_url", help="Starting URL of the first volume page.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (seconds)")
    args = parser.parse_args()

    covers_dir = os.path.join(os.getcwd(), "covers")
    os.makedirs(covers_dir, exist_ok=True)

    # Find all subfolders containing the keyword, sorted by natural key
    subfolders = sorted(
        [f for f in os.listdir(args.folder)
         if os.path.isdir(os.path.join(args.folder, f)) and args.keyword in f],
        key=natural_key
    )
    print(f"Found {len(subfolders)} folders with keyword '{args.keyword}': {subfolders}")

    url = args.start_url
    visited = set()
    idx = 0

    while url and idx < len(subfolders):
        if url in visited:
            print("Detected loop or repeated URL, stopping.")
            break
        visited.add(url)
        print(f"Processing: {url}")

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            break

        soup = BeautifulSoup(resp.content, "html.parser")
        img_url = get_cover_img_url(soup)
        if img_url:
            # Use "<keyword> <idx+1>.jpg" as filename
            ext = os.path.splitext(img_url)[1]
            if not ext or len(ext) > 5:
                ext = ".png"
            cover_name = f"{args.keyword} {idx+1}{ext}"
            save_path = os.path.join(covers_dir, cover_name)
            download_image(img_url, save_path)
        else:
            print("No cover image found on this page.")

        # Find next URL in issue-slide
        next_url = find_next_url_comicvine(soup, url)
        url = next_url
        idx += 1
        time.sleep(args.delay)

    print("Done.")

if __name__ == "__main__":
    main()
