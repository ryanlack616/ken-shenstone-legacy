"""
Build timeline.html from extracted/timeline.json.

Creates a browsable, filterable timeline page for the Ken Shenstone website.
Posts are grouped by estimated era (based on dates + scroll position).
"""
import json
import os
import re
from html import escape

BASE = os.path.dirname(os.path.abspath(__file__))
TL_PATH = os.path.join(BASE, "extracted", "timeline.json")
OUT_PATH = os.path.join(BASE, "timeline.html")

with open(TL_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

posts = data["posts"]
images_map = {img["id"]: img for img in data.get("images", [])}

# Sort posts by scroll position (y_global) — top of page = newest
posts_sorted = sorted(posts, key=lambda p: p.get("y_global", 0))

# Filter to posts with actual content (text or images)
meaningful = [p for p in posts_sorted if p.get("ocr_text", "").strip() or p.get("image_ids")]

# Build era estimates based on known dates + position interpolation
# Known dates: 2020 (top), 2016, 2014, 2013, 2012, 2009 (bottom)
# Facebook = newest first, so scroll down = older

# Assign rough eras based on source file position
def estimate_era(post):
    """Estimate time period from source file + position."""
    src = post.get("source_file", "")
    date = post.get("date_parsed", "")
    if date:
        year = date[:4]
        return year
    
    # Map source files to rough eras (fb1=newest, fb5=header+newest)
    chunk = post.get("chunk_file", "")
    if "fb5_chunk_000" in chunk:
        return "header"
    if chunk.startswith("fb5_"):
        return "2019-2020"
    if chunk.startswith("fb1_"):
        return "2018-2019"
    if chunk.startswith("fb2_"):
        return "2016-2018" 
    if chunk.startswith("fb3_"):
        return "2013-2015"
    if chunk.startswith("fb4_"):
        return "2009-2012"
    return "unknown"


def clean_text(text):
    """Clean OCR text for display."""
    if not text:
        return ""
    # Remove common OCR artifacts
    text = text.strip()
    # Collapse excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def make_tag_html(tags):
    """Create tag badges."""
    if not tags:
        return ""
    badges = []
    tag_icons = {
        "kiln": "🔥",
        "pottery": "🏺", 
        "sale": "💰",
        "event": "🎪",
        "wood": "🪵",
        "teabowl": "🍵",
        "community": "👥",
    }
    for tag in tags:
        icon = tag_icons.get(tag, "")
        badges.append(f'<span class="tag tag-{tag}">{icon} {tag}</span>')
    return " ".join(badges)


# Group posts by era
from collections import OrderedDict
era_order = ["header", "2019-2020", "2018-2019", "2016-2018", "2013-2015", "2009-2012", "unknown"]
era_labels = {
    "header": "Page Header",
    "2019-2020": "Recent (2019–2020)",
    "2018-2019": "2018–2019",
    "2016-2018": "2016–2018",
    "2013-2015": "2013–2015",
    "2009-2012": "2009–2012",
    "2020": "2020",
    "2016": "2016",
    "2014": "2014",
    "2013": "2013",
    "2012": "2012",
    "2009": "2009",
    "unknown": "Undated",
}

grouped = OrderedDict()
for era in era_order:
    grouped[era] = []

for post in meaningful:
    era = estimate_era(post)
    # Merge specific years into their era ranges
    if era in ("2019", "2020"):
        era = "2019-2020"
    elif era in ("2018",):
        era = "2018-2019"
    elif era in ("2016", "2017"):
        era = "2016-2018"
    elif era in ("2013", "2014", "2015"):
        era = "2013-2015"
    elif era in ("2009", "2010", "2011", "2012"):
        era = "2009-2012"
    if era not in grouped:
        grouped[era] = []
    grouped[era].append(post)

# Stats
total_with_text = sum(1 for p in meaningful if p.get("ocr_text", "").strip())
total_with_images = sum(1 for p in meaningful if p.get("image_ids"))
total_sales = sum(1 for p in meaningful if "sale" in p.get("tags", []))
total_kiln = sum(1 for p in meaningful if "kiln" in p.get("tags", []))

# Build HTML
html_parts = []
html_parts.append(f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Timeline — Ken Shenstone Legacy</title>
<meta name="description" content="A decade of posts from the Ken Shenstone Ceramic Studio & Albion Anagama Facebook page — kiln firings, pottery sales, community events, and studio life.">
<link rel="stylesheet" href="css/style.css">
<style>
/* Timeline-specific styles */
.timeline-stats {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 1rem;
  margin: 2rem 0;
}}
.timeline-stats .stat {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  text-align: center;
}}
.timeline-stats .stat-number {{
  font-family: var(--serif);
  font-size: 2rem;
  color: var(--ember);
  font-weight: bold;
}}
.timeline-stats .stat-label {{
  font-size: 0.85rem;
  color: var(--text-dim);
  margin-top: 0.25rem;
}}

