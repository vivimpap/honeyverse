#!/usr/bin/env python3
"""
AO3 fast scraper - replaces the old two-phase (IDs, then one request per fic)
workflow with a single pass over the tag's listing pages.

WHY THIS IS FASTER
------------------
The old Phase 2 fetched one page per fic. That was never necessary: AO3's work
listing pages already embed the full metadata for every fic they list, and
they list 20 fics per page. So one request gives you 20 fics instead of 1.

Two things people assume are wrong, and both are worth knowing:

  1. "The listing truncates the tag list with '...'."
     It doesn't. That truncation is pure CSS. AO3's blurb_tag_block helper
     writes every relationship / character / freeform tag into the HTML. The
     full list is there, logged out, in the page you already downloaded.

  2. "5-8 seconds between requests is what AO3 wants."
     AO3's published rate limit is 300 requests per 300 seconds (1/second).
     This script self-limits to 200 per 300s, which is a third under the limit
     and still ~4x faster per request than the old delay.

Combined: ~20x fewer requests, each ~4x sooner. For a 10,000-fic tag that is
roughly 19 hours -> ~13 minutes.

It also means ~20x fewer chances to hit a 525. Those errors aren't your rate
limit - 525 is Cloudflare failing to reach AO3's origin - so they're retried
fast here (2s, 5s, 10s...) instead of the old 15-60s ladder.

(20 per page is what AO3 actually serves. The otwarchive repo's sample config
says 25; production overrides it. Nothing here depends on the number - the
script reads however many blurbs a page returns.)

OUTPUT
------
Identical columns to the old Phase 2, in the same order, with the same ' ; '
separator between values (semicolon, never |, because AO3 puts | *inside*
individual tags: "Choi Taeyang | Theo"). Drop-in replacement for the old CSV.

THE ONE FIELD THAT NEEDS A SECOND LOOK
--------------------------------------
'published' is the only column not in the listing - blurbs show the *revised*
date. For any fic with a single posted chapter those are the same date, so it's
filled straight away. That's most fics. For the rest, run:

    python3 ao3_fast.py --fill-published

which visits only the multi-chapter fics (typically ~20-30% of a fandom).
Skip it entirely if you only care about the updated date.

USAGE
-----
    pip3 install requests beautifulsoup4        # lxml is optional but faster
    # edit the EDIT THESE block below, then:
    python3 ao3_fast.py                         # main scrape (resumable)
    python3 ao3_fast.py --fill-published        # optional exact publish dates
    python3 ao3_fast.py --update                # later: pull in new/changed fics
    python3 ao3_fast.py --verify 15             # sanity-check vs real fic pages

Every mode is resumable: rerun the same command and it continues.
"""

import argparse
import csv
import os
import re
import sys
import time
from collections import deque
from datetime import date, timedelta
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import requests
from bs4 import BeautifulSoup

# ==================== EDIT THESE ====================

# A real contact email. AO3 asks scrapers to identify themselves.
CONTACT_EMAIL = "your_email@example.com"

# The AO3 tag works URL, with any filters already applied.
#   https://archiveofourown.org/tags/P1Harmony%20(Band)/works
TAG_URL = "https://archiveofourown.org/tags/YOUR_TAG_HERE/works"

# Short slug used to name the output files.
PROJECT_NAME = "myfandom"

# ==================== RATE LIMITING ====================
# AO3's limit (otwarchive config.yml): RATE_LIMIT_NUMBER 300 / RATE_LIMIT_PERIOD
# 300, i.e. 300 requests per 300 seconds. We stay a third under it. The limiter
# is a rolling window, so retries count against the budget too and the script
# cannot exceed this even when AO3 is flaky.

MAX_REQUESTS_PER_WINDOW = 200
WINDOW_SECONDS = 300
MIN_SECONDS_BETWEEN_REQUESTS = 1.5

# 525/502/503 are AO3/Cloudflare hiccups, not your rate limit -> retry fast.
SERVER_ERROR_WAITS = [2, 5, 10, 20, 40]
RATE_LIMIT_RETRIES = 6
OUTAGE_THRESHOLD = 10          # consecutive hard failures -> assume AO3 is down

# ================================================================

