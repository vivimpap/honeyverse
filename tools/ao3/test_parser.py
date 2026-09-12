#!/usr/bin/env python3
"""Parser tests against HTML built to match otwarchive's own templates
(_work_module.html.erb, blurb_tag_block, get_symbols_for).

Run: python3 test_parser.py
"""
import sys
from datetime import date, timedelta

import ao3_fast
from ao3_fast import parse_listing, parse_listing_date

TODAY = date(2026, 9, 12)


def symbol(cls, title):
    return (f'<li><a class="help symbol question modal" href="/help/symbols-key">'
            f'<span class="{cls}" title="{title}"><span class="text">{title}</span>'
            f'</span></a></li>')


def blurb(wid, title, authors, fandoms, rating, warn_sym, category, wip_sym,
          datetime_text, warnings, rels, chars, freeforms, stats):
    author_html = ", ".join(
        f'<a rel="author" href="/users/{a}/pseuds/{a}">{a}</a>' for a in authors) \
        if authors else "Anonymous"
    tag_lis = []
    tag_lis += [f"<li class='warnings'><strong><a class=\"tag\" href=\"/t\">{w}</a></strong></li>" for w in warnings]
    tag_lis += [f"<li class='relationships'><a class=\"tag\" href=\"/t\">{r}</a></li>" for r in rels]
    tag_lis += [f"<li class='characters'><a class=\"tag\" href=\"/t\">{c}</a></li>" for c in chars]
    tag_lis += [f"<li class='freeforms'><a class=\"tag\" href=\"/t\">{f}</a></li>" for f in freeforms]
    return f'''
<li id="work_{wid}" class="work blurb group" role="article">
  <div class="header module">
    <h4 class="heading">
      <a href="/works/{wid}">{title}</a> by {author_html}
    </h4>
    <h5 class="fandoms heading">
      <span class="landmark">Fandoms:</span>
      {" ".join(f'<a class="tag" href="/tags/x/works">{f}</a>' for f in fandoms)}
      &nbsp;
    </h5>
    <ul class="required-tags">
      {symbol("rating-teen rating", rating)}
      {symbol("warning-no warnings", warn_sym)}
      {symbol("category-multi category", category)}
      {symbol(wip_sym[0], wip_sym[1])}
    </ul>
    <p class="datetime">{datetime_text}</p>
  </div>
  <h6 class="landmark heading">Tags</h6>
  <ul class="tags commas">{"".join(tag_lis)}</ul>
  <blockquote class="userstuff summary"><p>A summary.</p></blockquote>
  <dl class="stats">{stats}</dl>
</li>'''


# --- Case 1: multi-chapter WIP, two authors, pipes inside relationship tags ---
CASE1 = blurb(
    wid="12345678", title="The Time It Rained", authors=["vivi", "friend"],
    fandoms=["P1Harmony (Band)"], rating="Teen And Up Audiences",
    warn_sym="No Archive Warnings Apply", category="M/M, Gen",
    wip_sym=("complete-no iswip", "Work in Progress"),
    datetime_text="15 Jan 2024",
    warnings=["No Archive Warnings Apply"],
    rels=["Choi Taeyang | Theo/Park Jongseob", "Yoon Keeho/Kim Jiung | Jiung"],
    chars=["Choi Taeyang | Theo", "Yoon Keeho"],
    freeforms=["Angst", "Slow Burn"],
    stats='''<dt class="language">Language:</dt><dd class="language" lang="en">English</dd>
      <dt class="words">Words:</dt><dd class="words">12,345</dd>
      <dt class="chapters">Chapters:</dt><dd class="chapters"><a href="/works/1/chapters/9">3</a>/?</dd>
      <dt class="comments">Comments:</dt><dd class="comments">42</dd>
      <dt class="kudos">Kudos:</dt><dd class="kudos">500</dd>
      <dt class="bookmarks">Bookmarks:</dt><dd class="bookmarks"><a href="/b">30</a></dd>
      <dt class="hits">Hits:</dt><dd class="hits">9,001</dd>''')

# --- Case 2: one-shot, anonymous, no category, zero kudos/comments/bookmarks ---
CASE2 = blurb(
    wid="99999", title="A One Shot", authors=[],
    fandoms=["P1Harmony (Band)"], rating="General Audiences",
    warn_sym="No Archive Warnings Apply", category="No category",
    wip_sym=("complete-yes iswip", "Complete Work"),
    datetime_text="02 Mar 2023",
    warnings=["No Archive Warnings Apply"], rels=[], chars=["Shota"],
    freeforms=["Fluff"],
    stats='''<dt class="language">Language:</dt><dd class="language" lang="en">English</dd>
      <dt class="words">Words:</dt><dd class="words">800</dd>
      <dt class="chapters">Chapters:</dt><dd class="chapters">1/1</dd>
      <dt class="hits">Hits:</dt><dd class="hits">120</dd>''')

# --- Case 3: completed multi-chapter, relative (recent) date ---
CASE3 = blurb(
    wid="555", title="Finished Longfic", authors=["someone"],
    fandoms=["P1Harmony (Band)", "K-pop"], rating="Explicit",
    warn_sym="Graphic Depictions Of Violence", category="M/M",
    wip_sym=("complete-yes iswip", "Complete Work"),
    datetime_text="3 days",
    warnings=["Graphic Depictions Of Violence", "Major Character Death"],
    rels=["Keeho/Jiung"], chars=["Intak"], freeforms=["Hurt/Comfort"],
    stats='''<dt class="language">Language:</dt><dd class="language" lang="en">English</dd>
      <dt class="words">Words:</dt><dd class="words">100,000</dd>
      <dt class="chapters">Chapters:</dt><dd class="chapters"><a href="/c">25</a>/25</dd>
      <dt class="kudos">Kudos:</dt><dd class="kudos">3,000</dd>
      <dt class="hits">Hits:</dt><dd class="hits">50,000</dd>''')

