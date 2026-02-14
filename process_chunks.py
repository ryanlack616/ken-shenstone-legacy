#!/usr/bin/env python3
"""
Process pre-split Facebook chunks with EasyOCR.

Reads the chunks created by split_pngs.py, runs OCR on each,
detects post boundaries within each chunk, extracts embedded
images, and builds a timeline JSON.

Saves progress after every chunk so it can resume if interrupted.

Usage: python process_chunks.py [--resume] [--force]
  --resume  Skip chunks that already have results (default)
  --force   Reprocess everything from scratch
"""

import json
import os
import sys
import re
import gc
import hashlib
import time
from datetime import datetime
from PIL import Image
import cv2
import numpy as np

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

CHUNKS_DIR = r"C:\rje\dev\ken-shenstone-legacy\chunks"
OUTPUT_DIR = r"C:\rje\dev\ken-shenstone-legacy\extracted"
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "_progress.json")
COOLDOWN_SECONDS = 5  # Let CPU cool between chunks

# Initialize EasyOCR once
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _reader


def ocr_image(img_array):
    """Run EasyOCR on a numpy image array. Returns text string."""
    try:
        reader = get_reader()
        results = reader.readtext(img_array, detail=0, paragraph=True)
        return "\n".join(results).strip()
    except Exception as e:
        return f"[OCR ERROR: {e}]"


def find_dividers_in_chunk(img_array, min_brightness=225, max_std=6, min_height=8):
    """Find post divider gaps within a chunk image."""
    h, w = img_array.shape[:2]
    if len(img_array.shape) == 3:
        gray = np.mean(img_array, axis=2)
    else:
        gray = img_array.astype(float)
    
    row_mean = np.mean(gray, axis=1)
    row_std = np.std(gray, axis=1)
    is_div = (row_mean >= min_brightness) & (row_std <= max_std)
    
    gaps = []
    in_gap = False
    gap_start = 0
    for y in range(h):
        if is_div[y]:
            if not in_gap:
                gap_start = y
                in_gap = True
        else:
            if in_gap:
                if y - gap_start >= min_height:
                    gaps.append((gap_start, y))
                in_gap = False
    if in_gap and h - gap_start >= min_height:
        gaps.append((gap_start, h))
    
    return gaps


def extract_post_images(region, min_size=80, min_width_ratio=0.3):
    """Find embedded images within a post region using contour detection."""
    h, w = region.shape[:2]
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=3)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    images = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if cw < min_size or ch < min_size:
            continue
        if cw < w * min_width_ratio:
            continue
        aspect = cw / ch if ch > 0 else 0
        if aspect > 10 or aspect < 0.1:
            continue
        roi = region[y:y+ch, x:x+cw]
        if roi.size == 0:
            continue
        if np.std(roi) < 20:
            continue
        images.append((x, y, cw, ch, roi))
    
    return images


