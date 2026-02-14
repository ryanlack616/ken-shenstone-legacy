"""
Rename and organize Ken Shenstone Facebook images with meaningful names and dates.

Reads extracted/timeline.json, determines the best date for each post,
generates descriptive filenames, and copies images to organized_images/.
Also creates a manifest.json mapping old names → new names.
"""
import json, re, os, shutil
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(r"C:\rje\dev\ken-shenstone-legacy")
TIMELINE = BASE / "extracted" / "timeline.json"
IMG_DIR = BASE / "extracted" / "images"
OUT_DIR = BASE / "organized_images"

# ── Load data ──────────────────────────────────────────────────────────────
with open(TIMELINE, "r", encoding="utf-8") as f:
    data = json.load(f)
posts = data["posts"]

# ── Establish global chronological order ───────────────────────────────────
# The 5 source files are in this order (newest → oldest):
#   fb5 (.png no suffix)  → 2020-2016
#   fb1 (-2.png)          → 2016-2015
#   fb2 (-3.png)          → 2015
#   fb3 (-4.png)          → 2014-2012
#   fb4 (-5.png)          → 2012-2009
# Within each source, posts scroll top→bottom = newest→oldest.
# We assign a global_order based on this.

SRC_ORDER = {
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48.png": 0,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-2.png": 1,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-3.png": 2,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-4.png": 3,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-5.png": 4,
}

# Sort posts into true chronological order (newest first)
for i, p in enumerate(posts):
    p["_orig_idx"] = i

posts_chrono = sorted(posts, key=lambda p: (SRC_ORDER.get(p["source_file"], 99), p.get("y_global", 0)))

for i, p in enumerate(posts_chrono):
    p["_chrono_idx"] = i  # 0 = newest, N = oldest

# ── Date extraction ────────────────────────────────────────────────────────

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def parse_date_from_ocr(ocr_text):
    """Try to extract a date from OCR text. Returns (date_str, precision)."""
    if not ocr_text:
        return None, None

    # Try "Month Day, Year" or "Month Day Year" patterns
    m = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+'
        r'(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})',
        ocr_text, re.IGNORECASE
    )
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}", "day"

    # Try "Mon, Mon Day Year" (e.g. "Fri, Nov 9 2012")
    m = re.search(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[;,]\s*'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
        r'(\d{1,2}),?\s*(\d{4})',
        ocr_text, re.IGNORECASE
    )
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}", "day"

    # Try "Sat, Dec 10, 2016" variant  
    m = re.search(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[;,]\s*'
        r'(Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov)\s+'
        r'(\d{1,2}),?\s*(\d{4})',
        ocr_text, re.IGNORECASE
    )
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}", "day"

    # Try "Month Year" (e.g. "October 2015", "May 2019")
    m = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})',
        ocr_text, re.IGNORECASE
    )
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        year = int(m.group(2))
        if 2005 <= year <= 2025:
            return f"{year:04d}-{month:02d}", "month"

    # Try "Mon, Month Year" (e.g. "Mon; May 2019")
    m = re.search(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[;,]\s*'
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
        ocr_text, re.IGNORECASE
    )
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        year = int(m.group(2))
        return f"{year:04d}-{month:02d}", "month"

    # Try "December 10th and 11th, 2016" style
    m = re.search(
        r'(Decemb[ec]r|January|February|March|April|May|June|July|August|September|October|November)\s+'
        r'(\d{1,2})(?:st|nd|rd|th)?\s+(?:and|&)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*(\d{4})',
        ocr_text, re.IGNORECASE
    )
    if m:
        month_str = m.group(1).lower()
        # Fix OCR typos
        if month_str.startswith("decemb"):
            month = 12
        else:
            month = MONTH_MAP.get(month_str, 0)
        if month:
            day = int(m.group(2))
            year = int(m.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}", "day"

    return None, None


# Build image metadata index from data['images']
img_meta_by_id = {}
if 'images' in data:
    for im in data['images']:
        img_meta_by_id[im['id']] = im