# AO3 clamps deep paging: Search::Query#page does
#   [requested_page, (MAX_SEARCH_RESULTS / per_page).ceil].min
# so past the ceiling it silently re-serves the last real page instead of
# erroring. Both of those numbers are deployment config we can't read from
# outside, so don't try to compute the ceiling - detect it. When the clamp
# kicks in we get a full page whose fics we've all seen before, which is what
# CLAMP_REPEAT_LIMIT below watches for. This is just a runaway stop.
MAX_PAGE_SAFETY_LIMIT = 20000
CLAMP_REPEAT_LIMIT = 2         # full pages with zero new fics -> we're stuck

OUTPUT_CSV = f"{PROJECT_NAME}_metadata.csv"
PROGRESS_FILE = f"{PROJECT_NAME}_progress.txt"

USER_AGENT = f"AO3 metadata (personal research) - contact: {CONTACT_EMAIL}"
MULTI_SEP = " ; "
SERVER_ERROR_CODES = {500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530}

FIELDS = [
    "work_id", "url", "title", "author", "rating", "archive_warnings",
    "categories", "fandoms", "relationships", "characters", "additional_tags",
    "language", "published", "status_label", "status_date",
    "words", "chapters", "comments", "kudos", "bookmarks", "hits",
]

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

# Pick the fastest parser that's installed.
try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"


# ---------------------------------------------------------------- networking

class RateLimiter:
    """Rolling-window limiter. Guarantees we never exceed the budget."""

    def __init__(self, max_requests, period, min_gap):
        self.max_requests = max_requests
        self.period = period
        self.min_gap = min_gap
        self.times = deque()

    def wait(self):
        now = time.monotonic()
        if self.times:
            gap = self.min_gap - (now - self.times[-1])
            if gap > 0:
                time.sleep(gap)
                now = time.monotonic()
        while True:
            cutoff = now - self.period
            while self.times and self.times[0] < cutoff:
                self.times.popleft()
            if len(self.times) < self.max_requests:
                break
            sleep_for = max(self.times[0] + self.period - now + 0.1, 0.1)
            time.sleep(sleep_for)
            now = time.monotonic()
        self.times.append(now)


class Fetcher:
    """One keep-alive connection, reused for every request.

    The old scripts opened a fresh TCP+TLS connection per fic. Reusing one
    session removes a handshake (~0.2-0.5s) from every single request.
    """

    def __init__(self, limiter):
        self.limiter = limiter
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "text/html,application/xhtml+xml",
        })

    @staticmethod
    def _is_rate_limited(resp):
        if resp.status_code == 429:
            return True
        return "retry later" in resp.text[:2000].lower()

    def get(self, url):
        """Returns (kind, response). kind: ok | restricted | notfound | error."""
        rl_retries = 0
        rl_wait = 60.0
        server_try = 0

        while True:
            self.limiter.wait()
            try:
                resp = self.session.get(url, timeout=60)
            except requests.RequestException as e:
                if server_try >= len(SERVER_ERROR_WAITS):
                    print(f"  ! network still failing ({e})", end=" ")
                    return ("error", None)
                w = SERVER_ERROR_WAITS[server_try]
                server_try += 1
                print(f"  ! network error; retry in {w}s", end=" ")
                time.sleep(w)
                continue

            if self._is_rate_limited(resp):
                if rl_retries >= RATE_LIMIT_RETRIES:
                    return ("error", None)
                retry_after = resp.headers.get("Retry-After", "")
                pause = max(int(retry_after) if retry_after.isdigit() else int(rl_wait), 60)
                print(f"  ! throttled by AO3; waiting {pause}s", end=" ")
                time.sleep(pause)
                rl_wait *= 2
                rl_retries += 1
                continue

            if resp.status_code == 404:
                return ("notfound", resp)

            if resp.status_code in SERVER_ERROR_CODES:
                if server_try >= len(SERVER_ERROR_WAITS):
                    print(f"  ! HTTP {resp.status_code} persistent", end=" ")
                    return ("error", None)
                w = SERVER_ERROR_WAITS[server_try]
                server_try += 1
                print(f"  ! HTTP {resp.status_code} (AO3); retry in {w}s", end=" ")
                time.sleep(w)
                continue

            if resp.status_code == 200:
                if "/users/login" in resp.url:
                    return ("restricted", resp)
                return ("ok", resp)

            print(f"  ! HTTP {resp.status_code}", end=" ")
            return ("error", None)