def detect_signals(text):
    """Analyze OCR text for content signals."""
    signals = {
        "has_see_more": False,
        "has_more_photos": False,
        "more_photos_hint": "",
        "has_video": False,
        "date_hint": "",
        "post_type": "post",
        "tags": [],
        "links": [],
    }
    
    if not text:
        return signals
    
    tl = text.lower()
    
    if "see more" in tl or "see\nmore" in tl:
        signals["has_see_more"] = True
    
    photo_match = re.search(r'\+\s*(\d+)\s*(photo|image|pic)', tl)
    if photo_match:
        signals["has_more_photos"] = True
        signals["more_photos_hint"] = photo_match.group(0)
    
    album_match = re.search(r'(\d+)\s*(photo|image|pic)', tl)
    if album_match and int(album_match.group(1)) > 3:
        signals["has_more_photos"] = True
        signals["more_photos_hint"] = album_match.group(0)
    
    if any(v in tl for v in ["video", "watch"]):
        signals["has_video"] = True
        signals["post_type"] = "video"
    
    urls = re.findall(r'https?://\S+', text)
    if urls:
        signals["links"] = urls
    
    # Date patterns
    for pattern in [
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}',
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s*\d{4}',
        r'\d{1,2}/\d{1,2}/\d{2,4}',
        r'(\d+)\s+(hour|day|week|month|year)s?\s+ago',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            signals["date_hint"] = m.group(0)
            break
    
    # Auto-tags
    tag_map = {
        "kiln": ["kiln", "anagama", "firing", "fire"],
        "pottery": ["pottery", "ceramic", "clay", "glaze"],
        "sale": ["sale", "price", "$", "available"],
        "event": ["event", "festival", "market", "show", "exhibition"],
        "wood": ["wood", "firewood", "cord", "ash"],
        "teabowl": ["teabowl", "tea bowl", "chawan"],
        "community": ["together", "team", "friends", "volunteer"],
    }
    for tag, keywords in tag_map.items():
        if any(kw in tl for kw in keywords):
            signals["tags"].append(tag)
    
    if signals["has_more_photos"] or "photo" in tl:
        signals["post_type"] = "photo"
    
    return signals