.filter-bar {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 1.5rem 0;
  padding: 1rem;
  background: var(--bg-card);
  border-radius: 8px;
  border: 1px solid var(--border);
}}
.filter-bar button {{
  background: var(--bg-warm);
  border: 1px solid var(--border);
  padding: 0.4rem 0.8rem;
  border-radius: 4px;
  cursor: pointer;
  font-family: var(--sans);
  font-size: 0.85rem;
  color: var(--text);
  transition: all 0.2s;
}}
.filter-bar button:hover,
.filter-bar button.active {{
  background: var(--teal);
  color: white;
  border-color: var(--teal);
}}

.era-section {{
  margin: 2.5rem 0;
}}
.era-header {{
  font-family: var(--serif);
  font-size: 1.5rem;
  color: var(--teal);
  border-bottom: 2px solid var(--teal);
  padding-bottom: 0.5rem;
  margin-bottom: 1.5rem;
  position: sticky;
  top: 60px;
  background: var(--bg);
  z-index: 5;
  padding-top: 0.5rem;
}}
.era-header .count {{
  font-size: 0.85rem;
  color: var(--text-dim);
  font-family: var(--sans);
  font-weight: normal;
}}

.post-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.25rem;
  margin-bottom: 1rem;
  transition: border-color 0.2s;
}}
.post-card:hover {{
  border-color: var(--teal-light);
}}
.post-card.has-sale {{
  border-left: 3px solid var(--ember);
}}
.post-card.has-kiln {{
  border-left: 3px solid var(--teal);
}}

.post-meta {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
  font-size: 0.8rem;
  color: var(--text-dim);
}}
.post-date {{
  font-weight: 600;
  color: var(--teal);
}}

.post-text {{
  font-size: 0.95rem;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}}
.post-text.truncated {{
  max-height: 200px;
  overflow: hidden;
  position: relative;
}}
.post-text.truncated::after {{
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 60px;
  background: linear-gradient(transparent, var(--bg-card));
}}

.post-expand {{
  background: none;
  border: none;
  color: var(--teal);
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.5rem 0;
  font-family: var(--sans);
}}

