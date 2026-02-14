"""
Compare Facebook actual dates with our assigned dates from rename_images.py.
Cross-reference the OCR text content to match posts to images.
"""
import json
from datetime import datetime

# Facebook dates scraped from the actual page
FB_DATES = [
    "February 26, 2020",
    "May 6, 2019",
    "May 2, 2019",
    "May 1, 2019",
    "September 9, 2018",
    "September 8, 2018",
    "June 19, 2018",
    "May 12, 2018",
    "May 7, 2018",
    "May 2, 2018",
    "January 23, 2018",
    "December 8, 2017",
    "June 27, 2017",
    "December 15, 2016",
    "December 8, 2016",
    "December 7, 2016",
    "October 11, 2016",
    "August 6, 2016",
    "July 17, 2016",
    "July 16, 2016",
    "July 15, 2016",
    "July 14, 2016",
    "July 12, 2016",
    "July 11, 2016",
    "July 4, 2016",
    "July 3, 2016",
    "July 2, 2016",
    "July 1, 2016",
    "June 29, 2016",
    "June 25, 2016",
    "June 19, 2016",
    "June 18, 2016",
    "June 17, 2016",
    "June 7, 2016",
    "December 19, 2015",
    "December 12, 2015",
    "November 27, 2015",
    "November 20, 2015",
    "November 1, 2015",
    "October 31, 2015",
    "October 30, 2015",
    "October 29, 2015",
    "October 26, 2015",
    "October 24, 2015",
    "October 20, 2015",
    "October 18, 2015",
    "October 17, 2015",
    "September 20, 2015",
    "September 19, 2015",
    "September 18, 2015",
    "September 16, 2015",
    "September 15, 2015",
    "September 10, 2015",
    "September 2, 2015",
    "July 27, 2015",
    "May 18, 2015",
    "May 16, 2015",
    "May 14, 2015",
    "May 3, 2015",
    "May 2, 2015",
    "April 23, 2015",
    "March 22, 2015",
    "March 21, 2015",
    "March 9, 2015",
    "December 5, 2014",
    "December 2, 2014",
    "November 30, 2014",
    "November 29, 2014",
    "November 27, 2014",
    "November 21, 2014",
    "September 19, 2014",
    "August 30, 2014",
    "October 23, 2014",
    "August 27, 2014",
    "August 26, 2014",
    "August 5, 2014",
    "August 4, 2014",
    "August 1, 2014",
    "July 25, 2014",
    "June 21, 2014",
    "June 17, 2014",
    "May 20, 2014",
    "May 14, 2014",
    "May 10, 2014",
    "May 1, 2014",
    "December 5, 2013",
    "December 1, 2013",
    "November 30, 2013",
    "November 29, 2013",
    "November 7, 2013",
    "October 31, 2013",
    "October 21, 2013",
    "September 29, 2013",
    "July 25, 2013",
    "May 6, 2013",
    "May 4, 2013",
    "March 19, 2013",
    "February 4, 2013",
    "January 7, 2013",
    "December 6, 2012",
    "November 25, 2012",
    "November 17, 2012",
    "November 12, 2012",
    "November 11, 2012",
    "November 8, 2012",
    "November 7, 2012",
    "November 1, 2012",
    "October 22, 2012",
    "September 13, 2012",
    "September 3, 2012",
    "July 16, 2012",
    "March 2, 2012",
    "November 8, 2011",
    "August 11, 2011",
    "June 24, 2011",
    "October 10, 2010",
    "September 26, 2010",
    "November 11, 2009",
    "July 17, 2009",
    "May 15, 2009",
    "March 30, 2009",
    "March 28, 2009",
]

# Parse to dates
fb_parsed = []
for d in FB_DATES:
    fb_parsed.append(datetime.strptime(d, "%B %d, %Y"))

fb_parsed.sort()

# Load our timeline data
with open("extracted/timeline.json", "r") as f:
    data = json.load(f)

posts = data["posts"]
images_meta = data.get("images", [])

# Load our manifest from organized_images
with open("organized_images/manifest.json", "r") as f:
    manifest = json.load(f)

