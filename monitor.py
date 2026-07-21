#!/usr/bin/env python3
"""
BookMyShow Theatre Watcher
===========================
Watches a BookMyShow "buy tickets" page and alerts you the moment a theatre
whose name contains PVR, INOX, or AGS shows up in the listings.

WHY A REAL BROWSER?
BookMyShow renders its theatre list with JavaScript, so a plain
`requests.get()` won't see it. This script uses Playwright to open the page
in a real (headless) browser, exactly like your phone does.

HOW IT REMEMBERS STATE
Every theatre name it has ever seen containing your keywords is stored in
`seen_theatres.json` next to this script. On each run it only notifies you
about names that are NEW since the last run — so you get pinged once, not
every 5 minutes.

SETUP
1. pip install -r requirements.txt
2. playwright install chromium
3. (Optional but recommended) Set up Telegram alerts — see README.md
4. Run once manually to make sure it works:
       python monitor.py
5. Schedule it (see README.md for cron / Task Scheduler examples)
"""

import json
import os
import re
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

# ----------------------------------------------------------------------
# CONFIG — edit these
# ----------------------------------------------------------------------

URL = "https://in.bookmyshow.com/movies/chennai/jana-nayagan/buytickets/ET00430817/20260725"

KEYWORDS = ["PVR", "INOX", "AGS", "Rohini"]

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_theatres.json")

# ntfy.sh push notifications — install the "ntfy" app on your Android phone
# and subscribe to this same topic name. Pick something long/random so
# strangers can't guess it and spam you (topics are public by default).
NTFY_TOPIC = os.environ.get("BMS_NTFY_TOPIC", "")

# ----------------------------------------------------------------------


def fetch_theatre_names(url: str) -> list[str]:
    """Open the page in a headless browser and pull out theatre name candidates."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ))
        page.goto(url, wait_until="networkidle", timeout=60000)

        # Theatre cards on BMS typically carry the venue name as a heading-like
        # element followed by "<distance> km". We grab all visible text and
        # split into lines, which is robust to their CSS class names changing.
        page.wait_for_timeout(3000)  # let any lazy-loaded rows settle
        body_text = page.inner_text("body")
        browser.close()

    lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]

    # A theatre name line is usually followed shortly by a "X.X km" line.
    # We collect any line that looks like a venue name (not a time, not a
    # format tag, not a nav label) sitting near a "km" marker.
    theatre_names = []
    km_pattern = re.compile(r"\d+(\.\d+)?\s*km", re.IGNORECASE)
    for i, line in enumerate(lines):
        if km_pattern.search(line):
            # look back up to 3 lines for the venue name
            for j in range(max(0, i - 3), i):
                candidate = lines[j]
                if _looks_like_theatre_name(candidate):
                    theatre_names.append(candidate)
                    break

    # Fallback / belt-and-suspenders: also scan every line directly for the
    # keywords in case the layout heuristic above misses a row.
    for line in lines:
        if any(k.lower() in line.lower() for k in KEYWORDS) and _looks_like_theatre_name(line):
            theatre_names.append(line)

    # de-dupe, preserve order
    seen = set()
    result = []
    for name in theatre_names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _looks_like_theatre_name(line: str) -> bool:
    if len(line) < 3 or len(line) > 80:
        return False
    # exclude obvious non-name lines
    bad_markers = ["km", "AM", "PM", "Sort by", "Special Formats", "Cancellable",
                   "Mark Favourite", "Tamil", "2D", "3D", "₹"]
    if any(line == b or line.endswith(b) for b in ["km"]):
        return False
    if re.fullmatch(r"\d{1,2}:\d{2}\s?(AM|PM)", line):
        return False
    return True


def matching_theatres(names: list[str]) -> list[str]:
    return [n for n in names if any(k.lower() in n.lower() for k in KEYWORDS)]


def load_seen() -> set[str]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set[str]) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def notify(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message = f"[{timestamp}] {message}"
    print(full_message)

    if NTFY_TOPIC:
        try:
            import urllib.request

            api_url = f"https://ntfy.sh/{NTFY_TOPIC}"
            req = urllib.request.Request(
                api_url,
                data=message.encode("utf-8"),
                headers={
                    "Title": "BookMyShow theatre alert",
                    "Priority": "urgent",
                    "Tags": "movie_camera",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"  (ntfy send failed: {e})")


def main():
    print(f"Checking {URL} ...")
    try:
        names = fetch_theatre_names(URL)
    except Exception as e:
        print(f"ERROR fetching page: {e}")
        sys.exit(1)

    current_matches = set(matching_theatres(names))
    seen = load_seen()

    new_matches = current_matches - seen

    if new_matches:
        for name in sorted(new_matches):
            notify(f"🎬 New theatre available: {name}")
        save_seen(seen | current_matches)
    else:
        print(f"No new matching theatres. ({len(current_matches)} known match(es) so far)")


if __name__ == "__main__":
    main()

