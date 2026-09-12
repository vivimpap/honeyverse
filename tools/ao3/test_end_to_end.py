#!/usr/bin/env python3
"""End-to-end: a plain run must leave `published` complete for EVERY row.

This is the regression that mattered: the listing pass alone fills the date
only for single-chapter fics, so a plain run used to hand back a CSV that was
~25% empty in that column unless you knew to run a second command.

Run: python3 test_end_to_end.py
"""
import csv, os, sys, tempfile, types
import ao3_fast as A

A.DELAY_MIN = A.DELAY_MAX = 0
A.LONG_REST_EVERY = 0

def blurb(wid, chapters, datetime_text="15 Jan 2024"):
    return f'''<li id="work_{wid}" class="work blurb group">
 <div class="header module">
  <h4 class="heading"><a href="/works/{wid}">Fic {wid}</a> by <a rel="author" href="/u/a">a</a></h4>
  <h5 class="fandoms heading"><a class="tag" href="/t">P1Harmony (Band)</a></h5>
  <ul class="required-tags">
   <li><span class="rating-teen rating"><span class="text">Teen And Up Audiences</span></span></li>
   <li><span class="category-gen category"><span class="text">M/M</span></span></li>
  </ul>
  <p class="datetime">{datetime_text}</p></div>
 <ul class="tags commas"><li class='relationships'><a class="tag" href="/t">Choi Jiung/Yoon Keeho</a></li></ul>
 <dl class="stats"><dt class="words">Words:</dt><dd class="words">1,000</dd>
  <dt class="chapters">Chapters:</dt><dd class="chapters">{chapters}</dd>
  <dt class="hits">Hits:</dt><dd class="hits">10</dd></dl></li>'''

def navigate_page(first_date):
    return (f'<ol class="chapter index group">'
            f'<li><a href="/works/1/chapters/1">Chapter 1</a> '
            f'<span class="datetime">({first_date})</span></li>'
            f'<li><a href="/works/1/chapters/2">Chapter 2</a> '
            f'<span class="datetime">(2024-01-15)</span></li></ol>')

def work_page(published):
    return f'''<h2 class="title heading">Fic</h2>
 <dl class="work meta group"><dd class="stats"><dl class="stats">
  <dt class="published">Published:</dt><dd class="published">{published}</dd>
  <dt class="status">Updated:</dt><dd class="status">2024-01-15</dd>
  <dt class="words">Words:</dt><dd class="words">1,000</dd>
 </dl></dd></dl>'''

# 6 one-shots + 4 multichapter, mirroring the real ratio.
ONESHOTS = [10, 11, 12, 13, 14, 15]
MULTI = {20: "2/?", 21: "4/4", 22: "3/?", 23: "5/5"}
PAGE1 = "<ol>" + "".join(blurb(w, "1/1") for w in ONESHOTS) + \
        "".join(blurb(w, c) for w, c in MULTI.items()) + "</ol>"

listing_hits, work_hits = [], []
class FakeAO3:
    last_elapsed = 0.0
    last_bytes = 0
    def __init__(self, limiter): pass
    def get(self, url):
        if "/tags/" in url:
            listing_hits.append(url)
            page = int(url.rsplit("page=", 1)[1])
            html = PAGE1 if page == 1 else "<ol></ol>"
            return ("ok", types.SimpleNamespace(text=html, url=url, status_code=200))
        work_hits.append(url)
        wid = int(url.split("/works/")[1].split("?")[0].split("/")[0])
        body = (navigate_page(f"20{wid % 100:02d}-06-09") if "/navigate" in url
                else work_page(f"20{wid % 100:02d}-06-09"))
        return ("ok", types.SimpleNamespace(text=body, url=url, status_code=200))

A.Fetcher = FakeAO3
tmp = tempfile.mkdtemp(); os.chdir(tmp)
out = os.path.join(tmp, "keeung_metadata.csv")

sys.argv = ["ao3_fast.py", "--email", "me@example.com", "--project", "keeung",
            "--tag-url", "https://archiveofourown.org/tags/Test/works",
            "--csv", out]
A.main()

rows = list(csv.DictReader(open(out, encoding="utf-8")))
failures = []
def check(label, got, want):
    if got != want: failures.append(f"{label}\n    got:  {got!r}\n    want: {want!r}")

check("row count", len(rows), 10)
empty = [r["work_id"] for r in rows if not (r["published"] or "").strip()]
check("NO row left without a publish date", empty, [])

by_id = {r["work_id"]: r for r in rows}
# one-shots: filled from the listing, no fic-page request spent on them
check("one-shot date from listing", by_id["10"]["published"], "2024-01-15")
check("one-shot pages never fetched",
      [u for u in work_hits if any(f"/works/{w}?" in u for w in ONESHOTS)], [])
# multichapter: filled from the fic page
check("multichapter date from fic page", by_id["20"]["published"], "2020-06-09")
check("only multichapter fetched", sorted(
    u.split("/works/")[1].split("?")[0].split("/")[0] for u in work_hits),
    sorted(str(w) for w in MULTI))
check("uses the light chapter index, not the full work page",
      all("/navigate" in u for u in work_hits), True)
# listing-derived fields survive the fill pass untouched
check("status_label kept", by_id["20"]["status_label"], "Updated")
check("relationships kept", by_id["20"]["relationships"], "Choi Jiung/Yoon Keeho")
check("column order kept", list(by_id["20"].keys()), A.FIELDS)

# --no-fill-published must stop after the listing pass
os.remove(out); os.remove("keeung_progress.txt")
work_hits.clear()
sys.argv.append("--no-fill-published")
A.main()
rows2 = list(csv.DictReader(open(out, encoding="utf-8")))
empty2 = [r["work_id"] for r in rows2 if not (r["published"] or "").strip()]
check("--no-fill-published leaves multichapter empty", sorted(empty2),
      sorted(str(w) for w in MULTI))
check("--no-fill-published spends no fic-page requests", work_hits, [])

if failures:
    print(f"\nFAILED ({len(failures)}):\n"); print("\n\n".join(failures)); sys.exit(1)
print("\nAll end-to-end checks passed.")
