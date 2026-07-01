import os
import re

def get_images_for_slide(paper_id: str, slide_num: int):
    upload_dir = "uploads"
    slides_dir = os.path.join(upload_dir, "slides", paper_id)
    if not os.path.isdir(slides_dir):
        return []
    
    images = []
    for fname in sorted(os.listdir(slides_dir)):
        m = re.match(rf"slide_{slide_num:03d}_img_", fname)
        if m:
            images.append(os.path.join(slides_dir, fname))
    return images

print(get_images_for_slide("30d82e53-ee5a-414c-8b60-29326bdc6f75", 5))