PAGE = f'''<html><body><ol class="work index group">{CASE1}{CASE2}{CASE3}</ol>
<ol class="pagination actions"><li class="next"><a href="?page=2">Next</a></li></ol>
</body></html>'''

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n    got:  {got!r}\n    want: {want!r}")


rows, approx, has_next = parse_listing(PAGE, TODAY)
check("row count", len(rows), 3)
check("has_next", has_next, True)
check("approx count", approx, 1)

r1, r2, r3 = rows

# ---- Case 1 -------------------------------------------------------------
check("1 work_id", r1["work_id"], "12345678")
check("1 url", r1["url"], "https://archiveofourown.org/works/12345678")
check("1 title", r1["title"], "The Time It Rained")
check("1 author", r1["author"], "vivi ; friend")
check("1 rating", r1["rating"], "Teen And Up Audiences")
check("1 warnings", r1["archive_warnings"], "No Archive Warnings Apply")
check("1 categories (comma -> ' ; ')", r1["categories"], "M/M ; Gen")
check("1 fandoms", r1["fandoms"], "P1Harmony (Band)")
# The whole point: '|' stays inside a tag, ';' only ever separates tags.
check("1 relationships", r1["relationships"],
      "Choi Taeyang | Theo/Park Jongseob ; Yoon Keeho/Kim Jiung | Jiung")
check("1 characters", r1["characters"], "Choi Taeyang | Theo ; Yoon Keeho")
check("1 additional_tags", r1["additional_tags"], "Angst ; Slow Burn")
check("1 language", r1["language"], "English")
check("1 words", r1["words"], "12,345")
check("1 chapters", r1["chapters"], "3/?")
check("1 comments", r1["comments"], "42")
check("1 kudos", r1["kudos"], "500")
check("1 bookmarks", r1["bookmarks"], "30")
check("1 hits", r1["hits"], "9,001")
check("1 status_label (expected '?' -> WIP)", r1["status_label"], "Updated")
check("1 status_date", r1["status_date"], "2024-01-15")
check("1 published (3 chapters -> needs top-up)", r1["published"], "")

# ---- Case 2: one-shot ---------------------------------------------------
check("2 author (anonymous)", r2["author"], "Anonymous")
check("2 categories ('No category' -> empty)", r2["categories"], "")
check("2 relationships (none)", r2["relationships"], "")
check("2 comments (omitted when 0)", r2["comments"], "")
check("2 kudos (omitted when 0)", r2["kudos"], "")
check("2 bookmarks (omitted when 0)", r2["bookmarks"], "")
# expected_number_of_chapters == 1 -> the fic page has no status row at all.
check("2 status_label (1/1 -> empty)", r2["status_label"], "")
check("2 status_date (1/1 -> empty)", r2["status_date"], "")
check("2 published (1 chapter == revised)", r2["published"], "2023-03-02")

# ---- Case 3: completed longfic, relative date ---------------------------
check("3 status_label (25/25 -> Completed)", r3["status_label"], "Completed")
check("3 status_date (relative resolved)", r3["status_date"],
      (TODAY - timedelta(days=3)).isoformat())
check("3 warnings (multiple)", r3["archive_warnings"],
      "Graphic Depictions Of Violence ; Major Character Death")
check("3 fandoms (multiple)", r3["fandoms"], "P1Harmony (Band) ; K-pop")
check("3 words with delimiter", r3["words"], "100,000")
check("3 chapters", r3["chapters"], "25/25")
check("3 published (multi-chapter)", r3["published"], "")

# ---- Date parsing -------------------------------------------------------
check("date absolute", parse_listing_date("15 Jan 2024", TODAY), ("2024-01-15", False))
check("date 1 digit day", parse_listing_date("2 Mar 2023", TODAY), ("2023-03-02", False))
check("date 'about 1 hour'", parse_listing_date("about 1 hour", TODAY),
      (TODAY.isoformat(), True))
check("date 'less than a minute'", parse_listing_date("less than a minute", TODAY),
      (TODAY.isoformat(), True))
check("date '22 minutes'", parse_listing_date("22 minutes", TODAY),
      (TODAY.isoformat(), True))
check("date '3 days ago'", parse_listing_date("3 days ago", TODAY),
      ((TODAY - timedelta(days=3)).isoformat(), True))
check("date 'about 1 month'", parse_listing_date("about 1 month", TODAY),
      ((TODAY - timedelta(days=30)).isoformat(), True))

# ---- No next page -> we stop ------------------------------------------
_, _, last_has_next = parse_listing(f"<ol>{CASE2}</ol>", TODAY)
check("last page has_next", last_has_next, False)

# ---- Column contract matches old Phase 2 ------------------------------
check("field list", ao3_fast.FIELDS, [
    "work_id", "url", "title", "author", "rating", "archive_warnings",
    "categories", "fandoms", "relationships", "characters", "additional_tags",
    "language", "published", "status_label", "status_date",
    "words", "chapters", "comments", "kudos", "bookmarks", "hits"])
check("separator", ao3_fast.MULTI_SEP, " ; ")

if failures:
    print(f"FAILED ({len(failures)}):\n")
    print("\n\n".join(failures))
    sys.exit(1)
print(f"All checks passed (parser: {ao3_fast.PARSER}).")