SORT_COLUMN_KEY = "work_search[sort_column]"
SORT_DIRECTION_KEY = "work_search[sort_direction]"


def build_listing_url(page, stable_sort=True):
    """Force view_adult=true, set page=N, keep any filters already in TAG_URL.

    By default we also pin the sort to 'Date Posted, ascending'.

    This matters more than it looks. AO3's default listing sort is
    revised_at desc - so the moment anyone updates any fic in the tag, every
    fic below it shifts down a slot. Mid-crawl, a fic can move from page 8 to
    page 9 *after* you've read page 9, and you never see it. Sorting by
    created_at ascending (tie-broken by id, per work_query.rb) is a stable
    total order: existing fics never move, and anything posted while you crawl
    is appended at the end, where you'll reach it normally.
    """
    parts = urlparse(TAG_URL)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in ("page", "view_adult")]
    has_sort = any(k == SORT_COLUMN_KEY for k, _ in query)
    if stable_sort and not has_sort:
        query.append((SORT_COLUMN_KEY, "created_at"))
        query.append((SORT_DIRECTION_KEY, "asc"))
    query.append(("view_adult", "true"))
    query.append(("page", str(page)))
    return urlunparse(parts._replace(query=urlencode(query)))


# ------------------------------------------------------------------ parsing

def _tags(node, selector):
    if node is None:
        return ""
    return MULTI_SEP.join(a.get_text(strip=True) for a in node.select(selector))


def _symbol_text(required, cls):
    span = required.select_one(f"span.{cls}") if required else None
    return span.get_text(" ", strip=True) if span else ""


def parse_listing_date(text, today):
    """AO3 renders revised_at as '15 Jan 2024', but as a relative phrase
    ('3 days', 'about 1 hour') when it's under 30 days old. Returns
    (iso_date, was_approximate)."""
    text = (text or "").strip()

    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$", text)
    if m and m.group(2).title() in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(2).title()],
                        int(m.group(1))).isoformat(), False
        except ValueError:
            pass

    rel = text.lower().replace(" ago", "").replace("about ", "").strip()
    if not rel:
        return "", False
    if rel.startswith("less than") or "minute" in rel or "hour" in rel:
        return today.isoformat(), True
    m = re.search(r"(\d+)\s+(day|month|year)", rel)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"day": 1, "month": 30, "year": 365}[unit]
        return (today - timedelta(days=days)).isoformat(), True
    return "", False


def _split_chapters(chapters):
    """'3/5' -> (3, '5'). Handles thousands separators and '?'."""
    if "/" not in chapters:
        return None, None
    posted_s, expected = chapters.split("/", 1)
    posted_s = posted_s.replace(",", "").strip()
    expected = expected.replace(",", "").strip()
    posted = int(posted_s) if posted_s.isdigit() else None
    return posted, expected


