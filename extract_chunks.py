#!/usr/bin/env python3
"""
Ken Shenstone — Chunk-based Facebook extraction.

Processes the pre-split chunks (from split_pngs.py) one at a time.
Each chunk is ~4000px tall JPEG — manageable for EasyOCR.

Finds individual posts within each chunk, OCRs them, extracts
embedded images, detects "See more" / "more photos" signals,
and builds a unified timeline.json.

Saves progress after EVERY chunk so a crash doesn't lose work.

Usage:
    python extract_chunks.py [--resume]
"""

import json
import os
import sys
import gc
import re
import hashlib
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
import cv2
import numpy as np

Image.MAX_IMAGE_PIXELS = 200_000_000

# ── Paths ──────────────────────────────────────────────────────────────

CHUNKS_DIR = r"C:\rje\dev\ken-shenstone-legacy\chunks"
OUTPUT_DIR = r"C:\rje\dev\ken-shenstone-legacy\extracted"
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "_progress.json")

# ── OCR Setup ──────────────────────────────────────────────────────────

HAS_OCR = False
OCR_ENGINE = None
_easyocr_reader = None

try:
    import easyocr
    HAS_OCR = True
    OCR_ENGINE = "easyocr"
except ImportError:
    pass

if not HAS_OCR:
    try:
        import pytesseract
        import shutil
        for tp in [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                   r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]:
            if os.path.exists(tp):
                pytesseract.pytesseract.tesseract_cmd = tp
                HAS_OCR = True
                OCR_ENGINE = "tesseract"
                break
        if not HAS_OCR and shutil.which("tesseract"):
            HAS_OCR = True
            OCR_ENGINE = "tesseract"
    except ImportError:
        pass


def get_ocr_reader():
    global _easyocr_reader
    if OCR_ENGINE == "easyocr" and _easyocr_reader is None:
        print("  Loading EasyOCR model...", end=" ", flush=True)
        _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        print("done.", flush=True)
    return _easyocr_reader


def ocr_region(region_array):
    """Run OCR on a numpy array region."""
    if not HAS_OCR:
        return ""
    try:
        if OCR_ENGINE == "easyocr":
            reader = get_ocr_reader()
            results = reader.readtext(region_array, detail=0, paragraph=True)
            return "\n".join(results).strip()
        elif OCR_ENGINE == "tesseract":
            pil_img = Image.fromarray(region_array)
            return pytesseract.image_to_string(pil_img, config='--psm 6').strip()
    except Exception as e:
        return f"[OCR ERROR: {e}]"
    return ""


# ── Post boundary detection ───────────────────────────────────────────

def find_post_regions(img_array, min_gap=8, min_post_height=80):
    """Find individual post regions within a chunk."""
    h, w = img_array.shape[:2]
    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    row_mean = np.mean(gray, axis=1)
    row_std = np.std(gray, axis=1)
    
    is_divider = (row_mean > 220) & (row_std < 8)
    
    gaps = []
    in_gap = False
    gap_start = 0
    for y in range(h):
        if is_divider[y]:
            if not in_gap:
                gap_start = y
                in_gap = True
        else:
            if in_gap and (y - gap_start) >= min_gap:
                gaps.append((gap_start, y))
            in_gap = False
    if in_gap and (h - gap_start) >= min_gap:
        gaps.append((gap_start, h))
    
    posts = []
    prev_end = 0
    for gs, ge in gaps:
        if gs - prev_end >= min_post_height:
            posts.append((prev_end, gs))
        prev_end = ge
    if h - prev_end >= min_post_height:
        posts.append((prev_end, h))
    
    if not posts:
        posts = [(0, h)]
    
    return posts


# ── Image extraction from a post region ───────────────────────────────

def extract_images(region_array, source_file, post_idx, y_offset, output_dir):
    """Extract embedded photos from a post region."""
    h, w = region_array.shape[:2]
    gray = cv2.cvtColor(region_array, cv2.COLOR_RGB2GRAY)
    
    images = []
    edges = cv2.Canny(gray, 30, 100)
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=3)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if cw < 80 or ch < 80:
            continue
        if cw < w * 0.3:
            continue
        aspect = cw / ch if ch > 0 else 0
        if aspect > 10 or aspect < 0.1:
            continue
        
        roi = region_array[y:y+ch, x:x+cw]
        if roi.size == 0:
            continue
        if np.std(roi) < 20:
            continue
        
        img_id = hashlib.md5(f"{source_file}_{post_idx}_{x}_{y+y_offset}".encode()).hexdigest()[:12]
        save_path = os.path.join(output_dir, f"img_{img_id}.jpg")
        Image.fromarray(roi).save(save_path, "JPEG", quality=92)
        
        images.append({
            "id": img_id,
            "source": {"file": source_file, "post_index": post_idx, "region": [x, y + y_offset, cw, ch]},
            "saved_path": f"images/img_{img_id}.jpg",
            "width": cw, "height": ch,
            "description": "", "category": "", "people_visible": [],
            "is_thumbnail": cw < 200 or ch < 200,
            "needs_crawl": cw < 200 or ch < 200,
        })
    
    return images


