from PIL import Image, ImageEnhance, ImageOps

input_file = "Screenshot (1).png"
output_file = "preprocessed.png"

# Open image
image = Image.open(input_file)

# Convert to grayscale
image = ImageOps.grayscale(image)

# Increase contrast
contrast = ImageEnhance.Contrast(image)
image = contrast.enhance(2)

# Upscale image 2x
width, height = image.size
image = image.resize(
    (width * 2, height * 2)
)

# Save processed image
image.save(output_file)

print(f"Preprocessed image saved as: {output_file}")
