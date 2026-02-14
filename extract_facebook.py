#!/usr/bin/env python3
"""
Ken Shenstone Legacy — Facebook Screenshot Extraction Pipeline

Takes giant full-page Facebook screenshots (PNGs), slices them into
individual post regions, extracts embedded images, runs OCR on text
regions, and outputs a structured JSON timeline.

The JSON schema is designed to preserve maximum context:
- Every post gets a timeline position
- Extracted images are saved individually 
- OCR text is captured per-post
- "More content" indicators flag things to crawl later
- Source provenance tracks which screenshot/slice produced each entry

Usage:
    python extract_facebook.py [input_dir] [output_dir]
    
    Defaults:
        input_dir:  C:\\Users\\PC\\Desktop\\Ken Shenstone
        output_dir: C:\\rje\\dev\\ken-shenstone-legacy\\extracted
"""

import json
import os
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install Pillow opencv-python-headless")
    sys.exit(1)

# OCR engine — try EasyOCR first (no external binary needed), then Tesseract
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
        tesseract_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\ProgramData\chocolatey\bin\tesseract.exe",
        ]
        for tp in tesseract_paths:
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


# ── Schema ──────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

def make_empty_timeline():
    """Create the root timeline document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "subject": "Ken Shenstone Ceramic Studio & Albion Anagama",
        "extracted": datetime.now().isoformat(),
        "source_files": [],
        "posts": [],
        "images": [],
        "crawl_targets": [],
        "stats": {
            "total_posts_extracted": 0,
            "total_images_extracted": 0,
            "total_crawl_targets": 0,
            "ocr_available": HAS_OCR,
            "ocr_engine": OCR_ENGINE or "none",
        }
    }


def make_post_entry(post_id, source_file, slice_index, y_start, y_end,
                    ocr_text="", date_hint="", post_type="unknown"):
    """Create a single post entry in the timeline."""
    return {
        "id": post_id,
        "source": {
            "file": source_file,
            "slice_index": slice_index,
            "y_range": [y_start, y_end],
        },
        "date_hint": date_hint,        # extracted date text if found
        "date_parsed": "",              # ISO date if we can parse it
        "post_type": post_type,         # post, photo, video, event, share, check-in, review
        "ocr_text": ocr_text,           # raw OCR output
        "text_cleaned": "",             # manually cleaned / corrected text
        "has_images": False,
        "image_ids": [],                # references to images[] entries
        "has_more_content": False,      # "See more" detected
        "has_more_photos": False,       # "+N photos" or album reference detected
        "more_photos_hint": "",         # e.g. "+12 photos" text
        "reactions_text": "",           # like/reaction count text
        "comments_text": "",            # comment count text
        "shares_text": "",              # share count text
        "tags": [],                     # auto-detected: kiln, firing, pottery, event, sale, etc.
        "people_mentioned": [],         # names detected in text
        "needs_review": True,           # flag for manual review
        "notes": "",                    # manual annotation field
    }


def make_image_entry(image_id, source_file, slice_index, 
                     x, y, w, h, saved_path):
    """Create an image entry."""
    return {
        "id": image_id,
        "source": {
            "file": source_file,
            "slice_index": slice_index,
            "region": [x, y, w, h],
        },
        "saved_path": saved_path,
        "width": w,
        "height": h,
        "description": "",             # manual description
        "category": "",                # teabowl, kiln, firing, portrait, etc.
        "people_visible": [],
        "is_thumbnail": False,          # small image that suggests a larger version exists
        "full_resolution_url": "",      # if we can extract the FB image URL
        "needs_crawl": False,           # flag: this is a thumbnail, go get the full image
    }


def make_crawl_target(target_id, url_hint, context, priority="medium"):
    """Create a crawl target — something to go get later."""
    return {
        "id": target_id,
        "url_hint": url_hint,           # URL or description of where to find it
        "context": context,             # what post/image this relates to
        "type": "",                     # album, full_image, video, external_link
        "priority": priority,           # high, medium, low
        "status": "pending",            # pending, crawled, failed, skipped
        "crawled_date": "",
        "result_path": "",              # where the crawled content was saved
        "notes": "",
    }


# ── Image Processing ───────────────────────────────────────────────────

def load_screenshot(filepath):
    """Load a large PNG and convert to numpy array for OpenCV."""
    img = Image.open(filepath)
    if img.mode == 'RGBA':
        # Convert RGBA to RGB (white background)
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    return np.array(img)


def find_post_boundaries(img_array, min_gap=15, min_post_height=100):
    """
    Find horizontal dividers between Facebook posts.
    
    Facebook uses light gray horizontal lines/gaps between posts.
    We detect rows that are nearly uniform light gray/white,
    then use those as boundaries.
    """
    h, w = img_array.shape[:2]
    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    # Calculate row-wise standard deviation (uniform rows = dividers)
    row_std = np.std(gray, axis=1)
    row_mean = np.mean(gray, axis=1)
    
    # Facebook dividers are light (>220) and uniform (std < 5)
    is_divider = (row_mean > 215) & (row_std < 8)
    
    # Find contiguous divider regions
    boundaries = []
    in_gap = False
    gap_start = 0
    
    for y in range(h):
        if is_divider[y]:
            if not in_gap:
                gap_start = y
                in_gap = True
        else:
            if in_gap and (y - gap_start) >= min_gap:
                boundaries.append((gap_start, y))
            in_gap = False
    
    # Convert boundaries to post regions
    posts = []
    prev_end = 0
    for gap_start, gap_end in boundaries:
        if gap_start - prev_end >= min_post_height:
            posts.append((prev_end, gap_start))
        prev_end = gap_end
    
    # Don't forget the last section
    if h - prev_end >= min_post_height:
        posts.append((prev_end, h))
    
    # If no boundaries found, treat the whole image as one section
    if not posts:
        posts = [(0, h)]
    
    return posts


def extract_images_from_region(region_array, min_size=80, source_file="",
                               slice_index=0, y_offset=0, output_dir=""):
    """
    Find embedded images within a post region.
    
    Facebook images are typically:
    - Larger rectangular regions with non-text content
    - Higher color variance than text areas
    - Often have specific aspect ratios
    """
    h, w = region_array.shape[:2]
    gray = cv2.cvtColor(region_array, cv2.COLOR_RGB2GRAY)
    
    images_found = []
    
    # Strategy: Find large rectangular regions with high color variance
    # Use edge detection + contour finding
    edges = cv2.Canny(gray, 30, 100)
    
    # Dilate to connect nearby edges
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=3)
    
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        
        # Filter: must be reasonably large
        if cw < min_size or ch < min_size:
            continue
        
        # Filter: must occupy a significant portion of width (FB images are wide)
        if cw < w * 0.3:
            continue
            
        # Filter: aspect ratio sanity (not too thin)
        aspect = cw / ch if ch > 0 else 0
        if aspect > 10 or aspect < 0.1:
            continue
        
        # Check color variance in this region (images have higher variance than text bg)
        roi = region_array[y:y+ch, x:x+cw]
        if roi.size == 0:
            continue
            
        color_std = np.std(roi)
        if color_std < 20:  # Too uniform, probably background
            continue
        
        # This looks like an image region
        img_id = hashlib.md5(f"{source_file}_{slice_index}_{x}_{y+y_offset}".encode()).hexdigest()[:12]
        
        # Save the extracted image
        if output_dir:
            img_pil = Image.fromarray(roi)
            save_path = os.path.join(output_dir, f"img_{img_id}.jpg")
            img_pil.save(save_path, "JPEG", quality=92)
            
            images_found.append(make_image_entry(
                image_id=img_id,
                source_file=source_file,
                slice_index=slice_index,
                x=x, y=y + y_offset, w=cw, h=ch,
                saved_path=os.path.relpath(save_path, output_dir)
            ))
    
    return images_found


def parse_date_hint(date_text):
    """Try to parse a date hint string into an ISO date."""
    if not date_text:
        return ""
    
    # Full month name with year
    formats = [
        "%B %d, %Y",       # January 15, 2020
        "%B %d %Y",        # January 15 2020
        "%b %d, %Y",       # Jan 15, 2020
        "%b %d %Y",        # Jan 15 2020
        "%m/%d/%Y",         # 01/15/2020
        "%m/%d/%y",         # 01/15/20
    ]
    
    clean = date_text.strip().rstrip('.')
    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return ""


def detect_content_signals(text):
    """
    Analyze OCR text for signals that indicate more content to crawl.
    
    Returns dict of detected signals.
    """
    signals = {
        "has_see_more": False,
        "has_more_photos": False,
        "more_photos_hint": "",
        "has_video": False,
        "has_link": False,
        "link_hints": [],
        "date_hint": "",
        "reactions_text": "",
        "comments_text": "",
        "shares_text": "",
        "post_type": "post",
        "tags": [],
        "people_mentioned": [],
    }
    
    text_lower = text.lower()
    
    # See More
    if "see more" in text_lower or "see\nmore" in text_lower:
        signals["has_see_more"] = True
    
    # More photos
    photo_match = re.search(r'\+\s*(\d+)\s*(photo|image|pic)', text_lower)
    if photo_match:
        signals["has_more_photos"] = True
        signals["more_photos_hint"] = photo_match.group(0)
    
    album_match = re.search(r'(\d+)\s*(photo|image|pic)', text_lower)
    if album_match:
        count = int(album_match.group(1))
        if count > 3:
            signals["has_more_photos"] = True
            signals["more_photos_hint"] = album_match.group(0)
    
    # Video indicators
    if any(v in text_lower for v in ["video", "watch"]):
        signals["has_video"] = True
        signals["post_type"] = "video"
    
    # Links
    url_matches = re.findall(r'https?://\S+', text)
    if url_matches:
        signals["has_link"] = True
        signals["link_hints"] = url_matches
    
    # Date patterns (Facebook date formats)
    date_patterns = [
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}',
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s*\d{4}',
        r'\d{1,2}/\d{1,2}/\d{2,4}',
        r'(\d+)\s+(hour|day|week|month|year)s?\s+ago',
        r'Yesterday',
        r'Just now',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            signals["date_hint"] = match.group(0)
            break
    
    # Reactions/comments/shares
    react_match = re.search(r'(\d+[,.]?\d*)\s*(like|reaction|comment|share)', text_lower)
    if react_match:
        count = react_match.group(0)
        if "like" in count or "reaction" in count:
            signals["reactions_text"] = count
        elif "comment" in count:
            signals["comments_text"] = count
        elif "share" in count:
            signals["shares_text"] = count
    
    # Auto-tags based on content
    tag_keywords = {
        "kiln": ["kiln", "anagama", "fire", "firing", "burn", "heat"],
        "pottery": ["pottery", "pot", "pots", "ceramic", "clay", "glaze", "wheel"],
        "sale": ["sale", "price", "$", "buy", "available", "purchase"],
        "event": ["event", "festival", "market", "show", "exhibition", "tour"],
        "apprenticeship": ["apprentice", "opportunity", "learn", "residency", "resident"],
        "community": ["together", "team", "friends", "volunteer", "collaborative"],
        "wood": ["wood", "firewood", "cord", "split", "ash"],
        "teabowl": ["teabowl", "tea bowl", "chawan"],
        "demo": ["demonstration", "demo", "throwing", "wheel"],
    }
    for tag, keywords in tag_keywords.items():
        if any(kw in text_lower for kw in keywords):
            signals["tags"].append(tag)
    
    # Post type detection
    if any(w in text_lower for w in ["check", "checked in", "was at", "was here"]):
        signals["post_type"] = "check-in"
    elif any(w in text_lower for w in ["shared", "share"]):
        signals["post_type"] = "share"
    elif signals["has_more_photos"] or "photo" in text_lower:
        signals["post_type"] = "photo"
    
    return signals


def ocr_region(region_array):
    """Run OCR on a region. Returns text or empty string if unavailable."""
    global _easyocr_reader
    
    if not HAS_OCR:
        return ""
    
    try:
        if OCR_ENGINE == "easyocr":
            if _easyocr_reader is None:
                import easyocr
                _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            results = _easyocr_reader.readtext(region_array, detail=0, paragraph=True)
            return "\n".join(results).strip()
        elif OCR_ENGINE == "tesseract":
            pil_img = Image.fromarray(region_array)
            text = pytesseract.image_to_string(pil_img, config='--psm 6')
            return text.strip()
    except Exception as e:
        return f"[OCR ERROR: {e}]"
    return ""


# ── Main Pipeline ──────────────────────────────────────────────────────

def process_screenshot(filepath, output_dir, timeline):
    """Process a single Facebook screenshot PNG."""
    filename = os.path.basename(filepath)
    print(f"\n{'='*60}")
    print(f"Processing: {filename}")
    print(f"  Size: {os.path.getsize(filepath) / 1024 / 1024:.1f} MB")
    
    # Load image
    img_array = load_screenshot(filepath)
    h, w = img_array.shape[:2]
    print(f"  Dimensions: {w}x{h}")
    
    # Record source file
    timeline["source_files"].append({
        "filename": filename,
        "dimensions": [w, h],
        "size_mb": round(os.path.getsize(filepath) / 1024 / 1024, 1),
    })
    
    # Find post boundaries
    post_regions = find_post_boundaries(img_array)
    print(f"  Post regions found: {len(post_regions)}")
    
    # Process each post region
    images_dir = os.path.join(output_dir, "images")
    slices_dir = os.path.join(output_dir, "slices")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(slices_dir, exist_ok=True)
    
    for idx, (y_start, y_end) in enumerate(post_regions):
        region = img_array[y_start:y_end, :, :]
        region_h = y_end - y_start
        
        # Generate post ID
        post_id = hashlib.md5(f"{filename}_{idx}_{y_start}".encode()).hexdigest()[:12]
        
        # Save the slice for reference
        slice_path = os.path.join(slices_dir, f"slice_{filename}_{idx:03d}.jpg")
        Image.fromarray(region).save(slice_path, "JPEG", quality=90)
        
        # OCR the region
        ocr_text = ocr_region(region)
        
        # Detect content signals
        signals = detect_content_signals(ocr_text)
        
        # Extract embedded images
        extracted_images = extract_images_from_region(
            region, source_file=filename, slice_index=idx,
            y_offset=y_start, output_dir=images_dir
        )
        
        # Build post entry
        post = make_post_entry(
            post_id=post_id,
            source_file=filename,
            slice_index=idx,
            y_start=y_start,
            y_end=y_end,
            ocr_text=ocr_text,
            date_hint=signals["date_hint"],
            post_type=signals["post_type"],
        )
        
        post["has_images"] = len(extracted_images) > 0
        post["image_ids"] = [img["id"] for img in extracted_images]
        post["has_more_content"] = signals["has_see_more"]
        post["has_more_photos"] = signals["has_more_photos"]
        post["more_photos_hint"] = signals["more_photos_hint"]
        post["reactions_text"] = signals["reactions_text"]
        post["comments_text"] = signals["comments_text"]
        post["shares_text"] = signals["shares_text"]
        post["tags"] = signals["tags"]
        post["date_parsed"] = parse_date_hint(signals["date_hint"])
        post["people_mentioned"] = signals["people_mentioned"]
        
        timeline["posts"].append(post)
        timeline["images"].extend(extracted_images)
        
        # Create crawl targets for things we need to go get
        if signals["has_more_photos"]:
            target_id = hashlib.md5(f"crawl_photos_{post_id}".encode()).hexdigest()[:12]
            timeline["crawl_targets"].append(make_crawl_target(
                target_id=target_id,
                url_hint=f"Facebook post with more photos - {signals['more_photos_hint']}",
                context=f"Post {post_id} (slice {idx} of {filename})",
                priority="high",
            ))
        
        if signals["has_see_more"]:
            target_id = hashlib.md5(f"crawl_text_{post_id}".encode()).hexdigest()[:12]
            timeline["crawl_targets"].append(make_crawl_target(
                target_id=target_id,
                url_hint="Facebook post with truncated text ('See more')",
                context=f"Post {post_id} (slice {idx} of {filename})",
                priority="medium",
            ))
        
        if signals["has_video"]:
            target_id = hashlib.md5(f"crawl_video_{post_id}".encode()).hexdigest()[:12]
            timeline["crawl_targets"].append(make_crawl_target(
                target_id=target_id,
                url_hint="Facebook video content",
                context=f"Post {post_id} (slice {idx} of {filename})",
                priority="medium",
            ))
        
        for url in signals.get("link_hints", []):
            target_id = hashlib.md5(f"crawl_link_{post_id}_{url}".encode()).hexdigest()[:12]
            timeline["crawl_targets"].append(make_crawl_target(
                target_id=target_id,
                url_hint=url,
                context=f"Post {post_id} (slice {idx} of {filename})",
                priority="low",
            ))
        
        # Mark images that look like thumbnails
        for img_entry in extracted_images:
            if img_entry["width"] < 200 or img_entry["height"] < 200:
                img_entry["is_thumbnail"] = True
                img_entry["needs_crawl"] = True
                target_id = hashlib.md5(f"crawl_img_{img_entry['id']}".encode()).hexdigest()[:12]
                timeline["crawl_targets"].append(make_crawl_target(
                    target_id=target_id,
                    url_hint=f"Full resolution of thumbnail image {img_entry['id']}",
                    context=f"Post {post_id}, image in slice {idx}",
                    priority="high",
                ))
        
        print(f"  Slice {idx:3d}: y={y_start:5d}-{y_end:5d} ({region_h:4d}px) "
              f"| {len(extracted_images)} img | "
              f"{'OCR' if ocr_text else 'no-text'} | "
              f"tags: {','.join(signals['tags']) or 'none'}")
    
    return len(post_regions)


def main():
    input_dir = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\PC\Desktop\Ken Shenstone"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else r"C:\rje\dev\ken-shenstone-legacy\extracted"
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("Ken Shenstone Legacy — Facebook Extraction Pipeline")
    print(f"  Input:  {input_dir}")
    print(f"  Output: {output_dir}")
    print(f"  OCR:    {OCR_ENGINE + ' available' if HAS_OCR else 'NOT AVAILABLE — text extraction will be skipped'}")
    print()
    
    # Find all PNGs
    png_files = sorted([
        os.path.join(input_dir, f) for f in os.listdir(input_dir)
        if f.lower().endswith('.png') and 'screencapture' in f.lower()
    ])
    
    if not png_files:
        print(f"No Facebook screenshot PNGs found in {input_dir}")
        sys.exit(1)
    
    print(f"Found {len(png_files)} screenshot(s) to process")
    
    # Initialize timeline
    timeline = make_empty_timeline()
    
    # Process each screenshot  
    total_posts = 0
    for filepath in png_files:
        count = process_screenshot(filepath, output_dir, timeline)
        total_posts += count
    
    # Update stats
    timeline["stats"]["total_posts_extracted"] = len(timeline["posts"])
    timeline["stats"]["total_images_extracted"] = len(timeline["images"])
    timeline["stats"]["total_crawl_targets"] = len(timeline["crawl_targets"])
    
    # Save timeline JSON
    timeline_path = os.path.join(output_dir, "timeline.json")
    with open(timeline_path, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, indent=2, ensure_ascii=False)
    
    # Save a crawl targets summary for easy review
    if timeline["crawl_targets"]:
        crawl_path = os.path.join(output_dir, "crawl_targets.json")
        with open(crawl_path, 'w', encoding='utf-8') as f:
            json.dump(timeline["crawl_targets"], f, indent=2, ensure_ascii=False)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Screenshots processed: {len(png_files)}")
    print(f"  Posts extracted:       {len(timeline['posts'])}")
    print(f"  Images extracted:      {len(timeline['images'])}")
    print(f"  Crawl targets:         {len(timeline['crawl_targets'])}")
    print(f"    High priority:       {sum(1 for t in timeline['crawl_targets'] if t['priority'] == 'high')}")
    print(f"    Medium priority:     {sum(1 for t in timeline['crawl_targets'] if t['priority'] == 'medium')}")
    print(f"    Low priority:        {sum(1 for t in timeline['crawl_targets'] if t['priority'] == 'low')}")
    print(f"  OCR engine:            {OCR_ENGINE if HAS_OCR else 'none'}")
    print(f"\n  Timeline saved:        {timeline_path}")
    if timeline["crawl_targets"]:
        print(f"  Crawl targets saved:   {crawl_path}")
    print(f"  Image slices:          {output_dir}/slices/")
    print(f"  Extracted images:      {output_dir}/images/")
    
    # Posts needing attention
    see_more = sum(1 for p in timeline["posts"] if p["has_more_content"])
    more_photos = sum(1 for p in timeline["posts"] if p["has_more_photos"])
    if see_more or more_photos:
        print(f"\n  [!] Posts with truncated text ('See more'): {see_more}")
        print(f"  [!] Posts with more photos to crawl:       {more_photos}")


if __name__ == "__main__":
    main()
