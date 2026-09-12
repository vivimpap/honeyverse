# AO3 fast scraper

Replaces the old two-script workflow (`ao3_phase1_ids.py` + `ao3_phase2_metadata.py`)
with a single pass. Same CSV columns, same `' ; '` separator, ~100x faster.

## Why it's faster

The old Phase 2 fetched one page per fic. It never needed to. AO3's **work
listing pages already contain the full metadata for every fic they list** — and
they list 25 fics per page.

Three things were checked directly against [otwarchive](https://github.com/otwcode/otwarchive),
AO3's own source, rather than assumed:

| Claim | Where it's verified | Result |
|---|---|---|
| Listings truncate tags with "…" | `blurb_tag_block` (`app/helpers/tags_helper.rb`) | **False.** Every tag is written into the HTML. The "…" is CSS. |
| Listings show 20 fics/page | `ITEMS_PER_PAGE` (`config/config.yml`) | It's **25**. |
| 5–8 s between requests is required | `RATE_LIMIT_NUMBER` / `RATE_LIMIT_PERIOD` | Limit is **300 req / 300 s** = 1/sec. |

So: 25× fewer requests, each ~4× sooner. A 10,000-fic tag goes from roughly
19 hours to about 10 minutes — and hits ~25× fewer 525s along the way, because
a 525 is Cloudflare failing to reach AO3's origin, not your rate limit.

## Usage

```bash
pip3 install requests beautifulsoup4 lxml     # lxml optional, ~3x faster parsing

# edit the EDIT THESE block at the top of ao3_fast.py, then:
python3 ao3_fast.py                  # main scrape (resumable)
python3 ao3_fast.py --fill-published # optional: exact publish dates
python3 ao3_fast.py --verify 15      # spot-check against real fic pages
python3 ao3_fast.py --update         # later: pull in new/changed fics
```

## Output

Byte-identical column contract to the old Phase 2:

```
work_id, url, title, author, rating, archive_warnings, categories, fandoms,
relationships, characters, additional_tags, language, published, status_label,
status_date, words, chapters, comments, kudos, bookmarks, hits
```

Multi-value cells use `' ; '`. The `|` inside individual tags
(`Choi Taeyang | Theo`) is untouched — `;` only ever appears *between* tags, so
`split(";")` + `strip()` still works.

Empty cells match the old behaviour exactly: AO3 omits comments/kudos/bookmarks
when they're zero, and omits the Updated/Completed row entirely for fics whose
expected chapter count is 1 — so those cells were blank before too.

## The one field that needs a second request

`published` is the only column not in the listing; blurbs carry the *revised*
date. For a fic with **one posted chapter** those are the same date, so it's
filled immediately — that's the majority of most fandoms. For the rest,
`--fill-published` visits only those fics.

Everything else, including `status_label` and `status_date`, is derived exactly:
`work_meta_list` only emits the status row when `expected_number_of_chapters != 1`,
and the chapter display is `posted/expected`, so both are recoverable from the
blurb's `3/?` or `25/25`.

## Two correctness fixes over the old scripts

**Stable sort.** AO3's default listing order is `revised_at desc`, so every time
anyone updates a fic, everything below it shifts down a slot. Mid-crawl a fic can
move from page 8 to page 9 *after* you've read page 9 — and you never see it.
This script pins `sort_column=created_at&sort_direction=asc`, which
`work_query.rb` tie-breaks by `id`: a stable total order where existing fics
never move. (If your `TAG_URL` already specifies a sort, yours is respected.)

**Paging ceiling.** `MAX_SEARCH_RESULTS` is 100,000 and `Search::Query#page`
clamps with `.min` — so requesting page 5000 silently re-serves page 4000
forever rather than erroring. The old `MAX_PAGE = 5000` would burn ~1000 wasted
requests at the end of a big tag. This stops at 4000 and tells you to split by
date range.

## Verifying

The parser is tested against fixtures built from otwarchive's own templates:

```bash
python3 test_parser.py
```

To confirm against live AO3 — which the fixtures can't do — use `--verify N`.
It samples N scraped fics, fetches their real fic pages, and diffs every field.
Run it once on a small sample before trusting a big scrape.

## Why not Go / Rust / threads

The bottleneck is AO3's rate limit, not parsing. At 200 requests per 300 s the
script is idle almost the whole time — a faster language would wait faster.
Threads don't help either: the limit is per-IP, so concurrency just reaches it
sooner and earns 429s. The only real lever is *number of requests*, which is
exactly what dropping Phase 2 addresses.
