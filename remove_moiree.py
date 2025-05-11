import os
import shutil
from PIL import Image
import cv2
import numpy as np
import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- MOIRÉ REMOVAL & CALIBRATION SCRIPT FUNCTIONS ---

def pshape_design_rectangle_2d(img_width, img_height, rect_diameter_h, rect_length_w):
    output_image = np.zeros((img_height, img_width), dtype=np.uint8)
    rect_h = int(rect_diameter_h)
    rect_w = int(rect_length_w)
    center_x_img = img_width // 2
    center_y_img = img_height // 2
    start_x = center_x_img - rect_w // 2
    start_y = center_y_img - rect_h // 2
    end_x = start_x + rect_w
    end_y = start_y + rect_h
    draw_start_x = max(0, start_x)
    draw_end_x = min(img_width, end_x)
    draw_start_y = max(0, start_y)
    draw_end_y = min(img_height, end_y)
    if draw_start_x < draw_end_x and draw_start_y < draw_end_y:
        output_image[draw_start_y:draw_end_y, draw_start_x:draw_end_x] = 255
    return output_image

def pentropy_binarization(gray_image):
    if gray_image.ndim != 2 or gray_image.dtype != np.uint8:
        raise ValueError("Input must be a 2D uint8 grayscale image.")
    hist_counts = cv2.calcHist([gray_image], [0], None, [256], [0, 256]).ravel()
    total_pixels = gray_image.size
    if total_pixels == 0:
        return 0, np.zeros_like(gray_image, dtype=np.uint8)
    p_i = hist_counts / total_pixels 
    p_i_ln_p_i = np.zeros_like(p_i, dtype=np.float64)
    non_zero_indices = p_i > 1e-9
    p_i_ln_p_i[non_zero_indices] = p_i[non_zero_indices] * np.log(p_i[non_zero_indices])
    max_TE = -np.inf
    optimal_threshold = 0
    for s_threshold in range(255):
        P_s = np.sum(p_i[0 : s_threshold + 1])
        P_s_foreground = 1.0 - P_s
        if P_s < 1e-9 or P_s_foreground < 1e-9:
            continue
        H_s = np.sum(p_i_ln_p_i[0 : s_threshold + 1])
        H_s_prime = np.sum(p_i_ln_p_i[s_threshold + 1 : 256])
        term1 = np.log(P_s * P_s_foreground)
        term2 = H_s / P_s
        term3 = H_s_prime / P_s_foreground
        TE_s = term1 - term2 - term3
        if TE_s > max_TE:
            max_TE = TE_s
            optimal_threshold = s_threshold
    if max_TE == -np.inf: 
        optimal_threshold = 127 
        print("  Warning: Pentropy binarization failed to find a valid threshold, defaulting to 127.")
    _, binary_image = cv2.threshold(gray_image, optimal_threshold, 255, cv2.THRESH_BINARY)
    return optimal_threshold, binary_image

