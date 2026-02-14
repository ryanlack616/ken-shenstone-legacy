"""
Scrape all post dates and preview text from Ken Shenstone's Facebook page
using Playwright. Scrolls through the entire timeline collecting data.
"""
import asyncio
import json
import re
from playwright.async_api import async_playwright

URL = "https://www.facebook.com/p/Ken-Shenstone-Ceramic-Studio-Albion-Anagama-100063487453130/"

EXTRACT_JS = """
() => {
    var posts = [];
    // Facebook posts show dates in links with timestamps or text
    // Look for the post header area containing the page name and date
    var containers = document.querySelectorAll('[data-ad-rendering-role="profile_name"]');
    
    // Also try to find date links near post headers
    var allLinks = document.querySelectorAll('a[href*="/posts/"], a[aria-label]');
    var datePat = /(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s+\\d{4}/;
    var relPat = /^(\\d+)\\s*(y|yr|year|mo|month|d|day|h|hr|hour|m|min|w|wk|week)/i;
    
    allLinks.forEach(function(link) {
        var label = link.getAttribute('aria-label') || '';
        var text = link.textContent.trim();
        if (datePat.test(label)) {
            posts.push({type: 'date_label', date: label.match(datePat)[0], href: link.href});
        } else if (datePat.test(text)) {
            posts.push({type: 'date_text', date: text.match(datePat)[0], href: link.href});
        }
    });
    
    // Also look for timestamp elements with aria-label containing dates
    var timestamps = document.querySelectorAll('a[href*="posts"] span, span[id]');
    timestamps.forEach(function(el) {
        var parent = el.closest('a');
        if (parent) {
            var label = parent.getAttribute('aria-label') || '';
            if (datePat.test(label)) {
                posts.push({type: 'timestamp', date: label.match(datePat)[0], href: parent.href});
            }
        }
    });
    
    // Look for use2 timestamp format on FB: abbreviated like "7m", "10y" etc
    // Or full date format in span/abbr elements
    var abbrs = document.querySelectorAll('abbr, span[data-utime]');
    abbrs.forEach(function(el) {
        var title = el.getAttribute('title') || el.getAttribute('data-tooltip-content') || '';
        if (datePat.test(title)) {
            posts.push({type: 'abbr', date: title.match(datePat)[0]});
        }
    });
    
    return posts;
}
"""

# Alternative simpler approach - just get ALL text that looks like dates
EXTRACT_DATES_JS = """
() => {
    var dates = [];
    var datePat = /(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s+\\d{4}/g;
    var text = document.body.innerText;
    var match;
    while ((match = datePat.exec(text)) !== null) {
        // Get some context around the date
        var start = Math.max(0, match.index - 100);
        var end = Math.min(text.length, match.index + match[0].length + 200);
        var context = text.substring(start, end).replace(/\\n+/g, ' | ').trim();
        dates.push({date: match[0], context: context});
    }
    return dates;
}
"""

# Get post structure more directly
EXTRACT_POSTS_JS = """
() => {
    var results = [];
    // Find all top-level post containers
    // Facebook wraps each post in a div with specific structure
    // The date is usually an <a> link near the page name
    
    // Strategy: Find all "Ken Shenstone Ceramic Studio" text nodes,
    // then look for the nearby date element
    var pageNameLinks = document.querySelectorAll('a strong span');
    
    pageNameLinks.forEach(function(span) {
        if (span.textContent.includes('Ken Shenstone')) {
            // Found a post header - now find the date nearby
            var postContainer = span.closest('div[class]');
            // Walk up a few levels to find the full post
            for (var i = 0; i < 10 && postContainer; i++) {
                postContainer = postContainer.parentElement;
                if (!postContainer) break;
                // Check if this container has enough content to be a post
                if (postContainer.offsetHeight > 200) break;
            }
            
            if (postContainer) {
                // Find date - look for links with timestamp-like content
                var links = postContainer.querySelectorAll('a');
                var dateFound = '';
                var postText = '';
                var href = '';
                
                links.forEach(function(link) {
                    var lt = link.textContent.trim();
                    var la = link.getAttribute('aria-label') || '';
                    var datePat = /(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s+\\d{4}/;
                    var relPat = /^\\d+[ymdhw]/;
                    
                    if (datePat.test(la)) {
                        dateFound = la.match(datePat)[0];
                        href = link.href;
                    } else if (datePat.test(lt)) {
                        dateFound = lt.match(datePat)[0];
                        href = link.href;
                    } else if (relPat.test(lt) && !dateFound) {
                        dateFound = 'RELATIVE:' + lt;
                        href = link.href;
                    }
                });
                
                // Get post text content (first 200 chars)
                var textNodes = postContainer.querySelectorAll('div[dir="auto"]');
                textNodes.forEach(function(tn) {
                    var t = tn.textContent.trim();
                    if (t.length > 20 && !t.includes('Ken Shenstone') && !postText) {
                        postText = t.substring(0, 200);
                    }
                });
                
                if (dateFound) {
                    results.push({
                        date: dateFound,
                        text: postText,
                        href: href
                    });
                }
            }
        }
    });
    
    // Deduplicate by date+text
    var seen = {};
    var unique = [];
    results.forEach(function(r) {
        var key = r.date + '|' + r.text.substring(0, 50);
        if (!seen[key]) {
            seen[key] = true;
            unique.push(r);
        }
    });
    
    return unique;
}
"""

async def main():
    async with async_playwright() as p:
        # Connect to existing browser
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        if not contexts:
            print("No browser contexts found")
            return
        
        page = contexts[0].pages[0]
        
        # Navigate to the page
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        all_posts = []
        scroll_count = 0
        max_scrolls = 100
        last_height = 0
        no_change_count = 0
        
        while scroll_count < max_scrolls:
            # Scroll down
            height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            # Extract posts
            posts = await page.evaluate(EXTRACT_POSTS_JS)
            
            # Add new posts
            for post in posts:
                key = post.get('date', '') + '|' + post.get('text', '')[:50]
                if not any(p.get('date', '') + '|' + p.get('text', '')[:50] == key for p in all_posts):
                    all_posts.append(post)
                    print(f"  [{len(all_posts)}] {post.get('date', '?'):30s} {post.get('text', '')[:80]}")
            
            # Check if we've stopped loading new content
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                no_change_count += 1
                if no_change_count > 5:
                    print(f"\nNo new content after {no_change_count} scrolls, stopping")
                    break
            else:
                no_change_count = 0
            last_height = new_height
            scroll_count += 1
            
            if scroll_count % 10 == 0:
                print(f"  ... scrolled {scroll_count} times, {len(all_posts)} posts found, height={new_height}")
        
        print(f"\nTotal: {len(all_posts)} posts with dates found after {scroll_count} scrolls")
        
        # Save results
        with open("fb_dates.json", "w") as f:
            json.dump(all_posts, f, indent=2)
        
        # Also write a readable report
        with open("fb_dates_report.txt", "w") as f:
            f.write(f"Facebook Post Dates - Ken Shenstone Ceramic Studio\n")
            f.write(f"Scraped from: {URL}\n")
            f.write(f"Total posts found: {len(all_posts)}\n\n")
            
            for i, post in enumerate(all_posts, 1):
                f.write(f"{i:3d}. {post.get('date', '?'):30s} | {post.get('text', '')[:100]}\n")
        
        print("Saved to fb_dates.json and fb_dates_report.txt")

asyncio.run(main())