def extract_description(ocr_text, post_type="", image_meta=None):
    """Generate a short descriptive slug from OCR text and image metadata."""
    if not ocr_text:
        ocr_text = ""

    ocr_lower = ocr_text.lower().strip()

    # Check for known event types (most specific first)
    if "holiday" in ocr_lower and ("sale" in ocr_lower or "pottery" in ocr_lower):
        return "holiday-pottery-sale"
    if ("pottery sale" in ocr_lower or "pottery sal" in ocr_lower or
        "pottsry sal" in ocr_lower or "pottery sals" in ocr_lower):
        return "pottery-sale"
    if "clearance sale" in ocr_lower:
        return "clearance-sale"
    if "spring cleaning" in ocr_lower:
        return "spring-sale"
    if "mother" in ocr_lower and ("sale" in ocr_lower or "day" in ocr_lower or "cale" in ocr_lower):
        return "mothers-day-sale"
    if "father" in ocr_lower and ("sale" in ocr_lower or "day" in ocr_lower):
        return "fathers-day-sale"
    if "gofundme" in ocr_lower or "gofund" in ocr_lower:
        return "gofundme"
    if "resident" in ocr_lower and ("position" in ocr_lower or "postion" in ocr_lower):
        return "resident-artist-ad"
    if ("space avail" in ocr_lower or "pace avail" in ocr_lower) and "firing" in ocr_lower:
        return "firing-space-available"
    if "space avail" in ocr_lower or "pace avail" in ocr_lower:
        return "studio-space-available"
    if "firing dat" in ocr_lower:
        return "firing-schedule"
    if "firing" in ocr_lower and "anagama" in ocr_lower:
        return "anagama-firing"
    if "firing" in ocr_lower:
        return "kiln-firing"
    if "nobo" in ocr_lower:
        return "noborigama"
    if "unload" in ocr_lower:
        return "kiln-unloading"
    if "eastern market" in ocr_lower:
        return "eastern-market"
    if "sounds & sights" in ocr_lower or "sounds and sights" in ocr_lower:
        return "festival"
    if "artist profile" in ocr_lower:
        return "artist-profile"
    if re.search(r'added\s+\d+\s+new\s+photo', ocr_lower):
        return "ceramics"
    if "added new photo" in ocr_lower:
        return "ceramics"
    if re.search(r'followers|following|recommend', ocr_lower):
        return "page-profile"
    if "kshenstone.com" in ocr_lower:
        return "website"
    if re.search(r'\bsale\b', ocr_lower) and "off" in ocr_lower:
        return "pottery-sale"
    if re.search(r'\bsale\b', ocr_lower):
        return "pottery-sale"

    # Skip Facebook UI junk text
    if re.match(r'^[\+\d\s]*$', ocr_lower):    # "+3", numbers only
        return "ceramics"
    if re.match(r'^(comments?\s*shares?|\d+\s*views?|like\s|comment\s*share)', ocr_lower):
        return "ceramics"
    # Short meaningless OCR
    if len(ocr_lower) < 10:
        return "ceramics"

    # Fallback
    return "ceramics"


# ── Phase 1: Assign dates to all posts ─────────────────────────────────────

for p in posts_chrono:
    p["_date"] = None
    p["_date_precision"] = None
    p["_date_source"] = None

    # Priority 1: date_parsed
    if p.get("date_parsed"):
        p["_date"] = p["date_parsed"]
        p["_date_precision"] = "day"
        p["_date_source"] = "parsed"
        continue

    # Priority 2: Parse from OCR
    ocr_date, precision = parse_date_from_ocr(p.get("ocr_text", ""))
    if ocr_date:
        p["_date"] = ocr_date
        p["_date_precision"] = precision
        p["_date_source"] = "ocr"

# ── Phase 2: Interpolate missing dates ─────────────────────────────────────
# Posts are in chrono order (newest first). Find nearest known dates
# above and below, then interpolate.

def date_to_ordinal(ds):
    """Convert YYYY-MM-DD or YYYY-MM to ordinal number."""
    parts = ds.split("-")
    if len(parts) == 3:
        return datetime(int(parts[0]), int(parts[1]), int(parts[2])).toordinal()
    elif len(parts) == 2:
        return datetime(int(parts[0]), int(parts[1]), 15).toordinal()
    return None

def ordinal_to_date(o):
    """Convert ordinal → YYYY-MM-DD string."""
    d = datetime.fromordinal(int(o))
    return d.strftime("%Y-%m-%d")

# Build list of (chrono_idx, ordinal) for known dates
known = []
for p in posts_chrono:
    if p["_date"]:
        o = date_to_ordinal(p["_date"])
        if o:
            known.append((p["_chrono_idx"], o))

# Sort by chrono_idx (should already be)
known.sort()

