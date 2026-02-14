"""
Crop whitespace margins from Facebook screenshot chunks.

57 of 58 chunks have 597px left margin + 91px right margin.
fb5_chunk_000.jpg is the Facebook page header (full-width) — skip it.

Crops in-place (overwrites the chunk files) and updates manifest.json.
"""

import os
import json
from PIL import Image

CHUNKS_DIR = os.path.join(os.path.dirname(__file__), "chunks")
MANIFEST = os.path.join(CHUNKS_DIR, "manifest.json")

# Crop region for the 57 standard chunks (content column)
CROP_LEFT = 597
CROP_RIGHT = 1279  # inclusive, so width = 1279 - 597 + 1 = 683

# The one full-width chunk to skip
SKIP_CHUNKS = {"fb5_chunk_000.jpg"}


def main():
    with open(MANIFEST, "r") as f:
        manifest = json.load(f)

    cropped = 0
    skipped = 0

    for entry in manifest["chunks"]:
        fname = entry["file"]
        fpath = os.path.join(CHUNKS_DIR, fname)

        if fname in SKIP_CHUNKS:
            print(f"  SKIP  {fname} (page header, full-width)")
            skipped += 1
            continue

        if not os.path.exists(fpath):
            print(f"  MISS  {fname} — file not found")
            continue

        img = Image.open(fpath)
        w, h = img.size

        if w <= 700:
            print(f"  DONE  {fname} — already cropped ({w}x{h})")
            skipped += 1
            continue

        # Crop: left=597, top=0, right=1280, bottom=h
        cropped_img = img.crop((CROP_LEFT, 0, CROP_RIGHT + 1, h))
        cropped_img.save(fpath, "JPEG", quality=92)

        new_w, new_h = cropped_img.size
        new_kb = os.path.getsize(fpath) / 1024

        # Update manifest entry
        entry["width"] = new_w
        entry["crop_applied"] = {
            "original_width": w,
            "left": CROP_LEFT,
            "right_edge": CROP_RIGHT + 1,
        }

        print(f"  CROP  {fname}: {w}x{h} -> {new_w}x{new_h} ({new_kb:.0f} KB)")
        cropped += 1

    # Save updated manifest
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone: {cropped} cropped, {skipped} skipped")


if __name__ == "__main__":
    main()