def parse_blurb(li, today):
    """Turn one <li class='work blurb'> into a metadata row.

    Selectors verified against otwarchive's _work_module.html.erb,
    blurb_tag_block and get_symbols_for.
    """
    wid = (li.get("id") or "").replace("work_", "")
    if not wid.isdigit():
        return None, False

    row = {k: "" for k in FIELDS}
    row["work_id"] = wid
    row["url"] = f"https://archiveofourown.org/works/{wid}"

    header = li.select_one("h4.heading")
    if header:
        title_link = header.find(
            "a", href=lambda h: h and re.search(r"/works/\d+", h))
        row["title"] = title_link.get_text(strip=True) if title_link else ""
        authors = header.select("a[rel=author]")
        row["author"] = (MULTI_SEP.join(a.get_text(strip=True) for a in authors)
                         if authors else "Anonymous")

    row["fandoms"] = _tags(li.select_one("h5.fandoms"), "a.tag")

    required = li.select_one("ul.required-tags")
    if required:
        row["rating"] = _symbol_text(required, "rating")
        categories = _symbol_text(required, "category")
        # get_symbols_for writes "No category" when there are none; the fic page
        # simply omits the field, so match that with an empty cell.
        if categories and categories != "No category":
            row["categories"] = MULTI_SEP.join(
                c.strip() for c in categories.split(",") if c.strip())

    # Each tag is its own <li>, so these are already cleanly separated.
    row["archive_warnings"] = _tags(li, "ul.tags li.warnings a.tag")
    if not row["archive_warnings"] and required:
        row["archive_warnings"] = _symbol_text(required, "warnings")
    row["relationships"] = _tags(li, "ul.tags li.relationships a.tag")
    row["characters"] = _tags(li, "ul.tags li.characters a.tag")
    row["additional_tags"] = _tags(li, "ul.tags li.freeforms a.tag")

    stats = li.select_one("dl.stats")
    if stats:
        def stat(cls):
            dd = stats.select_one(f"dd.{cls}")
            return dd.get_text(strip=True) if dd else ""
        row["language"] = stat("language")
        row["words"] = stat("words")
        row["chapters"] = stat("chapters")
        # AO3 omits these entirely when zero - the fic page does too, so the
        # old Phase 2 also produced an empty cell here. Keep that behaviour.
        row["comments"] = stat("comments")
        row["kudos"] = stat("kudos")
        row["bookmarks"] = stat("bookmarks")
        row["hits"] = stat("hits")

    dt = li.select_one("p.datetime")
    revised, approximate = parse_listing_date(
        dt.get_text(strip=True) if dt else "", today)

    # work_meta_list only emits the Updated/Completed row when
    # expected_number_of_chapters != 1, and the chapter display is
    # "posted/expected" - so both fields are derivable from the blurb.
    posted, expected = _split_chapters(row["chapters"])
    if expected == "1":
        row["status_label"] = ""
        row["status_date"] = ""
    elif expected is not None:
        row["status_label"] = "Completed" if str(posted) == expected else "Updated"
        row["status_date"] = revised

    # published = first chapter's date. With one posted chapter that is exactly
    # revised_at; otherwise it needs the fic page (--fill-published).
    if posted == 1:
        row["published"] = revised

    return row, approximate


def parse_listing(html, today):
    """Returns (rows, approx_count, has_next_page)."""
    soup = BeautifulSoup(html, PARSER)
    rows, approx = [], 0
    for li in soup.select("li.work.blurb"):
        row, was_approx = parse_blurb(li, today)
        if row:
            rows.append(row)
            approx += 1 if was_approx else 0
    has_next = soup.select_one("li.next a") is not None
    return rows, approx, has_next


def parse_work_page(work_id, html):
    """Full parse of a single fic page - used by --fill-published and --verify.
    Mirrors the old Phase 2 exactly."""
    soup = BeautifulSoup(html, PARSER)
    row = {k: "" for k in FIELDS}
    row["work_id"] = work_id
    row["url"] = f"https://archiveofourown.org/works/{work_id}"

    title = soup.select_one("h2.title.heading")
    row["title"] = title.get_text(strip=True) if title else ""

    byline = soup.select_one("h3.byline.heading")
    if byline:
        authors = byline.select("a[rel=author]")
        row["author"] = (MULTI_SEP.join(a.get_text(strip=True) for a in authors)
                         if authors else (byline.get_text(strip=True) or "Anonymous"))

    meta = soup.select_one("dl.work.meta.group")
    if meta:
        for field, sel in (("rating", "dd.rating.tags"),
                           ("archive_warnings", "dd.warning.tags"),
                           ("categories", "dd.category.tags"),
                           ("fandoms", "dd.fandom.tags"),
                           ("relationships", "dd.relationship.tags"),
                           ("characters", "dd.character.tags"),
                           ("additional_tags", "dd.freeform.tags")):
            row[field] = _tags(meta.select_one(sel), "a.tag")

        lang = meta.select_one("dd.language")
        row["language"] = lang.get_text(strip=True) if lang else ""

        stats = meta.select_one("dd.stats dl.stats") or meta.select_one("dl.stats")
        if stats:
            def stat(cls):
                dd = stats.select_one(f"dd.{cls}")
                return dd.get_text(strip=True) if dd else ""
            row["published"] = stat("published")
            status_dt = stats.select_one("dt.status")
            row["status_label"] = status_dt.get_text(strip=True).rstrip(":") if status_dt else ""
            row["status_date"] = stat("status")
            for f in ("words", "chapters", "comments", "kudos", "bookmarks", "hits"):
                row[f] = stat(f)
    return row