.tag {{
  display: inline-block;
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 12px;
  margin-right: 0.25rem;
  background: var(--bg-warm);
  color: var(--text-light);
  border: 1px solid var(--border);
}}
.tag-kiln {{ background: #fef3ec; color: #c4784a; border-color: #e8c4a8; }}
.tag-pottery {{ background: #f0f5f4; color: #5a7f7b; border-color: #a8c8c4; }}
.tag-sale {{ background: #fdf8ec; color: #b8860b; border-color: #dcc878; }}
.tag-event {{ background: #f5f0fa; color: #7b5ea7; border-color: #c4b0d8; }}
.tag-wood {{ background: #f5f2ec; color: #8b6914; border-color: #c8b078; }}

.post-images {{
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
  flex-wrap: wrap;
}}
.post-images img {{
  max-height: 150px;
  border-radius: 4px;
  border: 1px solid var(--border);
}}

.post-indicators {{
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}}
.indicator {{
  font-size: 0.75rem;
  color: var(--text-dim);
  background: var(--bg-warm);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
}}

.source-note {{
  font-size: 0.8rem;
  color: var(--text-dim);
  margin-top: 2rem;
  padding: 1rem;
  background: var(--bg-warm);
  border-radius: 8px;
  line-height: 1.6;
}}

@media (max-width: 768px) {{
  .timeline-stats {{
    grid-template-columns: repeat(2, 1fr);
  }}
  .era-header {{
    font-size: 1.2rem;
  }}
}}
</style>
</head>
<body>

<!-- Navigation -->
<header class="site-nav">
  <div class="logo">Ken Shenstone <span class="accent">Legacy</span></div>
  <nav>
    <a href="index.html">Home</a>
    <a href="about.html">About</a>
    <a href="kiln.html">The Kiln</a>
    <a href="work.html">Work</a>
    <a href="studio.html">Studio Life</a>
    <a href="timeline.html" class="active">Timeline</a>
    <a href="contact.html">Contact</a>
  </nav>
</header>

<main class="content">
  <h1 class="page-title">Facebook Timeline</h1>
  <p class="intro">
    Over a decade of posts from the <strong>Ken Shenstone Ceramic Studio & Albion Anagama</strong>
    Facebook page — kiln firings, pottery sales, community gatherings, and daily life at the studio.
    Extracted from full-page screenshots, preserving the chronological record.
  </p>

  <div class="timeline-stats">
    <div class="stat">
      <div class="stat-number">{len(meaningful)}</div>
      <div class="stat-label">Posts</div>
    </div>
    <div class="stat">
      <div class="stat-number">{total_with_images}</div>
      <div class="stat-label">With Photos</div>
    </div>
    <div class="stat">
      <div class="stat-number">{total_kiln}</div>
      <div class="stat-label">Kiln / Firing</div>
    </div>
    <div class="stat">
      <div class="stat-number">{total_sales}</div>
      <div class="stat-label">Sales / Events</div>
    </div>
  </div>

  <div class="filter-bar">
    <span style="color: var(--text-dim); font-size: 0.85rem; margin-right: 0.5rem; align-self: center;">Filter:</span>
    <button class="active" onclick="filterPosts('all')">All</button>
    <button onclick="filterPosts('kiln')">🔥 Kiln</button>
    <button onclick="filterPosts('pottery')">🏺 Pottery</button>
    <button onclick="filterPosts('sale')">💰 Sales</button>
    <button onclick="filterPosts('event')">🎪 Events</button>
    <button onclick="filterPosts('has-text')">📝 With Text</button>
    <button onclick="filterPosts('has-image')">📷 With Photos</button>
  </div>
''')

# Build each era section  
for era in era_order:
    era_posts = grouped.get(era, [])
    if not era_posts or era == "header":
        continue
    
    label = era_labels.get(era, era)
    html_parts.append(f'''
  <section class="era-section" data-era="{era}">
    <h2 class="era-header">{label} <span class="count">({len(era_posts)} posts)</span></h2>
''')
    
    for post in era_posts:
        text = clean_text(post.get("ocr_text", ""))
        tags = post.get("tags", [])
        date_hint = post.get("date_hint", "")
        has_images = bool(post.get("image_ids"))
        
        # Skip posts that are just "+3" or "comments" or very short noise
        if text and len(text) < 10 and not has_images:
            noise_words = {"+3", "+4", "+5", "comments", "shares", "like", "reply"}
            if text.strip().lower() in noise_words:
                continue
        
        # Card classes
        card_classes = ["post-card"]
        if "sale" in tags:
            card_classes.append("has-sale")
        elif "kiln" in tags:
            card_classes.append("has-kiln")
        
        # Data attributes for filtering
        data_attrs = []
        for tag in tags:
            data_attrs.append(f'data-tag-{tag}="1"')
        if text.strip():
            data_attrs.append('data-has-text="1"')
        if has_images:
            data_attrs.append('data-has-image="1"')
        
        html_parts.append(f'    <div class="{" ".join(card_classes)}" {" ".join(data_attrs)}>')
        
        # Meta row
        html_parts.append('      <div class="post-meta">')
        if date_hint:
            html_parts.append(f'        <span class="post-date">{escape(date_hint)}</span>')
        else:
            html_parts.append(f'        <span>{escape(post.get("chunk_file", ""))}</span>')
        html_parts.append(f'        <span>{make_tag_html(tags)}</span>')
        html_parts.append('      </div>')
        
        # Text
        if text.strip():
            is_long = len(text) > 300
            trunc_class = ' truncated' if is_long else ''
            html_parts.append(f'      <div class="post-text{trunc_class}" id="text-{post["id"]}">{escape(text)}</div>')
            if is_long:
                html_parts.append(f'      <button class="post-expand" onclick="toggleText(\'{post["id"]}\')">Show more</button>')
        
        # Image references
        if has_images:
            html_parts.append('      <div class="post-images">')
            for img_id in post.get("image_ids", []):
                img_info = images_map.get(img_id, {})
                img_file = img_info.get("saved_path", "")
                if img_file:
                    html_parts.append(f'        <img src="extracted/images/{escape(img_file)}" alt="Post image" loading="lazy">')
            html_parts.append('      </div>')
        
        # Indicators
        indicators = []
        if post.get("has_more_content"):
            indicators.append("📄 Truncated (See more)")
        if post.get("has_video"):
            indicators.append("🎬 Video")
        if post.get("has_more_photos"):
            hint = post.get("more_photos_hint", "")
            indicators.append(f"📸 More photos{': ' + hint if hint else ''}")
        if indicators:
            html_parts.append('      <div class="post-indicators">')
            for ind in indicators:
                html_parts.append(f'        <span class="indicator">{ind}</span>')
            html_parts.append('      </div>')
        
        html_parts.append('    </div>')
    
    html_parts.append('  </section>')

# Footer
html_parts.append(f'''
  <div class="source-note">
    <strong>About this timeline:</strong> These posts were extracted from full-page screenshots of the
    Ken Shenstone Ceramic Studio & Albion Anagama Facebook page, captured February 2026.
    Text was extracted using EasyOCR. Some posts may contain OCR artifacts.
    {len(data.get("crawl_targets", []))} items have been flagged for additional content retrieval.
    <br><br>
    <em>5 screenshots → 58 chunks → {len(meaningful)} posts with content</em>
  </div>
</main>

<footer class="site-footer">
  <p>Preserving the legacy of Ken Shenstone &amp; the Albion Anagama</p>
  <p class="footer-sub">Albion, Michigan — Since 1987</p>
</footer>

<script>
function filterPosts(filter) {{
  const cards = document.querySelectorAll('.post-card');
  const buttons = document.querySelectorAll('.filter-bar button');
  
  buttons.forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  
  cards.forEach(card => {{
    let show = false;
    if (filter === 'all') {{
      show = true;
    }} else if (filter === 'has-text') {{
      show = card.dataset.hasText === '1';
    }} else if (filter === 'has-image') {{
      show = card.dataset.hasImage === '1';
    }} else {{
      show = card.dataset['tag' + filter.charAt(0).toUpperCase() + filter.slice(1)] === '1';
    }}
    card.style.display = show ? '' : 'none';
  }});
  
  // Update era counts
  document.querySelectorAll('.era-section').forEach(section => {{
    const visible = section.querySelectorAll('.post-card:not([style*="display: none"])').length;
    const count = section.querySelector('.count');
    if (count) count.textContent = '(' + visible + ' posts)';
    section.style.display = visible > 0 ? '' : 'none';
  }});
}}

function toggleText(id) {{
  const el = document.getElementById('text-' + id);
  const btn = el.nextElementSibling;
  if (el.classList.contains('truncated')) {{
    el.classList.remove('truncated');
    btn.textContent = 'Show less';
  }} else {{
    el.classList.add('truncated');
    btn.textContent = 'Show more';
  }}
}}
</script>

</body>
</html>''')

# Write
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(html_parts))

print(f"Built timeline.html: {len(meaningful)} posts across {sum(1 for e in grouped.values() if e and e != grouped.get('header'))} eras")
print(f"File: {OUT_PATH}")
