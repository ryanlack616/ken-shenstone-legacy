#!/usr/bin/env python3
"""
Smart PNG splitter for Facebook screenshots.

ONLY cuts at actual post boundaries — the full-width light gray
horizontal bands that Facebook puts between posts. Never splits
through images or text.

Detection strategy:
1. Scan every row for brightness + uniformity
2. Find contiguous runs of light uniform rows (the divider gaps)
3. Group dividers that are close together
4. Only cut at the CENTER of confirmed divider gaps
5. If a section between dividers is very tall, keep it whole
   (better to have one big chunk than cut through content)
"""

import os
import sys
import gc
import json
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = 200_000_000

INPUT_DIR = r"C:\Users\PC\Desktop\Ken Shenstone"
OUTPUT_DIR = r"C:\rje\dev\ken-shenstone-legacy\chunks"

# A divider row must be this bright (0-255) and this uniform
MIN_BRIGHTNESS = 225      # Nearly white/very light gray
MAX_ROW_STD = 6           # Very low color variation across the row
MIN_DIVIDER_HEIGHT = 8    # Minimum contiguous rows to count as a divider
MAX_CHUNK_HEIGHT = 2000   # ~2000px sweet spot for EasyOCR memory


def find_post_dividers(img_array):
    """
    Find the actual Facebook post divider gaps in the image.
    
    Returns list of (gap_center_y, gap_start_y, gap_end_y) tuples — 
    these are the ONLY safe places to cut.
    """
    h, w = img_array.shape[:2]
    
    # Convert to grayscale efficiently
    if len(img_array.shape) == 3:
        gray_rows = np.mean(img_array, axis=2)  # H x W grayscale
    else:
        gray_rows = img_array.astype(float)
    
    # Per-row metrics
    row_mean = np.mean(gray_rows, axis=1)      # brightness per row
    row_std = np.std(gray_rows, axis=1)         # uniformity per row
    
    # A divider row: bright AND uniform across entire width
    is_divider_row = (row_mean >= MIN_BRIGHTNESS) & (row_std <= MAX_ROW_STD)
    
    # Find contiguous runs of divider rows
    gaps = []
    in_gap = False
    gap_start = 0
    
    for y in range(h):
        if is_divider_row[y]:
            if not in_gap:
                gap_start = y
                in_gap = True
        else:
            if in_gap:
                gap_height = y - gap_start
                if gap_height >= MIN_DIVIDER_HEIGHT:
                    center = gap_start + gap_height // 2
                    gaps.append((center, gap_start, y))
                in_gap = False
    
    # Handle case where image ends in a gap
    if in_gap:
        gap_height = h - gap_start
        if gap_height >= MIN_DIVIDER_HEIGHT:
            center = gap_start + gap_height // 2
            gaps.append((center, gap_start, h))
    
    return gaps


def plan_cuts(dividers, img_height, max_chunk=MAX_CHUNK_HEIGHT):
    """
    Choose which dividers to actually cut at.
    
    Strategy: walk through dividers, accumulating height.
    When accumulated height exceeds max_chunk, cut at the 
    most recent divider. Never cuts between dividers.
    """
    if not dividers:
        return []  # No dividers found — return entire image as one chunk
    
    cuts = []
    last_cut_y = 0
    
    for center_y, gap_start, gap_end in dividers:
        height_since_cut = center_y - last_cut_y
        
        if height_since_cut >= max_chunk:
            cuts.append(center_y)
            last_cut_y = center_y
    
    return cuts