def remove_moire_algorithm(gray_image_input):
    if gray_image_input.ndim != 2:
        print(f"  Warning: remove_moire_algorithm received image with dims {gray_image_input.ndim}")
    gray_image_float = gray_image_input.astype(np.float32)

    f_transform = np.fft.fft2(gray_image_float)
    f_transform_shifted = np.fft.fftshift(f_transform)
    magnitude_spectrum_shifted = np.abs(f_transform_shifted)
    log_magnitude_spectrum = np.log1p(magnitude_spectrum_shifted) 
    mod_pan = cv2.normalize(log_magnitude_spectrum, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    mod_pan_median_filtered = cv2.medianBlur(mod_pan, 7)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 17))
    opening = cv2.morphologyEx(mod_pan_median_filtered, cv2.MORPH_OPEN, kernel)
    wth_pan = cv2.subtract(mod_pan_median_filtered, opening)

    if wth_pan.dtype != np.uint8:
        wth_pan_uint8 = cv2.normalize(wth_pan, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    else:
        wth_pan_uint8 = wth_pan
    thresh_val, freq_pan = pentropy_binarization(wth_pan_uint8)
    print(f"    (Used Pentropy (Kapur's) for FFT peak binarization, threshold={thresh_val})")

    rows_fft, cols_fft = freq_pan.shape
    horiz_bar = pshape_design_rectangle_2d(cols_fft, rows_fft, 23, cols_fft)
    vertic_bar = pshape_design_rectangle_2d(cols_fft, rows_fft, rows_fft, 12)
    axis_cross_mask = cv2.bitwise_or(horiz_bar, vertic_bar)
    inverted_axis_cross_mask = cv2.bitwise_not(axis_cross_mask)
    peaks_to_remove = cv2.bitwise_and(freq_pan, inverted_axis_cross_mask)
    spectrum_multiplicative_mask_shifted = cv2.bitwise_not(peaks_to_remove)
    spectrum_multiplicative_mask_unshifted = np.fft.ifftshift(spectrum_multiplicative_mask_shifted)
    spectrum_multiplicative_mask_unshifted_float = spectrum_multiplicative_mask_unshifted / 255.0
    f_transform_masked = f_transform * spectrum_multiplicative_mask_unshifted_float
    img_reconstructed_complex = np.fft.ifft2(f_transform_masked)
    img_reconstructed_real = np.real(img_reconstructed_complex)
    result_img_normalized = cv2.normalize(img_reconstructed_real, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    return result_img_normalized

def normalize_image(original_gray_cv, processed_gray_cv):
    print("    Applying normalization...")
    white_mask = original_gray_cv >= 255
    black_mask = original_gray_cv <= 0
    white_vals = processed_gray_cv[white_mask]
    black_vals = processed_gray_cv[black_mask]
    avg_white = white_vals.mean() if white_vals.size else 255.0
    avg_black = black_vals.mean() if black_vals.size else 0.0
    norm = processed_gray_cv.astype(np.float32)
    denom = avg_white - avg_black if avg_white != avg_black else 1.0
    norm = (norm - avg_black) / denom
    norm = np.clip(norm, 0, 1)
    norm = (norm * 255).astype(np.uint8)
    norm[black_mask] = original_gray_cv[black_mask]
    norm[white_mask] = original_gray_cv[white_mask]
    return norm

def process_and_save_moire_removed_image(input_image_path, output_image_path):
    original_pil = Image.open(input_image_path)
    gray_pil = original_pil.convert("L")
    original_gray_cv = np.array(gray_pil)
    if original_gray_cv.dtype != np.uint8:
        original_gray_cv = cv2.normalize(original_gray_cv, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

    print(f"  Applying moiré removal to {os.path.basename(input_image_path)}...")
    moire_removed_cv = remove_moire_algorithm(original_gray_cv.copy())
    final_image_cv = normalize_image(original_gray_cv, moire_removed_cv)
    cv2.imwrite(output_image_path, final_image_cv)
    print(f"  Saved final processed image to {output_image_path}")

# --- IMAGE WORKFLOW FUNCTIONS ---

def natural_key(s):
    """Sort helper: natural order for strings with numbers."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def is_grayscale(image_path):
    image = Image.open(image_path)
    if image.mode in ('RGB', 'RGBA'):
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = pixels[x, y][:3]
                if r != g or g != b:
                    return False
        return True
    elif image.mode == 'L':
        return True
    return False

def process_single_image(input_path, output_path, output_dir):
    try:
        try:
            with Image.open(input_path) as test_img:
                test_img.verify()
        except Exception:
            print(f"  Skipping non-image or corrupted file: {os.path.basename(input_path)}")
            if not os.path.exists(output_path) or \
               os.path.getmtime(input_path) > os.path.getmtime(output_path):
                shutil.copy2(input_path, output_path)
            return

        if is_grayscale(input_path):
            print(f"Processing grayscale image: {os.path.basename(input_path)}")
            process_and_save_moire_removed_image(input_path, output_path)
        else:
            print(f"  Non-grayscale image: {os.path.basename(input_path)}. Copying directly.")
            if not os.path.exists(output_path) or \
               os.path.getmtime(input_path) > os.path.getmtime(output_path):
                shutil.copy2(input_path, output_path)
                print(f"    Copied: {os.path.basename(input_path)} to {output_dir}")
            else:
                print(f"    Skipped copying {os.path.basename(input_path)}, output is newer or same.")
    except Exception as e:
        print(f"  Failed to process {os.path.basename(input_path)}: {e}")
        import traceback
        traceback.print_exc()

def process_images_in_folder(input_folder_path, output_folder_path, max_workers=8):
    jobs = []
    for root, dirs, files in os.walk(input_folder_path):
        dirs.sort(key=natural_key)
        rel_path = os.path.relpath(root, input_folder_path)
        output_dir = os.path.join(output_folder_path, rel_path) if rel_path != '.' else output_folder_path
        os.makedirs(output_dir, exist_ok=True)
        sorted_filenames = sorted(files, key=natural_key)
        for filename in sorted_filenames:
            input_path = os.path.join(root, filename)
            output_path = os.path.join(output_dir, filename)
            if os.path.isfile(input_path):
                jobs.append((input_path, output_path, output_dir))
    # Parallel processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_single_image, inp, outp, outdir) for inp, outp, outdir in jobs]
        for _ in as_completed(futures):
            pass  # Just to ensure all tasks complete

if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(description="Process images: moiré removal for grayscales, calibration, copy others.")
    cli_parser.add_argument("input_folder", type=str, help="Folder containing input images.")
    cli_parser.add_argument("output_folder", type=str, help="Folder where processed images will be saved.")
    
    args = cli_parser.parse_args()

    if not os.path.isdir(args.input_folder):
        print(f"Error: Input folder '{args.input_folder}' not found.")
        exit()

    process_images_in_folder(args.input_folder, args.output_folder)
    print("\nProcessing complete.")
