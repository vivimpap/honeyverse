#!/usr/bin/env python3
"""Tests for --fill-published against a fake AO3 that never touches the network.

Run: python3 test_fill_published.py
"""
import csv, os, sys, tempfile, types
import ao3_fast as A

A.DELAY_MIN = A.DELAY_MAX = 0
A.LONG_REST_EVERY = 0

def work_page(published="2019-03-14", status="Updated", sdate="2024-01-15"):
    status_html = (f'<dt class="status">{status}:</dt>'
                   f'<dd class="status">{sdate}</dd>') if status else ""
    return f'''<html><body>
 <h2 class="title heading">Some Longfic</h2>
 <dl class="work meta group">
   <dd class="stats"><dl class="stats">
     <dt class="published">Published:</dt><dd class="published">{published}</dd>
     {status_html}
     <dt class="words">Words:</dt><dd class="words">12,345</dd>
     <dt class="chapters">Chapters:</dt><dd class="chapters">3/?</dd>
     <dt class="hits">Hits:</dt><dd class="hits">900</dd>
   </dl></dd>
 </dl></body></html>'''

def navigate_page(dates):
    """The chapter index: what AO3 serves at /works/<id>/navigate."""
    items = "".join(
        f'<li><a href="/works/1/chapters/{i}">Chapter {i+1}</a> '
        f'<span class="datetime">({d})</span></li>'
        for i, d in enumerate(dates))
    return f'<h2 class="heading">Fic</h2><ol class="chapter index group" role="navigation">{items}</ol>'


failures = []
def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n    got:  {got!r}\n    want: {want!r}")

# A CSV shaped like the user's: extra columns the scraper never produced,
# in a non-FIELDS order, plus a one-shot that already has its date.
HEADER = ["work_id", "url", "title", "published", "status_label", "status_date",
          "chapters", "mi_nota", "leido"]
SEED = [
    # already filled -> must NOT be refetched or altered
    ["100", "https://archiveofourown.org/works/100", "One shot", "2022-05-01",
     "", "", "1/1", "favorita", "si"],
    ["200", "https://archiveofourown.org/works/200", "Longfic A", "",
     "Updated", "2024-01-15", "3/?", "pendiente", "no"],
    ["300", "https://archiveofourown.org/works/300", "Longfic B", "",
     "Completed", "2023-11-02", "12/12", "", "si"],
    # restricted -> permanent skip
    ["400", "https://archiveofourown.org/works/400", "Locked", "",
     "Updated", "2024-02-02", "5/?", "", "no"],
    # transient error -> must stay pending
    ["500", "https://archiveofourown.org/works/500", "Flaky", "",
     "Updated", "2024-03-03", "2/2", "", "no"],
]