# ── Content signal detection ──────────────────────────────────────────

def detect_signals(text):
    """Analyze OCR text for timeline signals."""
    if not text:
        return {"tags": [], "date_hint": "", "post_type": "post",
                "has_see_more": False, "has_more_photos": False,
                "more_photos_hint": "", "has_video": False,
                "link_hints": [], "reactions": "", "comments": "", "shares": ""}
    
    tl = text.lower()
    signals = {
        "has_see_more": "see more" in tl or "see\nmore" in tl,
        "has_more_photos": False,
        "more_photos_hint": "",
        "has_video": any(v in tl for v in ["video", "watch", "▶", "►"]),
        "link_hints": re.findall(r'https?://\S+', text),
        "date_hint": "",
        "reactions": "",
        "comments": "",
        "shares": "",
        "post_type": "post",
        "tags": [],
    }
    
    # More photos
    pm = re.search(r'\+\s*(\d+)\s*(photo|image|pic)', tl)
    if pm:
        signals["has_more_photos"] = True
        signals["more_photos_hint"] = pm.group(0)
    else:
        am = re.search(r'(\d+)\s*(photo|image|pic)', tl)
        if am and int(am.group(1)) > 3:
            signals["has_more_photos"] = True
            signals["more_photos_hint"] = am.group(0)
    
    # Dates
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
    
    # Reactions
    for pat, key in [
        (r'(\d+[,.]?\d*)\s*(like|reaction)', "reactions"),
        (r'(\d+[,.]?\d*)\s*comment', "comments"),
        (r'(\d+[,.]?\d*)\s*share', "shares"),
    ]:
        m = re.search(pat, tl)
        if m:
            signals[key] = m.group(0)
    
    # Tags
    tag_map = {
        "kiln": ["kiln", "anagama", "firing", "burn", "fire"],
        "pottery": ["pottery", "ceramic", "clay", "glaze", "wheel", "pot "],
        "sale": ["sale", "price", "$", "buy", "available", "purchase"],
        "event": ["event", "festival", "market", "show", "exhibition", "tour"],
        "community": ["together", "team", "friends", "volunteer"],
        "wood": ["wood", "firewood", "cord", "split", "ash"],
        "teabowl": ["teabowl", "tea bowl", "chawan"],
    }
    for tag, kws in tag_map.items():
        if any(k in tl for k in kws):
            signals["tags"].append(tag)
    
    # Post type
    if signals["has_video"]:
        signals["post_type"] = "video"
    elif any(w in tl for w in ["checked in", "was at", "was here"]):
        signals["post_type"] = "check-in"
    elif signals["has_more_photos"] or "photo" in tl or "album" in tl:
        signals["post_type"] = "photo"
    elif "shared" in tl:
        signals["post_type"] = "share"
    
    return signals


def parse_date(date_text):
    """Try to parse date hint into ISO date."""
    if not date_text:
        return ""
    clean = date_text.strip().rstrip('.')
    for fmt in ["%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
                "%m/%d/%Y", "%m/%d/%y"]:
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


# ── Main ───────────────────────────────────────────────────────────────

