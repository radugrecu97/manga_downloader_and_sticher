import os
import re
import argparse
from ebooklib import epub

def natural_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def find_epubs(folder):
    epub_files = []
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(('.epub', '.kepub')):
                epub_files.append(os.path.join(root, file))
    return sorted(epub_files, key=natural_key)

def print_epub_metadata(epub_path):
    print(f"\n=== {os.path.basename(epub_path)} ===")
    try:
        book = epub.read_epub(epub_path)
        # ebooklib's metadata is a dict: {namespace: {name: [values]}}
        for namespace, ns_dict in book.metadata.items():
            for name, values in ns_dict.items():
                for value in values:
                    print(f"{namespace}:{name} = {value}")
    except Exception as e:
        print(f"  Failed to read metadata: {e}")

def main():
    parser = argparse.ArgumentParser(description="Print EPUB metadata for files in a folder.")
    parser.add_argument("folder", help="Folder containing EPUB files (recursively).")
    parser.add_argument("--num", type=int, default=None, help="Number of EPUBs to print (default: all)")
    args = parser.parse_args()

    epub_files = find_epubs(args.folder)
    if not epub_files:
        print("No EPUB files found.")
        return

    if args.num is not None:
        epub_files = epub_files[:args.num]

    print(f"Found {len(epub_files)} EPUB files:")
    for f in epub_files:
        print_epub_metadata(f)

if __name__ == "__main__":
    main()
