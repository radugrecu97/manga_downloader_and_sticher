import cv2
import numpy as np
import os
import argparse

def reduce_moire_pandore_like(image_path, output_path, line_thickness=5):
    """
    Reduces Moiré patterns in an image using a Pandore-like script logic.
    Args:
        image_path (str): Path to the input image.
        output_path (str): Path to save the processed image.
        line_thickness (int): Thickness of the central cross mask lines.
    """
    # --- II.0: Read and Prepare Image ---
    # pany2pan input.png input.pan
    # For color images, we'll process the Luminance (Y) channel
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        print(f"Error: Could not read image {image_path}")
        return

    if len(img_bgr.shape) == 3 and img_bgr.shape[2] == 3:
        is_color = True
        img_ycbcr = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
        img_y, img_cr, img_cb = cv2.split(img_ycbcr)
        input_pan = img_y.astype(np.float32) # Pandore often works with float
    elif len(img_bgr.shape) == 2: # Grayscale
        is_color = False
        input_pan = img_bgr.astype(np.float32)
    else:
        print(f"Error: Unsupported image format or channels for {image_path}")
        return

    rows, cols = input_pan.shape
    if rows < 2 or cols < 2:
        print(f"Warning: Image too small {input_pan.shape}. Skipping.")
        cv2.imwrite(output_path, img_bgr) # Save original
        return

    # --- II.1: Fourier Transform & Modulus ---
    # psetcst 0 input.pan tmp1.pan (Imaginary part, np.fft.fft2 handles real input)
    # pfft input.pan tmp1.pan real_pan imag_pan
    fft_result = np.fft.fft2(input_pan)
    
    # pfftshift real_pan imag_pan tmp2_pan tmp3_pan
    fft_shifted = np.fft.fftshift(fft_result)
    real_shifted_pan = np.real(fft_shifted)
    imag_shifted_pan = np.imag(fft_shifted)

    # pmodulus tmp2_pan tmp3_pan modulus_pan
    modulus_pan = np.abs(fft_shifted) # Magnitude of complex numbers

    # logtransform 0 0 255 modulus_pan mod_pan
    # Add 1 to avoid log(0)
    mod_pan = np.log1p(modulus_pan)
    mod_pan_normalized = cv2.normalize(mod_pan, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # --- II.2: Frequency Peak Detection ---
    # pmedianfiltering 3 mod_pan (using mod_pan_normalized as input for CV funcs)
    median_filtered_mod = cv2.medianBlur(mod_pan_normalized, 3)

    # White Top-Hat: WTH(f) = f - opening(f)
    # opening(f) = dilation(erosion(f))
    # perosion 1 8 median_filtered_mod tmp4_pan
    kernel_size = 3 # half-size 1 -> 3x3
    # 8-connectivity approximated by ellipse or rect. Let's use rect for simplicity
    struct_element = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    tmp4_pan = cv2.erode(median_filtered_mod, struct_element, iterations=1)
    
    # pdilatation 1 8 tmp4_pan tmp5_pan (plashing -> dilation)
    tmp5_pan = cv2.dilate(tmp4_pan, struct_element, iterations=1) # This is opening(median_filtered_mod)
    
    # pdif tmp5_pan median_filtered_mod wth_pan  (WTH = f - opening(f))
    # Ensure inputs to subtract are of the same type and positive
    wth_pan = cv2.subtract(median_filtered_mod.astype(np.float32), tmp5_pan.astype(np.float32))
    wth_pan = np.clip(wth_pan, 0, 255).astype(np.uint8) # ensure valid range for binarization

    # pentropybinarization wth_pan freq_pan
    # Using Otsu's binarization as a substitute for entropy binarization
    _, freq_pan = cv2.threshold(wth_pan, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # --- II.3: Deletion of Frequency Peaks (Revised Interpretation) ---
    # Goal: Create a mask that is 0 at detected off-axis peaks, and 1 elsewhere.
    
    # pshapedsign ... horiz.pan / vertic.pan / por / pinverse -> mask1_inv_pan
    # Create a mask that is 0 on the central axes and 1 elsewhere.
    # This mask will be used to select *off-axis* peaks from freq_pan.
    mask_axes_inv = np.ones((rows, cols), dtype=np.uint8) * 255 # Start with all ones (white)
    crow, ccol = rows // 2, cols // 2
    half_thickness = line_thickness // 2
    
    # Make central horizontal and vertical bands zero (black)
    mask_axes_inv[crow - half_thickness : crow + half_thickness + 1, :] = 0 # Horizontal band
    mask_axes_inv[:, ccol - half_thickness : ccol + half_thickness + 1] = 0 # Vertical band

    # pmask freq.pan mask_axes_inv.pan off_axis_peaks_pan
    # This isolates peaks that are *not* on the central axes
    off_axis_peaks_pan = cv2.bitwise_and(freq_pan, freq_pan, mask=mask_axes_inv)

    # pinverse off_axis_peaks_pan final_suppression_mask
    # This mask is 0 where off-axis peaks were, 1 elsewhere.
    # This is the mask to apply to the FFT components.
    # It should be float [0,1] for multiplication with complex FFT data.
    final_suppression_mask_shifted = cv2.bitwise_not(off_axis_peaks_pan).astype(np.float32) / 255.0
    
    # --- II.4: Apply Mask and Inverse Fourier Transform ---
    # The mask `final_suppression_mask_shifted` is already in the shifted domain.
    # We apply it to the shifted real and imaginary parts.
    # `real_shifted_pan` and `imag_shifted_pan` are already computed.

    masked_real_shifted = real_shifted_pan * final_suppression_mask_shifted
    masked_imag_shifted = imag_shifted_pan * final_suppression_mask_shifted

    # Combine back to complex
    fft_masked_shifted = masked_real_shifted + 1j * masked_imag_shifted

    # Inverse shift
    # pifftshift (implicitly part of ifft process if we combine before ifftshift)
    fft_masked_unshifted = np.fft.ifftshift(fft_masked_shifted)

    # pifft tmp9_pan tmp10_pan tmp11_pan tmp12_pan
    img_back_complex = np.fft.ifft2(fft_masked_unshifted)
    tmp11_pan = np.real(img_back_complex) # Real part is the image

    # plineartransform 0 0 255 tmp11_pan tmp13_pan
    # pim2uc tmp13_pan output_pan
    # Normalize and convert back to uint8
    processed_y_channel = cv2.normalize(tmp11_pan, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    if is_color:
        # Merge processed Y channel with original Cr, Cb channels
        ycbcr_processed = cv2.merge([processed_y_channel, img_cr, img_cb])
        result_image = cv2.cvtColor(ycbcr_processed, cv2.COLOR_YCrCb2BGR)
    else:
        result_image = processed_y_channel
        
    # ppan2png output.pan output.png
    cv2.imwrite(output_path, result_image)
    print(f"Processed and saved: {output_path}")


def process_directory_pandore_like(input_dir, output_dir, line_thickness):
    allowed_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')
    for root, _, files in os.walk(input_dir):
        for filename in files:
            if filename.lower().endswith(allowed_extensions):
                input_path = os.path.join(root, filename)
                
                relative_path = os.path.relpath(input_path, input_dir)
                output_path = os.path.join(output_dir, relative_path)
                
                output_subdir = os.path.dirname(output_path)
                if not os.path.exists(output_subdir):
                    os.makedirs(output_subdir)

                print(f"Processing (Pandore-like): {input_path}")
                try:
                    reduce_moire_pandore_like(input_path, output_path, line_thickness)
                except Exception as e:
                    print(f"Error processing {input_path} with Pandore-like script: {e}")
                    # Optionally, copy the original file on error
                    # import shutil
                    # shutil.copy(input_path, output_path)
                    # print(f"Copied original due to error: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reduce Moiré effect in images using Pandore-like script.")
    parser.add_argument("input_dir", help="Directory containing input images.")
    parser.add_argument("output_dir", help="Directory to save processed images.")
    parser.add_argument("--thickness", type=int, default=5,
                        help="Thickness of the central cross mask lines for axis exclusion (pixels). Default: 5")

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"Error: Input directory '{args.input_dir}' not found.")
        exit(1)

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        print(f"Created output directory: {args.output_dir}")

    process_directory_pandore_like(args.input_dir, args.output_dir, args.thickness)
    print("Pandore-like processing complete.")