# Stats
print(f"Facebook dates found: {len(fb_parsed)}")
print(f"Timeline posts: {len(posts)}")
print(f"Images in manifest: {len(manifest)}")
print(f"FB date range: {fb_parsed[0].strftime('%Y-%m-%d')} to {fb_parsed[-1].strftime('%Y-%m-%d')}")
print()

# Group FB dates by year
by_year = {}
for d in fb_parsed:
    by_year.setdefault(d.year, []).append(d)

print("Posts per year (from Facebook):")
for year in sorted(by_year.keys()):
    print(f"  {year}: {len(by_year[year])} posts")
print()

# Now I need to match our posts to FB dates.
# Our posts are in chronological order (from the rename script).
# FB has 122 dates for what was originally 176 posts in the OCR data.
# Some FB dates may correspond to events or embedded content, not actual posts.
# Some posts may not have been captured by our scrolling.

# The posts should be in the same order. Let me sort both and try to align them.
# Key insight: our 176 OCR posts include EVERY visible element from the screenshots.
# Facebook's 122 dates are for distinct posts (some OCR "posts" may be comments/shared content).

# Let's compare: for each image in our manifest, check how close our assigned date
# is to the nearest FB date.

report = []
for entry in manifest:
    our_date_str = entry.get("date", "")
    precision = entry.get("date_precision", "")
    source = entry.get("date_source", "")
    
    if not our_date_str:
        continue
    
    # Parse our date
    try:
        if len(our_date_str) == 7:  # YYYY-MM
            our_date = datetime.strptime(our_date_str + "-15", "%Y-%m-%d")
        else:
            our_date = datetime.strptime(our_date_str, "%Y-%m-%d")
    except:
        continue
    
    # Find nearest FB date
    diffs = [(abs((our_date - fb_d).days), fb_d) for fb_d in fb_parsed]
    diffs.sort()
    nearest_days, nearest_fb = diffs[0]
    
    report.append({
        "original": entry.get("original", ""),
        "renamed": entry.get("renamed", ""),
        "our_date": our_date_str,
        "our_source": source,
        "nearest_fb_date": nearest_fb.strftime("%Y-%m-%d"),
        "days_off": nearest_days,
        "ocr_preview": entry.get("ocr_preview", "")[:80]
    })

# Sort by days_off descending to see worst mismatches first
report.sort(key=lambda r: -r["days_off"])

# Write report
with open("_fb_comparison.txt", "w", encoding="utf-8") as f:
    f.write("Facebook Date Verification Report\n")
    f.write("=" * 80 + "\n")
    f.write(f"Facebook dates scraped: {len(fb_parsed)}\n")
    f.write(f"Our images: {len(manifest)}\n\n")
    
    # Summary stats
    exact = sum(1 for r in report if r["days_off"] == 0)
    close = sum(1 for r in report if 0 < r["days_off"] <= 7)
    moderate = sum(1 for r in report if 7 < r["days_off"] <= 30)
    far = sum(1 for r in report if r["days_off"] > 30)
    
    f.write(f"Date accuracy:\n")
    f.write(f"  Exact match (0 days off): {exact}\n")
    f.write(f"  Close (1-7 days off): {close}\n")
    f.write(f"  Moderate (8-30 days off): {moderate}\n")
    f.write(f"  Far off (30+ days): {far}\n\n")
    
    f.write("WORST MISMATCHES (sorted by days off):\n")
    f.write("-" * 120 + "\n")
    f.write(f"{'Original':<30s} {'Our Date':<12s} {'FB Date':<12s} {'Days Off':<10s} {'Source':<15s} {'Preview'}\n")
    f.write("-" * 120 + "\n")
    
    for r in report:
        f.write(f"{r['original']:<30s} {r['our_date']:<12s} {r['nearest_fb_date']:<12s} {r['days_off']:<10d} {r['our_source']:<15s} {r['ocr_preview'][:60]}\n")

print("Written to _fb_comparison.txt")

# Also print top 20 worst
print("\nTop 20 worst mismatches:")
print(f"{'Original':<30s} {'Our':<12s} {'FB':<12s} {'Off':<6s} {'Source'}")
print("-" * 80)
for r in report[:20]:
    print(f"{r['original']:<30s} {r['our_date']:<12s} {r['nearest_fb_date']:<12s} {r['days_off']:<6d} {r['our_source']}")
