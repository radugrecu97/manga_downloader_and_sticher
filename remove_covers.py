import os
import re
import sys

def natural_key(s):
    # Split string into list of strings and integers for natural sorting
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def find_first_pngs_in_first_chapter_per_volume(root_folder, exclude_chapter=None):
    candidates = []
    # List volume folders sorted naturally
    for vol_name in sorted(os.listdir(root_folder), key=natural_key):
        vol_path = os.path.join(root_folder, vol_name)
        if not os.path.isdir(vol_path):
            continue
        # Find chapter folders inside this volume, sorted naturally
        chapter_folders = [d for d in os.listdir(vol_path) if os.path.isdir(os.path.join(vol_path, d))]
        if not chapter_folders:
            continue
        chapter_folders_sorted = sorted(chapter_folders, key=natural_key)
        first_chapter = chapter_folders_sorted[0]
        # Exclusion logic
        match = re.match(r"Chapter\s+(\d+)", first_chapter, re.IGNORECASE)
        if exclude_chapter is not None and match:
            chap_num = int(match.group(1))
            if chap_num == exclude_chapter:
                continue
        chapter_path = os.path.join(vol_path, first_chapter)
        # Find PNG files in this chapter folder, sorted naturally
        pngs = [f for f in os.listdir(chapter_path) if f.lower().endswith('.png')]
        if not pngs:
            continue
        pngs_sorted = sorted(pngs, key=natural_key)
        first_png = os.path.join(chapter_path, pngs_sorted[0])
        candidates.append(first_png)
    return candidates

def confirm_user(prompt_message):
    while True:
        choice = input(f"{prompt_message} (yes/no, y/n): ").strip().lower()
        if choice in ('yes', 'y'):
            return True
        elif choice in ('no', 'n'):
            return False
        print("Invalid input. Please enter 'yes' or 'no' (or 'y'/'n').")

def main():
    if len(sys.argv) < 2:
        print("Usage: python remove_covers.py <input_folder> [--exclude-chapter <number>]")
        sys.exit(1)
    input_folder = sys.argv[1]
    exclude_chapter = None
    # Parse optional --exclude-chapter argument
    for i, arg in enumerate(sys.argv[2:], start=2):
        if arg in ("--exclude-chapter", "-e") and i + 1 < len(sys.argv):
            try:
                exclude_chapter = int(sys.argv[i + 1])
            except ValueError:
                print("Error: --exclude-chapter requires an integer argument.")
                sys.exit(1)
            break

    png_candidates = find_first_pngs_in_first_chapter_per_volume(input_folder, exclude_chapter)
    if not png_candidates:
        print("No PNG files found for removal.")
        return
    print("The following PNG files are candidates for removal:")
    for idx, path in enumerate(png_candidates):
        print(f"{idx+1}: {path}")
    if not confirm_user("\nRemove ALL the above PNG files?"):
        print("Aborted by user.")
        return
    for path in png_candidates:
        print(f"Removing: {path}")
        os.remove(path)

if __name__ == "__main__":
    main()