def process_chunk(chunk_info, output_dir, images_dir, slices_dir):
    """Process a single chunk. Returns (posts, images, crawl_targets)."""
    chunk_file = chunk_info["file"]
    chunk_path = os.path.join(CHUNKS_DIR, chunk_file)
    
    img = Image.open(chunk_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img_array = np.array(img)
    del img
    
    h, w = img_array.shape[:2]
    
    # Find post regions within this chunk
    post_regions = find_post_regions(img_array)
    
    posts = []
    all_images = []
    crawl_targets = []
    
    for pidx, (y_start, y_end) in enumerate(post_regions):
        region = img_array[y_start:y_end]
        region_h = y_end - y_start
        
        # Post ID based on source position
        global_y = chunk_info["y_start"] + y_start
        post_id = hashlib.md5(
            f"{chunk_info['source']}_{chunk_info['source_index']}_{global_y}".encode()
        ).hexdigest()[:12]
        
        # Save slice for reference
        slice_name = f"slice_{chunk_file}_{pidx:03d}.jpg"
        slice_path = os.path.join(slices_dir, slice_name)
        Image.fromarray(region).save(slice_path, "JPEG", quality=88)
        
        # OCR
        ocr_text = ocr_region(region)
        
        # Signals
        signals = detect_signals(ocr_text)
        
        # Extract images
        extracted_imgs = extract_images(
            region, chunk_file, pidx, global_y, images_dir
        )
        
        post = {
            "id": post_id,
            "source": {
                "file": chunk_info["source"],
                "chunk": chunk_file,
                "chunk_index": chunk_info["chunk_index"],
                "source_index": chunk_info["source_index"],
                "post_in_chunk": pidx,
                "y_global": [global_y, global_y + region_h],
                "y_in_chunk": [y_start, y_end],
            },
            "slice_file": f"slices/{slice_name}",
            "date_hint": signals["date_hint"],
            "date_parsed": parse_date(signals["date_hint"]),
            "post_type": signals["post_type"],
            "ocr_text": ocr_text,
            "text_cleaned": "",
            "has_images": len(extracted_imgs) > 0,
            "image_ids": [img["id"] for img in extracted_imgs],
            "has_more_content": signals["has_see_more"],
            "has_more_photos": signals["has_more_photos"],
            "more_photos_hint": signals["more_photos_hint"],
            "has_video": signals["has_video"],
            "reactions_text": signals["reactions"],
            "comments_text": signals["comments"],
            "shares_text": signals["shares"],
            "tags": signals["tags"],
            "needs_review": True,
            "notes": "",
        }
        
        posts.append(post)
        all_images.extend(extracted_imgs)
        
        # Crawl targets
        if signals["has_more_photos"]:
            tid = hashlib.md5(f"crawl_photos_{post_id}".encode()).hexdigest()[:12]
            crawl_targets.append({
                "id": tid, "type": "album",
                "url_hint": f"FB post with more photos: {signals['more_photos_hint']}",
                "context": f"Post {post_id} in {chunk_file}",
                "priority": "high", "status": "pending",
            })
        
        if signals["has_see_more"]:
            tid = hashlib.md5(f"crawl_text_{post_id}".encode()).hexdigest()[:12]
            crawl_targets.append({
                "id": tid, "type": "truncated_text",
                "url_hint": "FB post with truncated text (See more)",
                "context": f"Post {post_id} in {chunk_file}",
                "priority": "medium", "status": "pending",
            })
        
        if signals["has_video"]:
            tid = hashlib.md5(f"crawl_video_{post_id}".encode()).hexdigest()[:12]
            crawl_targets.append({
                "id": tid, "type": "video",
                "url_hint": "FB video content",
                "context": f"Post {post_id} in {chunk_file}",
                "priority": "medium", "status": "pending",
            })
        
        for thumb in [i for i in extracted_imgs if i.get("is_thumbnail")]:
            tid = hashlib.md5(f"crawl_img_{thumb['id']}".encode()).hexdigest()[:12]
            crawl_targets.append({
                "id": tid, "type": "full_image",
                "url_hint": f"Full resolution of thumbnail {thumb['id']}",
                "context": f"Post {post_id} in {chunk_file}",
                "priority": "high", "status": "pending",
            })
        
        tag_str = ",".join(signals["tags"]) or "none"
        img_count = len(extracted_imgs)
        has_text = "OCR" if ocr_text and not ocr_text.startswith("[OCR ERROR") else "no-text"
        date_str = signals["date_hint"][:20] if signals["date_hint"] else ""
        print(f"    post {pidx:2d}: y={y_start:5d}-{y_end:5d} | {img_count} img | "
              f"{has_text} | {tag_str}" + (f" | {date_str}" if date_str else ""),
              flush=True)
    
    del img_array
    gc.collect()
    
    return posts, all_images, crawl_targets


def main():
    resume = "--resume" in sys.argv
    
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
    
    # Load progress if resuming
    completed_chunks = set()
    timeline = {
        "schema_version": "1.0",
        "subject": "Ken Shenstone Ceramic Studio & Albion Anagama",
        "extracted": datetime.now().isoformat(),
        "source_files": list({c["source"] for c in chunks}),
        "posts": [],
        "images": [],
        "crawl_targets": [],
        "stats": {},
    }
    
    if resume and os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
        completed_chunks = set(progress.get("completed_chunks", []))
        # Load existing timeline
        tl_path = os.path.join(OUTPUT_DIR, "timeline.json")
        if os.path.exists(tl_path):
            with open(tl_path) as f:
                timeline = json.load(f)
        print(f"Resuming — {len(completed_chunks)} chunks already done", flush=True)
    
    remaining = [c for c in chunks if c["file"] not in completed_chunks]
    
    print(f"Ken Shenstone — Chunk Extraction", flush=True)
    print(f"  Chunks dir:  {CHUNKS_DIR}", flush=True)
    print(f"  Output:      {OUTPUT_DIR}", flush=True)
    print(f"  OCR engine:  {OCR_ENGINE or 'NONE'}", flush=True)
    print(f"  Total chunks: {len(chunks)}", flush=True)
    print(f"  To process:   {len(remaining)}", flush=True)
    print(f"  Resume mode:  {resume}", flush=True)
    print(flush=True)
    
    start_time = time.time()
    
    for ci, chunk in enumerate(remaining):
        chunk_file = chunk["file"]
        elapsed = time.time() - start_time
        
        print(f"\n[{ci+1}/{len(remaining)}] {chunk_file} "
              f"({chunk['height']}px, src #{chunk['source_index']}) "
              f"[{elapsed:.0f}s elapsed]", flush=True)
        
        try:
            posts, images, crawl_targets = process_chunk(
                chunk, OUTPUT_DIR, images_dir, slices_dir
            )
            
            timeline["posts"].extend(posts)
            timeline["images"].extend(images)
            timeline["crawl_targets"].extend(crawl_targets)
            completed_chunks.add(chunk_file)
            
            print(f"  -> {len(posts)} posts, {len(images)} images, "
                  f"{len(crawl_targets)} crawl targets", flush=True)
            
        except Exception as e:
            print(f"  ERROR processing {chunk_file}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Continue to next chunk
        
        # Save progress after EVERY chunk
        timeline["stats"] = {
            "total_posts_extracted": len(timeline["posts"]),
            "total_images_extracted": len(timeline["images"]),
            "total_crawl_targets": len(timeline["crawl_targets"]),
            "ocr_engine": OCR_ENGINE or "none",
            "chunks_processed": len(completed_chunks),
            "chunks_total": len(chunks),
            "elapsed_seconds": round(time.time() - start_time),
        }
        
        with open(os.path.join(OUTPUT_DIR, "timeline.json"), 'w', encoding='utf-8') as f:
            json.dump(timeline, f, indent=2, ensure_ascii=False)
        
        with open(PROGRESS_FILE, 'w') as f:
            json.dump({"completed_chunks": list(completed_chunks)}, f)
    
    # Final summary
    elapsed = time.time() - start_time
    
    # Save crawl targets separately
    if timeline["crawl_targets"]:
        with open(os.path.join(OUTPUT_DIR, "crawl_targets.json"), 'w', encoding='utf-8') as f:
            json.dump(timeline["crawl_targets"], f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*55}", flush=True)
    print(f"EXTRACTION COMPLETE — {elapsed:.0f}s", flush=True)
    print(f"{'='*55}", flush=True)
    print(f"  Posts:          {len(timeline['posts'])}", flush=True)
    print(f"  Images:         {len(timeline['images'])}", flush=True)
    print(f"  Crawl targets:  {len(timeline['crawl_targets'])}", flush=True)
    hp = sum(1 for t in timeline["crawl_targets"] if t.get("priority") == "high")
    print(f"    High:         {hp}", flush=True)
    
    see_more = sum(1 for p in timeline["posts"] if p.get("has_more_content"))
    more_photos = sum(1 for p in timeline["posts"] if p.get("has_more_photos"))
    has_date = sum(1 for p in timeline["posts"] if p.get("date_hint"))
    print(f"  Posts with dates:     {has_date}", flush=True)
    print(f"  Posts truncated:      {see_more}", flush=True)
    print(f"  Posts more photos:    {more_photos}", flush=True)
    print(f"\n  Timeline: {OUTPUT_DIR}/timeline.json", flush=True)


if __name__ == "__main__":
    main()