# ------------------------------------------------------------------- storage

def load_done_ids():
    done = set()
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("work_id"):
                    done.add(r["work_id"].strip())
    return done


def load_progress():
    """Returns the next page to fetch, or None if the last run finished."""
    if os.path.exists(PROGRESS_FILE):
        raw = open(PROGRESS_FILE).read().strip()
        if raw == "done":
            return None
        try:
            return int(raw) + 1
        except ValueError:
            pass
    return 1


def save_progress(page):
    with open(PROGRESS_FILE, "w") as f:
        f.write(str(page))


# --------------------------------------------------------------------- modes

def run_scrape(fetcher):
    start = load_progress()
    if start is None:
        print(f"{OUTPUT_CSV} is already complete for this tag.\n"
              f"  - to pull in new/updated fics:  --update\n"
              f"  - to fill exact publish dates:  --fill-published\n"
              f"  - to scrape from scratch:       delete {PROGRESS_FILE}")
        return

    seen = load_done_ids()
    today = date.today()
    exists = os.path.exists(OUTPUT_CSV)

    out_f = open(OUTPUT_CSV, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=FIELDS)
    if not exists:
        writer.writeheader()

    print(f"Scraping listing pages (~20 fics each), starting at page {start}.")
    print(f"Already saved: {len(seen)} fics -> {OUTPUT_CSV}")
    print(f"Parser: {PARSER} | budget: {MAX_REQUESTS_PER_WINDOW} req / "
          f"{WINDOW_SECONDS}s (AO3 allows 300)\n")

    added_total = approx_total = 0
    consecutive_errors = 0
    stale_pages = 0
    completed = False
    t0 = time.monotonic()

    try:
        page = start
        while page <= MAX_PAGE_SAFETY_LIMIT:
            print(f"page {page}...", end=" ", flush=True)
            kind, resp = fetcher.get(build_listing_url(page))

            if kind != "ok":
                consecutive_errors += 1
                print("failed -> will retry on next run.")
                if consecutive_errors >= OUTAGE_THRESHOLD:
                    print("\nToo many failures in a row; AO3 looks down. "
                          "Rerun later to resume.")
                    break
                page += 1 if kind == "notfound" else 0
                if kind != "notfound":
                    time.sleep(10)
                continue
            consecutive_errors = 0

            rows, approx, has_next = parse_listing(resp.text, today)
            if not rows:
                print("no fics -> end of listing.")
                completed = True
                break

            added = 0
            for row in rows:
                if row["work_id"] not in seen:
                    writer.writerow(row)
                    seen.add(row["work_id"])
                    added += 1
            out_f.flush()
            save_progress(page)
            added_total += added
            approx_total += approx
            print(f"{len(rows)} fics ({added} new; {len(seen)} total).")

            if not has_next:
                print("last page reached -> done.")
                completed = True
                break

            # Every fic on a full page was already on file. Either AO3 has
            # clamped us at its paging ceiling and is re-serving the same page,
            # or we're re-reading ground we covered. Either way, going further
            # costs requests and returns nothing.
            stale_pages = stale_pages + 1 if added == 0 else 0
            if stale_pages >= CLAMP_REPEAT_LIMIT:
                print(f"\n{stale_pages} pages in a row with nothing new - AO3 "
                      f"has stopped paginating (its deep-paging ceiling).\n"
                      f"Everything up to here is saved. To get the rest, split "
                      f"TAG_URL by date range, e.g. add\n"
                      f"  &work_search[date_from]=2020-01-01"
                      f"&work_search[date_to]=2020-12-31\n"
                      f"and rerun with a different PROJECT_NAME per slice.")
                break
            page += 1
        else:
            print(f"\nStopped at the {MAX_PAGE_SAFETY_LIMIT}-page safety limit.")
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun the same command to resume.")
    finally:
        out_f.close()
        if completed:
            with open(PROGRESS_FILE, "w") as f:
                f.write("done")

    mins = (time.monotonic() - t0) / 60
    print(f"\nDone in {mins:.1f} min. New fics this run: {added_total}. "
          f"Total: {len(seen)}.")
    if approx_total:
        print(f"{approx_total} fics were updated in the last 30 days, so AO3 "
              f"showed a relative date ('3 days'); those dates are "
              f"day-accurate but derived. --fill-published makes them exact.")
    missing = sum(1 for r in read_rows() if not r.get("published"))
    if missing:
        print(f"{missing} multi-chapter fics have no 'published' date yet. "
              f"Run: python3 {os.path.basename(__file__)} --fill-published")


