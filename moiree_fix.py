import cv2
import numpy as np
import os
import argparse

def reduce_moire_frequency(image_path, output_path):
    # Load the image in grayscale
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    
    if img is None:
        print(f"Error: Image not found at {image_path}")
        return

    # Perform Fourier Transform
    f = np.fft.fft2(img)
    fshift = np.fft.fftshift(f)  # Shift zero-frequency components to the center
    
    # Create a mask to filter out high-frequency noise
    rows, cols = img.shape
    crow, ccol = rows // 2, cols // 2
    radius = 30  # Adjust this for better results
    mask = np.ones((rows, cols), np.uint8)
    cv2.circle(mask, (ccol, crow), radius, 0, -1)  # Create a circular low-pass filter

    # Apply the mask to the frequency domain
    fshift_filtered = fshift * mask

    # Perform inverse FFT to get the filtered image
    f_ishift = np.fft.ifftshift(fshift_filtered)
    img_filtered = np.fft.ifft2(f_ishift)
    img_filtered = np.abs(img_filtered)

    # Save the resulting image
    cv2.imwrite(output_path, img_filtered)
    print(f"Moire reduction using frequency domain completed. Saved as {output_path}")

def process_images_in_folder(input_folder, output_folder):
    # Get a list of all images in the input folder
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    image_files = [f for f in os.listdir(input_folder) if f.endswith(('.jpg', '.jpeg', '.png', '.bmp'))]

    for image_file in image_files:
        input_path = os.path.join(input_folder, image_file)
        output_path = os.path.join(output_folder, f"reduced_{image_file}")
        reduce_moire_frequency(input_path, output_path)

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Reduce moiré effect in images using frequency domain filtering.")
    parser.add_argument('input_folder', type=str, help="Path to the folder containing input images")
    parser.add_argument('output_folder', type=str, help="Path to the folder to save the processed images")
    
    # Parse arguments
    args = parser.parse_args()

    # Process images in the provided folder
    process_images_in_folder(args.input_folder, args.output_folder)
