import os
import re
import shutil
import argparse
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

def fetch_wikipedia_chapter_list(url, volume_prefix="Volume "):
    """
    Fetches and parses the Wikipedia page to get a mapping of volumes to chapter numbers.
    """
    print(f"DEBUG: Starting fetch_wikipedia_chapter_list for URL: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        print(f"DEBUG: Successfully fetched URL. Status code: {response.status_code}")
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')
    volume_map = {} # E.g., {"Volume 1": {1, 2, ...}, "Volume 2": {8, 9, ...}}
    
    main_table = soup.find('table', class_='wikitable')
    if not main_table:
        print("DEBUG: Could not find the main table with class 'wikitable'.")
        return None
    else:
        print("DEBUG: Found a table with class 'wikitable'.")

    current_volume_number_str = "N/A" 
    current_volume_name = "N/A" 

    rows = main_table.find_all('tr') 
    
    print(f"DEBUG: Found {len(rows)} <tr> elements (searched recursively from main_table).")
    
    if not rows:
        print("DEBUG: No <tr> elements found even with recursive search. This is highly unexpected if table exists.")
        return None

    row_counter = 0
    for row in rows:
        row_counter += 1
        
        volume_header_th = row.find('th', scope='row', id=lambda x: x and x.startswith('vol'))
        
        if volume_header_th:
            current_volume_number_str = volume_header_th.get_text(strip=True)
            try:
                current_volume_number = int(current_volume_number_str)
                current_volume_name = f"{volume_prefix}{current_volume_number}"
                volume_map[current_volume_name] = set()
                print(f"DEBUG: Identified Volume Header: '{current_volume_name}' from text '{current_volume_number_str}' in row {row_counter}.")
            except ValueError:
                print(f"DEBUG: Could not parse volume number from '{current_volume_number_str}' in row {row_counter}. Skipping this as volume header.")
                current_volume_name = "N/A (Parse Error)"
            continue 

        if current_volume_name != "N/A" and current_volume_name in volume_map:
            chapter_ols = row.find_all('ol') 
            
            if chapter_ols:
                for ol_index, ol in enumerate(chapter_ols):
                    start_chapter_str = ol.get('start')
                    if start_chapter_str:
                        try:
                            start_chapter_num = int(start_chapter_str)
                        except ValueError:
                            print(f"DEBUG: Could not parse 'start' attribute '{start_chapter_str}' from <ol> tag in row {row_counter}, <ol> index {ol_index}. Skipping this <ol>.")
                            continue
                    else: 
                        print(f"DEBUG: <ol> tag in row {row_counter}, <ol> index {ol_index}, has no 'start' attribute. Inferring start.")
                        if volume_map[current_volume_name]:
                           start_chapter_num = max(volume_map[current_volume_name], default=0) + 1
                        else:
                           start_chapter_num = 1 
                           print(f"DEBUG: No chapters yet for {current_volume_name}, defaulting inferred start to 1 for this <ol>.")
                    
                    lis = ol.find_all('li', recursive=False) 
                    for i, li_tag in enumerate(lis):
                        current_li_chapter_num = start_chapter_num + i
                        volume_map[current_volume_name].add(current_li_chapter_num)

    if not volume_map:
        print("DEBUG: volume_map is empty after processing all rows.")
        any_vol_id = soup.find(lambda tag: tag.name == 'th' and tag.has_attr('id') and tag['id'].startswith('vol'))
        if any_vol_id:
            print("DEBUG: Found at least one element with an ID like 'volX', but it wasn't processed as a volume header. Check row iteration logic or volume header identification.")
        else:
            print("DEBUG: Did not find any element with an ID like 'volX'. The page structure might be different than expected.")
        return None
        
    print(f"DEBUG: Successfully parsed {len(volume_map)} volumes. Final map keys: {list(volume_map.keys())}")
    return volume_map

def get_local_chapters(chapter_dir):
    """
    Scans the directory for chapter folders and extracts their numbers.
    Returns a dictionary mapping original folder name to its float chapter number,
    and a set of integer base chapter numbers found locally.
    """
    print(f"\nScanning local chapter directory: {chapter_dir}...")
    if not os.path.isdir(chapter_dir):
        print(f"Error: Chapter directory '{chapter_dir}' not found.")
        return None, None

    local_chapters_raw = {} # "Chapter 1": 1.0, "Chapter 2.5": 2.5
    local_chapter_base_numbers = set() # {1, 2}

    for item in os.listdir(chapter_dir):
        item_path = os.path.join(chapter_dir, item)
        if os.path.isdir(item_path) and not item.lower().startswith("volume"): # Avoid processing already created volume folders
            match = re.match(r"Chapter\s*([\d\.]+)", item, re.IGNORECASE)
            if match:
                try:
                    num_str = match.group(1)
                    num_float = float(num_str)
                    local_chapters_raw[item] = num_float
                    local_chapter_base_numbers.add(int(num_float))
                except ValueError:
                    print(f"Warning: Could not parse chapter number from folder '{item}'")
    
    print(f"Found {len(local_chapters_raw)} chapter folders locally.")
    if not local_chapters_raw:
        print("No chapter folders like 'Chapter X' found.")
    return local_chapters_raw, local_chapter_base_numbers

def confirm_user(prompt_message):
    """Helper function to get yes/no confirmation from the user."""
    while True:
        choice = input(f"{prompt_message} (yes/no, y/n): ").strip().lower()
        if choice in ('yes', 'y'):
            return True
        elif choice in ('no', 'n'):
            return False
        print("Invalid input. Please enter 'yes' or 'no' (or 'y'/'n').")

def print_wikipedia_map(volume_map_wiki):
    """Prints the parsed Wikipedia chapter map for user review."""
    print("\n--- Parsed Wikipedia Chapter Map ---")
    if not volume_map_wiki:
        print("No data from Wikipedia.")
        return

    def extract_vol_num(vol_name):
        # Extracts the first integer found in the volume name for sorting
        match = re.search(r'(\d+)', vol_name)
        return int(match.group(1)) if match else float('inf')

    for vol_name in sorted(volume_map_wiki.keys(), key=extract_vol_num):
        chap_set = volume_map_wiki[vol_name]
        print(f"{vol_name}: Chapters {', '.join(map(str, sorted(list(chap_set))))}")
    print("--- End of Wikipedia Map ---")

def confirm_grouping_and_discrepancies(volume_map_wiki, local_chapters_raw, all_local_base_numbers, volume_prefix="Volume "):
    """
    Guides the user through confirming chapter groupings and reports discrepancies.
    Returns a map of folders to move if confirmed, otherwise None.
    """
    # Create reverse map: chapter_base_num -> volume_name from Wikipedia
    wiki_chapter_to_volume_map = {}
    for vol_name, chap_set in volume_map_wiki.items():
        for chap_num in chap_set:
            wiki_chapter_to_volume_map[chap_num] = vol_name

    proposed_grouping_exact = defaultdict(list)
    proposed_grouping_assignable = defaultdict(list)
    unknown_local_chapter_folders = {} # folder_name -> float_chapter_num

    for folder_name, local_chap_float in local_chapters_raw.items():
        local_chap_base = int(local_chap_float)
        
        if local_chap_base in wiki_chapter_to_volume_map:
            target_volume = wiki_chapter_to_volume_map[local_chap_base]
            if local_chap_base == local_chap_float: # e.g. Chapter 5 (is 5.0)
                proposed_grouping_exact[target_volume].append(folder_name)
            else: # e.g. Chapter 5.5, and base Chapter 5 is on Wikipedia
                proposed_grouping_assignable[target_volume].append(folder_name)
        else:
            unknown_local_chapter_folders[folder_name] = local_chap_float

    print("\n--- Proposed Chapter Grouping (Step 1/2) ---")
    final_folders_to_move = defaultdict(list)
    
    if proposed_grouping_exact:
        print("\nLocal chapters with EXACT base match to Wikipedia (will be grouped by default):")
        for vol, folders in sorted(proposed_grouping_exact.items(), key=lambda x: float(re.search(r'(\d+)', x[0]).group(1)) if re.search(r'(\d+)', x[0]) else float('inf')):
            # Sort folders numerically by chapter number
            folders_sorted = sorted(
                folders,
                key=lambda f: float(re.search(r'([\d\.]+)', f).group(1)) if re.search(r'([\d\.]+)', f) else float('inf')
            )
            print(f"  {vol}: {', '.join(folders_sorted)}")
            final_folders_to_move[vol].extend(folders)
    else:
        print("\nNo local chapters found with an exact base match to Wikipedia.")

    if proposed_grouping_assignable:
        print("\nLocal chapters with DECIMAL numbers (e.g., 'Chapter X.Y') where base 'X' IS on Wikipedia:")
        for vol, folders in sorted(proposed_grouping_assignable.items()):
            folders_sorted = sorted(folders, key=lambda f: float(re.search(r'([\d\.]+)', f).group(1)) if re.search(r'([\d\.]+)', f) else float('inf'))
            print(f"  For {vol} (based on their integer part): {', '.join(folders_sorted)}")
        
        if confirm_user("\nDo you want to include these decimal chapters in the grouping as shown above?"):
            for vol, folders in proposed_grouping_assignable.items():
                final_folders_to_move[vol].extend(folders)
            print("Decimal chapters will be included in the grouping.")
        else:
            print("Decimal chapters will NOT be included and will be treated as 'unknown'.")
            for folders_list in proposed_grouping_assignable.values():
                for folder in folders_list:
                    unknown_local_chapter_folders[folder] = local_chapters_raw[folder]
    else:
        print("\nNo local chapters with assignable decimal numbers found.")

    # --- Confirm grouping again after decimal chapters ---
    print("\n--- Confirm Final Volume Grouping (Step 1b/2) ---")
    for vol_name, folders in sorted(final_folders_to_move.items(), key=lambda x: float(re.search(r'(\d+)', x[0]).group(1)) if re.search(r'(\d+)', x[0]) else float('inf')):
        folders_sorted = sorted(
            folders,
            key=lambda f: float(re.search(r'([\d\.]+)', f).group(1)) if re.search(r'([\d\.]+)', f) else float('inf')
        )
        print(f"{vol_name}: {', '.join(folders_sorted)}")
    if not confirm_user("\nDoes the above final grouping look correct?"):
        print("Exiting based on user input.")
        return None

    print("\n--- Discrepancy Report (Step 2/2) ---")
    
    missing_locally_report = defaultdict(list)
    if all_local_base_numbers is not None:
        for vol_name, wiki_chap_set in volume_map_wiki.items():
            for wiki_chap_num in wiki_chap_set:
                if wiki_chap_num not in all_local_base_numbers:
                    missing_locally_report[vol_name].append(wiki_chap_num)

    if missing_locally_report:
        print("\nINFO: The following chapters are listed on Wikipedia, but NO local folder (even decimal) has this base number:")
        for vol, chaps in sorted(missing_locally_report.items()):
            print(f"  {vol}: Chapters {', '.join(map(str, sorted(list(chaps))))}")
    else:
        print("\nINFO: All chapters listed on Wikipedia appear to have a corresponding local folder (based on integer part).")

    # --- Prompt before bundling unknown chapters into Volume 99 ---
    if unknown_local_chapter_folders:
        vol99 = f"{volume_prefix}99"
        folders = list(unknown_local_chapter_folders.keys())
        folders_sorted = sorted(folders, key=lambda f: float(re.search(r'([\d\.]+)', f).group(1)) if re.search(r'([\d\.]+)', f) else float('inf'))
        print(f"\nThe following chapters are unknown/unassigned and would be bundled into:\n{vol99}: {', '.join(folders_sorted)}")
        if confirm_user(f"\nDo you want to group these chapters into '{vol99}'?"):
            for folder in folders_sorted:
                final_folders_to_move[vol99].append(folder)
        else:
            print("These chapters will NOT be grouped into Volume 99 and will remain ungrouped.")
    else:
        print("\nINFO: All found local chapters were either proposed for grouping or are not present.")
        
    if not final_folders_to_move:
        print("\nNo chapters are slated for grouping. Nothing to move.")
        return None
        
    print("\n--- Summary of Folders to be Moved ---")
    def extract_vol_num(vol_name):
        # Extracts the first integer found in the volume name for sorting
        match = re.search(r'(\d+)', vol_name)
        return int(match.group(1)) if match else float('inf')

    def extract_chap_num(chap_name):
        # Extracts the first float found in the chapter name for sorting
        match = re.search(r'([\d\.]+)', chap_name)
        return float(match.group(1)) if match else float('inf')

    for vol_name, folders in sorted(final_folders_to_move.items(), key=lambda x: extract_vol_num(x[0])):
        folders_sorted = sorted(folders, key=extract_chap_num)
        print(f"{vol_name}: {', '.join(folders_sorted)}")
            
    if confirm_user("Proceed with creating volume folders and moving these chapters?"):
        return final_folders_to_move
    else:
        return None

def organize_chapters(chapter_dir, final_assignment, volume_prefix="Volume "):
    """
    Creates volume folders and moves chapter folders into them.
    """
    print("\n--- Organizing Chapters ---")
    if not final_assignment:
        print("No assignments to process. Nothing will be moved.")
        return

    for volume_name, chapter_folders in final_assignment.items():
        if not volume_name.startswith(volume_prefix):
            volume_folder = f"{volume_prefix}{volume_name}"
        else:
            volume_folder = volume_name
        volume_path = os.path.join(chapter_dir, volume_folder)
        os.makedirs(volume_path, exist_ok=True)
        print(f"Created/Ensured directory: {volume_path}")

        for folder_name in chapter_folders:
            source_path = os.path.join(chapter_dir, folder_name)
            destination_path = os.path.join(volume_path, folder_name)

            if os.path.exists(source_path):
                try:
                    print(f"Moving '{source_path}' to '{destination_path}'")
                    shutil.move(source_path, destination_path)
                except Exception as e:
                    print(f"Error moving '{source_path}': {e}")
            else:
                print(f"Warning: Source folder '{source_path}' not found for moving.")
    print("\nChapter organization complete.")

def main():
    parser = argparse.ArgumentParser(description="Organize manga chapter folders into volumes based on Wikipedia.")
    parser.add_argument("wiki_url", help="URL of the Wikipedia page listing manga chapters.")
    parser.add_argument("chapter_dir", help="Path to the directory containing chapter folders (e.g., 'Chapter 1', 'Chapter 2').")
    parser.add_argument("--volume-prefix", default="Volume ", help="Prefix for volume folders (default: 'Volume ')")
    
    args = parser.parse_args()

    # STAGE 1: WIKIPEDIA DATA
    volume_map_wiki = fetch_wikipedia_chapter_list(args.wiki_url, volume_prefix=args.volume_prefix)
    if not volume_map_wiki:
        print("Failed to get chapter list from Wikipedia. Exiting.")
        return
    
    print_wikipedia_map(volume_map_wiki)
    if not confirm_user("\nDoes the Wikipedia chapter mapping look correct?"):
        print("Exiting based on user input.")
        return

    # STAGE 2: LOCAL DATA
    local_chapters_raw, all_local_base_numbers = get_local_chapters(args.chapter_dir)
    if not local_chapters_raw:
        print("Exiting due to no local chapters found or directory issue.")
        return

    # STAGE 3: RECONCILIATION & PROPOSED GROUPING (includes its own confirmations)
    folders_to_move_map = confirm_grouping_and_discrepancies(
        volume_map_wiki, 
        local_chapters_raw,
        all_local_base_numbers,
        volume_prefix=args.volume_prefix
    )

    # STAGE 4: EXECUTION
    if folders_to_move_map:
        organize_chapters(args.chapter_dir, folders_to_move_map, volume_prefix=args.volume_prefix)
    else:
        print("\nNo chapter organization will be performed (either cancelled or no chapters to move).")

if __name__ == "__main__":
    main()