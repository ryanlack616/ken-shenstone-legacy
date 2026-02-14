"""
Fix image dates by ordered alignment with real Facebook dates.

Rather than trying to classify posts, we directly align images (which are in scroll
order = newest first) with the 122 FB dates (also newest first), using ordering
constraints to ensure monotonic date assignment.

Each image is assigned the closest FB date that is <= the previous image's date.
Images from the same post share the same date.
"""
import json
import os
import shutil
import re
from datetime import datetime
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))

# ── Restore from backup ───────────────────────────────────────────────────
backup = BASE / "extracted" / "timeline_backup.json"
tl_path = BASE / "extracted" / "timeline.json"

if backup.exists():
    shutil.copy2(backup, tl_path)
    print("Restored timeline.json from backup")

with open(tl_path, "r", encoding="utf-8") as f:
    data = json.load(f)

posts = data["posts"]

# ── Facebook dates (newest first) ─────────────────────────────────────────
FB_RAW = [
    "February 26, 2020", "May 6, 2019", "May 2, 2019", "May 1, 2019",
    "September 9, 2018", "September 8, 2018", "June 19, 2018", "May 12, 2018",
    "May 7, 2018", "May 2, 2018", "January 23, 2018", "December 8, 2017",
    "June 27, 2017", "December 15, 2016", "December 8, 2016", "December 7, 2016",
    "October 11, 2016", "August 6, 2016", "July 17, 2016", "July 16, 2016",
    "July 15, 2016", "July 14, 2016", "July 12, 2016", "July 11, 2016",
    "July 4, 2016", "July 3, 2016", "July 2, 2016", "July 1, 2016",
    "June 29, 2016", "June 25, 2016", "June 19, 2016", "June 18, 2016",
    "June 17, 2016", "June 7, 2016", "December 19, 2015", "December 12, 2015",
    "November 27, 2015", "November 20, 2015", "November 1, 2015", "October 31, 2015",
    "October 30, 2015", "October 29, 2015", "October 26, 2015", "October 24, 2015",
    "October 20, 2015", "October 18, 2015", "October 17, 2015", "September 20, 2015",
    "September 19, 2015", "September 18, 2015", "September 16, 2015", "September 15, 2015",
    "September 10, 2015", "September 2, 2015", "July 27, 2015", "May 18, 2015",
    "May 16, 2015", "May 14, 2015", "May 3, 2015", "May 2, 2015",
    "April 23, 2015", "March 22, 2015", "March 21, 2015", "March 9, 2015",
    "December 5, 2014", "December 2, 2014", "November 30, 2014", "November 29, 2014",
    "November 27, 2014", "November 21, 2014", "September 19, 2014", "August 30, 2014",
    "October 23, 2014", "August 27, 2014", "August 26, 2014", "August 5, 2014",
    "August 4, 2014", "August 1, 2014", "July 25, 2014", "June 21, 2014",
    "June 17, 2014", "May 20, 2014", "May 14, 2014", "May 10, 2014",
    "May 1, 2014", "December 5, 2013", "December 1, 2013", "November 30, 2013",
    "November 29, 2013", "November 7, 2013", "October 31, 2013", "October 21, 2013",
    "September 29, 2013", "July 25, 2013", "May 6, 2013", "May 4, 2013",
    "March 19, 2013", "February 4, 2013", "January 7, 2013", "December 6, 2012",
    "November 25, 2012", "November 17, 2012", "November 12, 2012", "November 11, 2012",
    "November 8, 2012", "November 7, 2012", "November 1, 2012", "October 22, 2012",
    "September 13, 2012", "September 3, 2012", "July 16, 2012", "March 2, 2012",
    "November 8, 2011", "August 11, 2011", "June 24, 2011", "October 10, 2010",
    "September 26, 2010", "November 11, 2009", "July 17, 2009", "May 15, 2009",
    "March 30, 2009", "March 28, 2009",
]

fb_dates = sorted([datetime.strptime(d, "%B %d, %Y") for d in FB_RAW], reverse=True)
fb_iso = [d.strftime("%Y-%m-%d") for d in fb_dates]

# ── Sort posts by scroll position ─────────────────────────────────────────
SRC_ORDER = {
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48.png": 0,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-2.png": 1,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-3.png": 2,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-4.png": 3,
    "screencapture-facebook-p-Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130-2026-02-12-22_42_48-5.png": 4,
}
posts_sorted = sorted(posts, key=lambda p: (SRC_ORDER.get(p["source_file"], 99), p.get("y_global", 0)))

# ── Collect image-bearing posts in scroll order ───────────────────────────
image_posts = []
seen_post_ids = set()
for p in posts_sorted:
    if p.get("image_ids") and p["id"] not in seen_post_ids:
        image_posts.append(p)
        seen_post_ids.add(p["id"])

print(f"Image-bearing posts in scroll order: {len(image_posts)}")
print(f"Total images: {sum(len(p.get('image_ids', [])) for p in image_posts)}")
print(f"FB dates available: {len(fb_iso)}")

