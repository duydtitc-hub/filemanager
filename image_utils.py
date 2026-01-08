from PIL import Image
import os
import base64
from io import BytesIO
from datetime import datetime


def merge_three_images(image_paths, out_path=None, layout='horizontal', spacing=8, bg_color=(255,255,255), max_width=None, max_height=None):
    """
    Merge up to 3 images into one image.

    Args:
      image_paths: list of 1..3 file paths (strings)
      out_path: optional output path (if None, uses OUTPUT_DIR/temp_merged_{ts}.jpg)
      layout: 'horizontal' | 'vertical' | 'grid_2top_1bottom'
      spacing: pixels between images
      bg_color: background color tuple
      max_width / max_height: optional cap to resize final image (keep aspect)
    Returns:
      output_path (str)
    """
    imgs = [Image.open(p).convert('RGB') for p in image_paths]
    if len(imgs) == 0:
        raise ValueError("Need at least one image")
    if len(imgs) > 3:
        imgs = imgs[:3]

    # Helper to resize with LANCZOS
    def resize_keep(img, new_w=None, new_h=None):
        if new_w is None and new_h is None:
            return img
        if new_w is None:
            ratio = new_h / img.height
            new_w = int(img.width * ratio)
        if new_h is None:
            ratio = new_w / img.width
            new_h = int(img.height * ratio)
        return img.resize((new_w, new_h), Image.LANCZOS)

    if layout == 'horizontal':
        min_h = min(i.height for i in imgs)
        imgs = [resize_keep(i, new_h=min_h) for i in imgs]
        total_w = sum(i.width for i in imgs) + spacing * (len(imgs)-1)
        final_h = min_h
        final_w = total_w
        canvas = Image.new('RGB', (final_w, final_h), bg_color)
        x = 0
        for i in imgs:
            canvas.paste(i, (x, 0))
            x += i.width + spacing

    elif layout == 'vertical':
        min_w = min(i.width for i in imgs)
        imgs = [resize_keep(i, new_w=min_w) for i in imgs]
        total_h = sum(i.height for i in imgs) + spacing * (len(imgs)-1)
        final_w = min_w
        final_h = total_h
        canvas = Image.new('RGB', (final_w, final_h), bg_color)
        y = 0
        for i in imgs:
            canvas.paste(i, (0, y))
            y += i.height + spacing

    elif layout == 'grid_2top_1bottom':
        if len(imgs) == 1:
            return merge_three_images(image_paths, out_path=out_path, layout='horizontal', spacing=spacing, bg_color=bg_color, max_width=max_width, max_height=max_height)
        if len(imgs) == 2:
            imgs.append(Image.new('RGB', imgs[0].size, bg_color))
        top_h = min(imgs[0].height, imgs[1].height)
        top_imgs = [resize_keep(imgs[0], new_h=top_h), resize_keep(imgs[1], new_h=top_h)]
        bottom = imgs[2]
        top_w = top_imgs[0].width + top_imgs[1].width + spacing
        bottom_ratio = top_w / bottom.width
        bottom_h = int(bottom.height * bottom_ratio)
        bottom_resized = resize_keep(bottom, new_w=top_w, new_h=bottom_h)
        final_w = top_w
        final_h = top_h + spacing + bottom_h
        canvas = Image.new('RGB', (final_w, final_h), bg_color)
        x = 0
        canvas.paste(top_imgs[0], (0, 0))
        canvas.paste(top_imgs[1], (top_imgs[0].width + spacing, 0))
        canvas.paste(bottom_resized, (0, top_h + spacing))

    else:
        raise ValueError("Unknown layout")

    # Resize final canvas if requested
    if max_width and canvas.width > max_width:
        ratio = max_width / canvas.width
        new_w = int(canvas.width * ratio)
        new_h = int(canvas.height * ratio)
        canvas = canvas.resize((new_w, new_h), Image.LANCZOS)
    if max_height and canvas.height > max_height:
        ratio = max_height / canvas.height
        new_w = int(canvas.width * ratio)
        new_h = int(canvas.height * ratio)
        canvas = canvas.resize((new_w, new_h), Image.LANCZOS)

    if out_path is None:
        out_dir = os.path.join(os.getcwd(), "outputs")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    canvas.save(out_path, quality=90)
    return out_path


def merged_image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()