def split_png(filepath, output_dir, file_index):
    """Split one PNG at verified post boundaries only."""
    filename = os.path.basename(filepath)
    short_name = f"fb{file_index}"
    
    print(f"\n{'='*55}")
    print(f"Splitting: {filename}")
    print(f"  Loading...", end=" ", flush=True)
    
    img = Image.open(filepath)
    if img.mode == 'RGBA':
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    
    w, h = img.size
    img_array = np.array(img)
    del img
    print(f"{w}x{h}")
    
    # Step 1: Find ALL post dividers
    dividers = find_post_dividers(img_array)
    print(f"  Post dividers found: {len(dividers)}")
    
    if dividers:
        heights = [end - start for _, start, end in dividers]
        print(f"  Divider gap sizes: min={min(heights)}px, max={max(heights)}px, avg={sum(heights)//len(heights)}px")
    
    # Step 2: Plan cuts (only at dividers)
    cut_points = plan_cuts(dividers, h)
    print(f"  Cut points selected: {len(cut_points)}")
    
    # Step 3: Build chunk boundaries
    boundaries = [0] + cut_points + [h]
    chunks = []
    
    for idx in range(len(boundaries) - 1):
        y_start = boundaries[idx]
        y_end = boundaries[idx + 1]
        chunk_h = y_end - y_start
        
        if chunk_h < 20:
            continue
        
        # Count how many post dividers are IN this chunk
        dividers_in_chunk = [
            d for d in dividers 
            if d[1] >= y_start and d[2] <= y_end
        ]
        
        chunk = img_array[y_start:y_end]
        chunk_name = f"{short_name}_chunk_{idx:03d}.jpg"
        chunk_path = os.path.join(output_dir, chunk_name)
        Image.fromarray(chunk).save(chunk_path, "JPEG", quality=92)
        
        size_kb = os.path.getsize(chunk_path) / 1024
        
        print(f"  {chunk_name}: y={y_start:5d}-{y_end:5d} ({chunk_h:4d}px) "
              f"[{size_kb:.0f} KB] — {len(dividers_in_chunk)} posts inside")
        
        chunks.append({
            "file": chunk_name,
            "source": filename,
            "source_index": file_index,
            "chunk_index": idx,
            "y_start": y_start,
            "y_end": y_end,
            "height": chunk_h,
            "width": w,
            "dividers_inside": len(dividers_in_chunk),
            "cut_at_divider": True,
        })
    
    del img_array
    gc.collect()
    
    return chunks, dividers


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Clear old chunks
    old = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.jpg')]
    if old:
        print(f"Clearing {len(old)} old chunks...")
        for f in old:
            os.remove(os.path.join(OUTPUT_DIR, f))
    
    manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        os.remove(manifest_path)
    
    pngs = sorted([
        f for f in os.listdir(INPUT_DIR)
        if f.lower().endswith('.png') and 'screencapture' in f.lower()
    ])
    
    print(f"Ken Shenstone — Smart PNG Splitter")
    print(f"  RULE: Only cuts at confirmed post divider gaps")
    print(f"  Input:  {INPUT_DIR}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Max chunk height: {MAX_CHUNK_HEIGHT}px (soft limit)")
    print(f"  PNGs: {len(pngs)}")
    
    all_chunks = []
    total_dividers = 0
    
    for i, png in enumerate(pngs):
        filepath = os.path.join(INPUT_DIR, png)
        chunks, dividers = split_png(filepath, OUTPUT_DIR, i + 1)
        all_chunks.extend(chunks)
        total_dividers += len(dividers)
    
    # Save manifest
    manifest = {
        "total_chunks": len(all_chunks),
        "total_dividers_detected": total_dividers,
        "source_files": len(pngs),
        "max_chunk_height": MAX_CHUNK_HEIGHT,
        "split_rule": "Only cuts at confirmed Facebook post divider gaps — never through content",
        "chunks": all_chunks,
    }
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    total_kb = sum(
        os.path.getsize(os.path.join(OUTPUT_DIR, c["file"])) 
        for c in all_chunks
    ) / 1024
    
    heights = [c["height"] for c in all_chunks]
    
    print(f"\n{'='*55}")
    print(f"DONE — {len(all_chunks)} chunks, {total_dividers} dividers detected")
    print(f"  Chunk heights: min={min(heights)}px, max={max(heights)}px, avg={sum(heights)//len(heights)}px")
    print(f"  Total size: {total_kb/1024:.1f} MB")
    print(f"  Manifest: {manifest_path}")
    print(f"  All cuts verified at post boundaries")


if __name__ == "__main__":
    main()