# ── Greedy ordered alignment ──────────────────────────────────────────────
# Walk through image_posts (newest→oldest), assign each to the nearest FB date
# that maintains monotonic ordering (each date <= previous assigned date).

def find_best_fb_date(post, fb_dates_remaining, fb_iso_remaining):
    """Find the best matching FB date for this post from remaining dates."""
    # Check if post has OCR with a parseable date
    ocr = (post.get("ocr_text", "") or "").strip()
    
    MONTH_MAP = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    
    m = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+'
        r'(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})',
        ocr, re.IGNORECASE
    )
    if m:
        try:
            month = MONTH_MAP[m.group(1).lower()]
            day = int(m.group(2))
            year = int(m.group(3))
            if 2005 <= year <= 2025:
                target = datetime(year, month, day)
                target_iso = target.strftime("%Y-%m-%d")
                # Find exact match in remaining dates
                if target_iso in fb_iso_remaining:
                    return fb_iso_remaining.index(target_iso)
                # Find closest remaining date
                best_idx = min(range(len(fb_dates_remaining)),
                             key=lambda i: abs((fb_dates_remaining[i] - target).days))
                return best_idx
        except (ValueError, KeyError):
            pass
    
    # No date clue — take the first remaining date (maintains order)
    return 0

# Work with copies we can pop from
remaining_dates = list(fb_dates)
remaining_iso = list(fb_iso)

assignments = []  # (post_id, assigned_date_iso, [image_ids])

for post in image_posts:
    if not remaining_dates:
        # Ran out of dates — extrapolate from last known
        if assignments:
            last_date = datetime.strptime(assignments[-1][1], "%Y-%m-%d")
            # Step back 14 days per post
            extrapolated = (last_date - __import__('datetime').timedelta(days=14))
            assignments.append((post["id"], extrapolated.strftime("%Y-%m-%d"), post["image_ids"]))
        continue
    
    idx = find_best_fb_date(post, remaining_dates, remaining_iso)
    assigned_date = remaining_iso[idx]
    
    # Remove this date and all dates newer than it (they're consumed)
    # Actually, just remove the assigned one and everything before it in the list
    # Since list is newest→oldest, removing indices 0..idx = removing newer dates
    remaining_dates = remaining_dates[idx + 1:]
    remaining_iso = remaining_iso[idx + 1:]
    
    assignments.append((post["id"], assigned_date, post["image_ids"]))

print(f"\nAssigned dates to {len(assignments)} image-bearing posts")
print(f"Unused FB dates: {len(remaining_dates)}")

# ── Update timeline.json ──────────────────────────────────────────────────
post_date_map = {}
for post_id, date_iso, img_ids in assignments:
    post_date_map[post_id] = date_iso

updated = 0
for post in data["posts"]:
    if post["id"] in post_date_map:
        d = post_date_map[post["id"]]
        post["date_parsed"] = d
        post["date_hint"] = datetime.strptime(d, "%Y-%m-%d").strftime("%B %d, %Y")
        post["date_source"] = "facebook_aligned"
        updated += 1

with open(tl_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"Updated {updated} posts in timeline.json")

# ── Verify by running comparison ──────────────────────────────────────────
# Load manifest and check how dates improved
manifest_path = BASE / "organized_images" / "manifest.json"
if manifest_path.exists():
    with open(manifest_path, "r") as f:
        old_manifest = json.load(f)
    
    img_to_old_date = {e["original"]: e["date"] for e in old_manifest}
    
    # New dates (from post assignment)
    img_to_new_date = {}
    for post_id, date_iso, img_ids in assignments:
        for img_id in img_ids:
            img_to_new_date[f"img_{img_id}.jpg"] = date_iso
    
    print(f"\nDate improvements for images:")
    improved = 0
    same = 0
    for entry in old_manifest:
        old_date = entry["date"]
        new_date = img_to_new_date.get(entry["original"])
        if new_date and new_date != old_date:
            improved += 1
        elif new_date:
            same += 1
    print(f"  Changed: {improved}")
    print(f"  Unchanged: {same}")
    print(f"  Not in new set: {len(old_manifest) - improved - same}")

# ── Show date range samples ───────────────────────────────────────────────
print(f"\nFirst 10 assignments (newest):")
for post_id, date, imgs in assignments[:10]:
    post = next(p for p in posts if p["id"] == post_id)
    preview = (post.get("ocr_text", "") or "")[:40].replace("\n", " ")
    print(f"  {date}  imgs={len(imgs)}  {preview}")

print(f"\nLast 10 assignments (oldest):")
for post_id, date, imgs in assignments[-10:]:
    post = next(p for p in posts if p["id"] == post_id)
    preview = (post.get("ocr_text", "") or "")[:40].replace("\n", " ")
    print(f"  {date}  imgs={len(imgs)}  {preview}")