def read_rows():
    if not os.path.exists(OUTPUT_CSV):
        return []
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_update(fetcher, quiet_pages=3):
    """Top up an existing CSV with new and recently-updated fics.

    Uses AO3's default sort (most recently updated first) and walks from page 1
    until it sees `quiet_pages` pages in a row with nothing new or changed.
    Cheap: for a tag that gained a handful of fics this is 3-4 requests.
    """
    rows = read_rows()
    if not rows:
        print(f"No {OUTPUT_CSV} yet - run the main scrape first.")
        return

    by_id = {r["work_id"]: r for r in rows}
    today = date.today()
    # Fields that move when a fic is updated; used to spot changed rows.
    watched = ("status_date", "words", "chapters", "kudos", "comments",
               "bookmarks", "hits", "title", "relationships", "characters",
               "additional_tags")

    print(f"Update mode: {len(rows)} fics on file. Walking newest-updated "
          f"first, stopping after {quiet_pages} quiet pages.\n")

    new_count = changed_count = 0
    quiet = 0
    page = 1
    try:
        while page <= MAX_PAGE_SAFETY_LIMIT and quiet < quiet_pages:
            print(f"page {page}...", end=" ", flush=True)
            kind, resp = fetcher.get(build_listing_url(page, stable_sort=False))
            if kind != "ok":
                print("failed -> stopping; rerun to try again.")
                break

            parsed, _, has_next = parse_listing(resp.text, today)
            if not parsed:
                print("no fics -> done.")
                break

            added = changed = 0
            for row in parsed:
                wid = row["work_id"]
                old = by_id.get(wid)
                if old is None:
                    by_id[wid] = row
                    rows.append(row)
                    added += 1
                elif any((old.get(f) or "") != (row.get(f) or "") for f in watched):
                    # Keep a publish date we already paid a request for.
                    if old.get("published") and not row.get("published"):
                        row["published"] = old["published"]
                    old.update(row)
                    changed += 1

            new_count += added
            changed_count += changed
            quiet = quiet + 1 if (added == 0 and changed == 0) else 0
            print(f"{len(parsed)} fics ({added} new, {changed} updated).")

            if not has_next:
                print("last page reached -> done.")
                break
            page += 1
    except KeyboardInterrupt:
        print("\nInterrupted; saving what we have.")
    finally:
        write_rows(rows)

    print(f"\nUpdate finished. New: {new_count} | refreshed: {changed_count} | "
          f"total: {len(rows)}")


def run_fill_published(fetcher):
    rows = read_rows()
    if not rows:
        print(f"No {OUTPUT_CSV} yet - run the main scrape first.")
        return

    pending = [r for r in rows if not r.get("published")]
    print(f"{len(rows)} fics total; {len(pending)} need an exact publish date "
          f"(the rest are single-chapter, already exact).\n")
    if not pending:
        return

    by_id = {r["work_id"]: r for r in rows}
    filled = failed = 0
    consecutive_errors = 0

    try:
        for i, r in enumerate(pending, 1):
            wid = r["work_id"]
            print(f"[{i}/{len(pending)}] fic {wid}...", end=" ", flush=True)
            kind, resp = fetcher.get(
                f"https://archiveofourown.org/works/{wid}?view_adult=true")
            if kind != "ok":
                failed += 1
                consecutive_errors += 1
                print("failed -> stays pending.")
                if consecutive_errors >= OUTAGE_THRESHOLD:
                    print("\nAO3 looks down; stopping. Rerun to resume.")
                    break
                continue
            consecutive_errors = 0
            full = parse_work_page(wid, resp.text)
            if full["published"]:
                by_id[wid]["published"] = full["published"]
                # The fic page is authoritative for these two as well.
                by_id[wid]["status_label"] = full["status_label"]
                by_id[wid]["status_date"] = full["status_date"]
                filled += 1
                print("ok.")
            else:
                failed += 1
                print("no date found.")
            if i % 25 == 0:
                write_rows(rows)
    except KeyboardInterrupt:
        print("\nInterrupted; saving what we have.")
    finally:
        write_rows(rows)

    print(f"\nFilled: {filled} | still pending: {failed}")