tmpdir = tempfile.mkdtemp()
path = os.path.join(tmpdir, "nct_copia.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(HEADER); w.writerows(SEED)

requested = []
WORK_PAGE_HITS = []

class FakeAO3:
    last_elapsed = 0.0
    last_bytes = 0
    def get(self, url):
        requested.append(url)
        if "/400" in url:
            return ("restricted", None)
        if "/500" in url:
            return ("error", None)
        if url.endswith("/navigate?view_adult=true"):
            # chapter 1 first, then later chapters
            body = navigate_page(["2019-03-14", "2021-07-01", "2024-01-15"])
        else:
            WORK_PAGE_HITS.append(url)
            body = work_page()
        return ("ok", types.SimpleNamespace(text=body, url=url, status_code=200))


def work_id_of(url):
    return url.split("/works/")[1].split("?")[0].split("/")[0]

# ---------- test mode must not write ----------
before = open(path, encoding="utf-8").read()
A.run_fill_published(FakeAO3(), csv_path=path, test_n=2)
check("test mode leaves file untouched", open(path, encoding="utf-8").read(), before)
check("test mode fetched only 2", len(requested), 2)

# ---------- full pass ----------
requested.clear()
A.run_fill_published(FakeAO3(), csv_path=path, save_every=2)

with open(path, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    out = {r["work_id"]: r for r in reader}
    header_after = reader.fieldnames

# columns
check("header preserved exactly", header_after, HEADER)

# the already-filled row is untouched and was never requested
check("one-shot date untouched", out["100"]["published"], "2022-05-01")
check("one-shot not refetched", any("/100" in u for u in requested), False)

# filled rows
check("200 published filled", out["200"]["published"], "2019-03-14")
check("300 published filled", out["300"]["published"], "2019-03-14")

# only `published` changed: status pair and custom columns survive verbatim
check("200 status_label untouched", out["200"]["status_label"], "Updated")
check("200 status_date untouched", out["200"]["status_date"], "2024-01-15")
check("200 custom col untouched", out["200"]["mi_nota"], "pendiente")
check("300 custom col untouched", out["300"]["leido"], "si")
check("100 custom col untouched", out["100"]["mi_nota"], "favorita")

# restricted -> stays empty (permanent), error -> stays empty (retryable)
check("restricted stays empty", out["400"]["published"], "")
check("errored stays empty", out["500"]["published"], "")

# backup written before the first in-place rewrite
check("backup exists", os.path.exists(path + ".bak"), True)
with open(path + ".bak", newline="", encoding="utf-8") as f:
    bak = {r["work_id"]: r for r in csv.DictReader(f)}
check("backup holds pre-run state", bak["200"]["published"], "")

# ---------- resume: rerun must only retry what's still empty ----------
requested.clear()
A.run_fill_published(FakeAO3(), csv_path=path, save_every=2)
check("resume refetches only 400 and 500",
      sorted(work_id_of(u) for u in requested), ["400", "500"])

# the whole point of this change: the heavy work page is never touched
check("never downloads the full work page", WORK_PAGE_HITS, [])
check("asks for the chapter index instead",
      all(u.endswith("/navigate?view_adult=true") for u in requested), True)

# ---------- view_adult is forced onto the row's own url ----------
u = A.fic_url({"url": "https://archiveofourown.org/works/999"})
check("view_adult appended", u, "https://archiveofourown.org/works/999?view_adult=true")
u2 = A.fic_url({"url": "https://archiveofourown.org/works/999?view_adult=false"})
check("view_adult not duplicated", u2, "https://archiveofourown.org/works/999?view_adult=true")
u3 = A.fic_url({"work_id": "777", "url": ""})
check("falls back to work_id", u3, "https://archiveofourown.org/works/777?view_adult=true")

# ---------- navigate URL building ----------
check("navigate url from url column",
      A.navigate_url({"url": "https://archiveofourown.org/works/123"}),
      "https://archiveofourown.org/works/123/navigate?view_adult=true")
check("navigate url from work_id",
      A.navigate_url({"work_id": "123", "url": ""}),
      "https://archiveofourown.org/works/123/navigate?view_adult=true")
check("navigate url not doubled",
      A.navigate_url({"url": "https://archiveofourown.org/works/123/navigate"}),
      "https://archiveofourown.org/works/123/navigate?view_adult=true")

# ---------- chapter index: first entry is the publication date ----------
check("published = chapter 1's date",
      A.extract_published_from_navigate(
          navigate_page(["2019-03-14", "2021-07-01", "2024-01-15"])),
      "2019-03-14")
check("single chapter index",
      A.extract_published_from_navigate(navigate_page(["2020-02-02"])), "2020-02-02")
check("not a chapter index -> empty (triggers fallback)",
      A.extract_published_from_navigate(work_page()), "")

# ---------- fallback: unusable navigate page -> work page ----------
class NavBroken(FakeAO3):
    def get(self, url):
        requested.append(url)
        if url.endswith("/navigate?view_adult=true"):
            return ("ok", types.SimpleNamespace(text="<p>nope</p>", url=url, status_code=200))
        return ("ok", types.SimpleNamespace(text=work_page("2001-09-11"), url=url, status_code=200))

fb = os.path.join(tmpdir, "fallback.csv")
with open(fb, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(HEADER)
    w.writerow(["900", "https://archiveofourown.org/works/900", "X", "",
                "Updated", "2024-01-01", "3/?", "", ""])
requested.clear()
A.run_fill_published(NavBroken(), csv_path=fb)
with open(fb, newline="", encoding="utf-8") as f:
    got = list(csv.DictReader(f))[0]["published"]
check("falls back to the work page", got, "2001-09-11")
check("fallback cost 2 requests", len(requested), 2)

# ---------- selector: dd.published, not dd.status ----------
pub, label, sdate, _ = A.extract_published(work_page("2015-01-01", "Completed", "2020-12-31"))
check("published from dd.published", pub, "2015-01-01")
check("status label read separately", label, "Completed")
check("status date read separately", sdate, "2020-12-31")

if failures:
    print(f"\nFAILED ({len(failures)}):\n"); print("\n\n".join(failures)); sys.exit(1)
print("\nAll fill-published checks passed.")