def parse_date(hint):
    """Try to parse a date hint into ISO format."""
    if not hint:
        return ""
    from dateutil import parser as dp
    try:
        dt = dp.parse(hint)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def load_progress():
    """Load progress tracking."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, Exception):
            pass
    return {"completed_chunks": [], "last_chunk": -1}


# Cooldown between chunks to prevent CPU overheating
COOLDOWN_SECONDS = 2

def save_progress(progress):
    """Save progress atomically with fsync."""
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(progress, f)
        f.flush()
        os.fsync(f.fileno())
    # Windows-safe: remove then rename
    try:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
        os.rename(tmp, PROGRESS_FILE)
    except OSError:
        # Fallback: just copy
        import shutil
        shutil.copy2(tmp, PROGRESS_FILE)


def save_timeline(timeline, path):
    """Save timeline atomically with fsync."""
    tmp = path + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    try:
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
    except OSError:
        import shutil
        shutil.copy2(tmp, path)


def process_one_chunk(chunk_info, images_dir, slices_dir):
    """Process a single chunk. Returns (posts, images, crawl_targets)."""
    chunk_path = os.path.join(CHUNKS_DIR, chunk_info["file"])
    
    img = Image.open(chunk_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img_array = np.array(img)
    del img
    
    h, w = img_array.shape[:2]
    source_file = chunk_info["source"]
    chunk_idx = chunk_info["chunk_index"]
    y_offset = chunk_info["y_start"]
    
    # Find post boundaries within this chunk
    dividers = find_dividers_in_chunk(img_array)
    
    # Build post regions
    regions = []
    if dividers:
        prev = 0
        for gap_start, gap_end in dividers:
            if gap_start - prev > 50:
                regions.append((prev, gap_start))
            prev = gap_end
        if h - prev > 50:
            regions.append((prev, h))
    else:
        regions = [(0, h)]
    
    posts = []
    images = []
    crawl = []
    
    for ridx, (ry_start, ry_end) in enumerate(regions):
        region = img_array[ry_start:ry_end]
        region_h = ry_end - ry_start
        
        # Post ID
        pid = hashlib.md5(f"{source_file}_{chunk_idx}_{ridx}_{y_offset+ry_start}".encode()).hexdigest()[:12]
        
        # Save slice
        slice_name = f"slice_{chunk_info['source_index']}_{chunk_idx:03d}_{ridx:03d}.jpg"
        slice_path = os.path.join(slices_dir, slice_name)
        Image.fromarray(region).save(slice_path, "JPEG", quality=90)
        
        # OCR
        ocr_text = ocr_image(region)
        
        # Signals
        signals = detect_signals(ocr_text)
        
        # Extract images
        found_images = extract_post_images(region)
        image_entries = []
        for x, y, cw, ch, roi in found_images:
            iid = hashlib.md5(f"{source_file}_{chunk_idx}_{ridx}_{x}_{y}".encode()).hexdigest()[:12]
            img_name = f"img_{iid}.jpg"
            img_path = os.path.join(images_dir, img_name)
            Image.fromarray(roi).save(img_path, "JPEG", quality=92)
            
            entry = {
                "id": iid,
                "source_file": source_file,
                "chunk_index": chunk_idx,
                "region": [x, y + y_offset + ry_start, cw, ch],
                "saved_path": img_name,
                "width": cw,
                "height": ch,
                "is_thumbnail": cw < 200 or ch < 200,
                "needs_crawl": cw < 200 or ch < 200,
            }
            image_entries.append(entry)
            
            if entry["is_thumbnail"]:
                tid = hashlib.md5(f"crawl_img_{iid}".encode()).hexdigest()[:12]
                crawl.append({
                    "id": tid,
                    "type": "full_image",
                    "context": f"Post {pid}, thumbnail {iid}",
                    "priority": "high",
                    "status": "pending",
                })
        
        post = {
            "id": pid,
            "source_file": source_file,
            "chunk_file": chunk_info["file"],
            "chunk_index": chunk_idx,
            "region_index": ridx,
            "y_global": y_offset + ry_start,
            "y_global_end": y_offset + ry_end,
            "height": region_h,
            "slice_file": slice_name,
            "ocr_text": ocr_text,
            "date_hint": signals["date_hint"],
            "date_parsed": parse_date(signals["date_hint"]),
            "post_type": signals["post_type"],
            "has_images": len(image_entries) > 0,
            "image_ids": [e["id"] for e in image_entries],
            "has_more_content": signals["has_see_more"],
            "has_more_photos": signals["has_more_photos"],
            "more_photos_hint": signals["more_photos_hint"],
            "has_video": signals["has_video"],
            "tags": signals["tags"],
            "links": signals["links"],
            "needs_review": True,
        }
        
        posts.append(post)
        images.extend(image_entries)
        
        if signals["has_see_more"]:
            tid = hashlib.md5(f"crawl_text_{pid}".encode()).hexdigest()[:12]
            crawl.append({
                "id": tid,
                "type": "truncated_text",
                "context": f"Post {pid} has 'See more'",
                "priority": "medium",
                "status": "pending",
            })
        
        if signals["has_more_photos"]:
            tid = hashlib.md5(f"crawl_photos_{pid}".encode()).hexdigest()[:12]
            crawl.append({
                "id": tid,
                "type": "album",
                "hint": signals["more_photos_hint"],
                "context": f"Post {pid}",
                "priority": "high",
                "status": "pending",
            })
    
    del img_array
    gc.collect()
    
    return posts, images, crawl


def main():
    force = "--force" in sys.argv
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    images_dir = os.path.join(OUTPUT_DIR, "images")
    slices_dir = os.path.join(OUTPUT_DIR, "slices")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(slices_dir, exist_ok=True)
    
    # Load manifest
    manifest_path = os.path.join(CHUNKS_DIR, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    chunks = manifest["chunks"]
    total = len(chunks)
    
    # Load or reset progress
    if force:
        progress = {"completed_chunks": [], "last_chunk": -1}
        # Clear old output
        for d in [images_dir, slices_dir]:
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
        timeline = {
            "schema_version": "1.0",
            "subject": "Ken Shenstone Ceramic Studio & Albion Anagama",
            "extracted": datetime.now().isoformat(),
            "source_files": manifest.get("source_files", 5),
            "posts": [],
            "images": [],
            "crawl_targets": [],
            "stats": {},
        }
    else:
        progress = load_progress()
        # Try to load existing timeline
        tl_path = os.path.join(OUTPUT_DIR, "timeline.json")
        if os.path.exists(tl_path):
            try:
                with open(tl_path, 'r') as f:
                    timeline = json.load(f)
            except Exception:
                timeline = {
                    "schema_version": "1.0",
                    "subject": "Ken Shenstone Ceramic Studio & Albion Anagama",
                    "extracted": datetime.now().isoformat(),
                    "source_files": manifest.get("source_files", 5),
                    "posts": [],
                    "images": [],
                    "crawl_targets": [],
                    "stats": {},
                }
        else:
            timeline = {
                "schema_version": "1.0",
                "subject": "Ken Shenstone Ceramic Studio & Albion Anagama",
                "extracted": datetime.now().isoformat(),
                "source_files": manifest.get("source_files", 5),
                "posts": [],
                "images": [],
                "crawl_targets": [],
                "stats": {},
            }
    
    done_set = set(progress["completed_chunks"])
    
    print("Ken Shenstone - Chunk Processing Pipeline", flush=True)
    print(f"  Chunks: {total}", flush=True)
    print(f"  Already done: {len(done_set)}", flush=True)
    print(f"  Remaining: {total - len(done_set)}", flush=True)
    print(f"  Mode: {'FORCE (fresh start)' if force else 'RESUME'}", flush=True)
    print("", flush=True)
    
    start_time = time.time()
    
    for i, chunk in enumerate(chunks):
        chunk_file = chunk["file"]
        
        if chunk_file in done_set and not force:
            print(f"[{i+1}/{total}] {chunk_file} - SKIP (done)", flush=True)
            continue
        
        t0 = time.time()
        print(f"[{i+1}/{total}] {chunk_file} ...", end=" ", flush=True)
        
        try:
            posts, images, crawl = process_one_chunk(chunk, images_dir, slices_dir)
            
            timeline["posts"].extend(posts)
            timeline["images"].extend(images)
            timeline["crawl_targets"].extend(crawl)
            
            elapsed = time.time() - t0
            print(f"OK - {len(posts)} posts, {len(images)} imgs [{elapsed:.1f}s]", flush=True)
            
            # Cool down CPU
            time.sleep(COOLDOWN_SECONDS)
            
            # Save progress
            done_set.add(chunk_file)
            progress["completed_chunks"] = list(done_set)
            progress["last_chunk"] = i
            save_progress(progress)
            
            # Save timeline after each chunk
            timeline["stats"] = {
                "total_posts_extracted": len(timeline["posts"]),
                "total_images_extracted": len(timeline["images"]),
                "total_crawl_targets": len(timeline["crawl_targets"]),
                "ocr_engine": "easyocr",
                "chunks_processed": len(done_set),
                "chunks_total": total,
                "elapsed_seconds": round(time.time() - start_time),
            }
            save_timeline(timeline, os.path.join(OUTPUT_DIR, "timeline.json"))
            
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Save what we have so far
            save_progress(progress)
            save_timeline(timeline, os.path.join(OUTPUT_DIR, "timeline.json"))
            continue
    
    total_elapsed = time.time() - start_time
    
    print("", flush=True)
    print("=" * 50, flush=True)
    print("EXTRACTION COMPLETE", flush=True)
    print("=" * 50, flush=True)
    print(f"  Posts:          {len(timeline['posts'])}", flush=True)
    print(f"  Images:         {len(timeline['images'])}", flush=True)
    print(f"  Crawl targets:  {len(timeline['crawl_targets'])}", flush=True)
    print(f"  Time:           {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)", flush=True)
    
    see_more = sum(1 for p in timeline["posts"] if p.get("has_more_content"))
    more_photos = sum(1 for p in timeline["posts"] if p.get("has_more_photos"))
    has_dates = sum(1 for p in timeline["posts"] if p.get("date_hint"))
    
    print(f"  Posts with dates:       {has_dates}", flush=True)
    print(f"  Posts with 'See more':  {see_more}", flush=True)
    print(f"  Posts with more photos: {more_photos}", flush=True)
    print(f"  Timeline: {os.path.join(OUTPUT_DIR, 'timeline.json')}", flush=True)


if __name__ == "__main__":
    main()