def write_rows(rows):
    tmp = OUTPUT_CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    os.replace(tmp, OUTPUT_CSV)


def run_verify(fetcher, sample_size):
    """Fetch a random sample of fic pages and diff them against what we parsed
    from the listing. This is how you prove the fast path is correct."""
    import random

    rows = read_rows()
    if not rows:
        print(f"No {OUTPUT_CSV} yet - run the main scrape first.")
        return

    sample = random.sample(rows, min(sample_size, len(rows)))
    # 'published' is expected to differ for multi-chapter fics until
    # --fill-published has run, so don't count it as a mismatch there.
    mismatches = 0
    checked = 0

    for i, r in enumerate(sample, 1):
        wid = r["work_id"]
        print(f"[{i}/{len(sample)}] verifying {wid}...", end=" ", flush=True)
        kind, resp = fetcher.get(
            f"https://archiveofourown.org/works/{wid}?view_adult=true")
        if kind != "ok":
            print(f"skipped ({kind}).")
            continue
        truth = parse_work_page(wid, resp.text)
        checked += 1
        diffs = []
        for field in FIELDS:
            if field == "published" and not r.get("published"):
                continue
            if field == "hits":
                continue  # hits move between the two requests
            got, want = (r.get(field) or "").strip(), (truth.get(field) or "").strip()
            if got != want:
                diffs.append(f"    {field}:\n      listing: {got!r}\n      fic page: {want!r}")
        if diffs:
            mismatches += 1
            print("MISMATCH")
            print("\n".join(diffs))
        else:
            print("match.")

    print(f"\nVerified {checked} fics: {checked - mismatches} exact, "
          f"{mismatches} with differences.")
    if not mismatches and checked:
        print("The listing-only data matches the fic pages field for field.")


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Fast AO3 tag scraper.")
    ap.add_argument("--fill-published", action="store_true",
                    help="visit only multi-chapter fics to get exact publish dates")
    ap.add_argument("--update", action="store_true",
                    help="top up an existing CSV with new/recently-updated fics")
    ap.add_argument("--verify", type=int, metavar="N",
                    help="spot-check N scraped fics against their real fic pages")
    ap.add_argument("--tag-url", help="override TAG_URL")
    ap.add_argument("--project", help="override PROJECT_NAME")
    ap.add_argument("--email", help="override CONTACT_EMAIL")
    ap.add_argument("--delay", type=float,
                    help="min seconds between requests (default 1.5)")
    args = ap.parse_args()

    global TAG_URL, PROJECT_NAME, CONTACT_EMAIL, OUTPUT_CSV, PROGRESS_FILE
    global USER_AGENT, MIN_SECONDS_BETWEEN_REQUESTS
    if args.tag_url:
        TAG_URL = args.tag_url
    if args.project:
        PROJECT_NAME = args.project
    if args.email:
        CONTACT_EMAIL = args.email
    if args.delay:
        MIN_SECONDS_BETWEEN_REQUESTS = args.delay
    OUTPUT_CSV = f"{PROJECT_NAME}_metadata.csv"
    PROGRESS_FILE = f"{PROJECT_NAME}_progress.txt"
    USER_AGENT = f"AO3 metadata (personal research) - contact: {CONTACT_EMAIL}"

    if CONTACT_EMAIL == "your_email@example.com":
        print("Set CONTACT_EMAIL (in the EDIT THESE block, or --email) first.")
        return 1
    if "YOUR_TAG_HERE" in TAG_URL and not (args.fill_published or args.verify):
        print("Set TAG_URL (in the EDIT THESE block, or --tag-url) first.")
        return 1

    limiter = RateLimiter(MAX_REQUESTS_PER_WINDOW, WINDOW_SECONDS,
                          MIN_SECONDS_BETWEEN_REQUESTS)
    fetcher = Fetcher(limiter)

    if args.verify:
        run_verify(fetcher, args.verify)
    elif args.fill_published:
        run_fill_published(fetcher)
    elif args.update:
        run_update(fetcher)
    else:
        run_scrape(fetcher)
    return 0


if __name__ == "__main__":
    sys.exit(main())