# For each undated post, find nearest known dates and interpolate
for p in posts_chrono:
    if p["_date"]:
        continue

    idx = p["_chrono_idx"]

    # Find nearest before (smaller idx = newer) and after (larger idx = older)
    before = None  # newer known date
    after = None   # older known date

    for ki, ko in known:
        if ki < idx:
            before = (ki, ko)  # most recent known before this
        elif ki > idx:
            after = (ki, ko)
            break

    if before and after:
        # Linear interpolation
        bi, bo = before
        ai, ao = after
        frac = (idx - bi) / (ai - bi)
        interp_ord = bo + frac * (ao - bo)
        p["_date"] = ordinal_to_date(interp_ord)
        p["_date_precision"] = "estimated"
        p["_date_source"] = "interpolated"
    elif before:
        # Only newer known — estimate older by offset
        bi, bo = before
        gap = idx - bi
        p["_date"] = ordinal_to_date(bo - gap * 14)  # ~2 weeks per post
        p["_date_precision"] = "estimated"
        p["_date_source"] = "extrapolated"
    elif after:
        # Only older known — estimate newer
        ai, ao = after
        gap = ai - idx
        p["_date"] = ordinal_to_date(ao + gap * 14)
        p["_date_precision"] = "estimated"
        p["_date_source"] = "extrapolated"
    else:
        p["_date"] = "unknown"
        p["_date_precision"] = "none"
        p["_date_source"] = "none"

# ── Phase 3: Build image rename map ───────────────────────────────────────

OUT_DIR.mkdir(exist_ok=True)

# Track used filenames to avoid collisions
used_names = set()
manifest = []
log_lines = []

# Index posts by chronological order for multi-image sequencing
post_by_id = {p["id"]: p for p in posts_chrono}

# Process all image-bearing posts in chronological order
for p in posts_chrono:
    if not p.get("has_images") or not p.get("image_ids"):
        continue

    date_str = p["_date"] or "unknown"
    # Clean date for filename (remove any time part)
    date_for_name = date_str[:10]  # YYYY-MM-DD or YYYY-MM

    desc = extract_description(p.get("ocr_text", ""), p.get("post_type", ""),
                                img_meta_by_id.get(p["image_ids"][0]) if p["image_ids"] else None)

    for img_idx, img_id in enumerate(p["image_ids"]):
        img_file = f"img_{img_id}.jpg"
        src_path = IMG_DIR / img_file

        if not src_path.exists():
            log_lines.append(f"MISSING: {img_file}")
            continue

        # Build new name
        if len(p["image_ids"]) > 1:
            suffix = f"_{img_idx + 1:02d}"
        else:
            suffix = ""

        new_name = f"{date_for_name}_{desc}{suffix}.jpg"

        # Handle collisions
        base_name = new_name
        counter = 2
        while new_name in used_names:
            stem = base_name.rsplit(".jpg", 1)[0]
            new_name = f"{stem}_{counter}.jpg"
            counter += 1

        used_names.add(new_name)

        # Copy file
        dst_path = OUT_DIR / new_name
        shutil.copy2(src_path, dst_path)

        manifest.append({
            "original": img_file,
            "renamed": new_name,
            "post_id": p["id"][:8],
            "date": date_str,
            "date_precision": p["_date_precision"],
            "date_source": p["_date_source"],
            "description": desc,
            "chunk": p.get("chunk_file", ""),
            "ocr_preview": (p.get("ocr_text", "") or "")[:100],
        })

# ── Write manifest ─────────────────────────────────────────────────────────

manifest_path = OUT_DIR / "manifest.json"
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

# ── Write human-readable report ────────────────────────────────────────────

report_path = BASE / "_rename_report.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(f"Image Rename Report\n")
    f.write(f"{'='*80}\n")
    f.write(f"Total images processed: {len(manifest)}\n")

    # Count by date source
    by_source = {}
    for m in manifest:
        src = m["date_source"]
        by_source[src] = by_source.get(src, 0) + 1
    f.write(f"\nDate sources:\n")
    for src, count in sorted(by_source.items()):
        f.write(f"  {src}: {count}\n")

    # Count by description
    by_desc = {}
    for m in manifest:
        d = m["description"]
        by_desc[d] = by_desc.get(d, 0) + 1
    f.write(f"\nDescriptions:\n")
    for d, count in sorted(by_desc.items(), key=lambda x: -x[1]):
        f.write(f"  {d}: {count}\n")

    f.write(f"\n{'='*80}\n")
    f.write(f"{'Original':<30} {'New Name':<55} {'Date Src':<14}\n")
    f.write(f"{'-'*30} {'-'*55} {'-'*14}\n")

    for m in manifest:
        f.write(f"{m['original']:<30} {m['renamed']:<55} {m['date_source']:<14}\n")

    if log_lines:
        f.write(f"\n{'='*80}\n")
        f.write("WARNINGS:\n")
        for line in log_lines:
            f.write(f"  {line}\n")

print(f"Done! {len(manifest)} images copied to {OUT_DIR}")
print(f"Manifest: {manifest_path}")
print(f"Report: {report_path}")
if log_lines:
    print(f"Warnings: {len(log_lines)}")
