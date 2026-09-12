# AO3 fast scraper

Replaces the old two-script workflow (`ao3_phase1_ids.py` + `ao3_phase2_metadata.py`)
with a single pass. Same CSV columns, same `' ; '` separator, ~90x faster.

## Why it's faster

The old Phase 2 fetched one page per fic. It never needed to. AO3's **work
listing pages already contain the full metadata for every fic they list** — and
they list 20 fics per page.

Three things were checked rather than assumed — two against
[otwarchive](https://github.com/otwcode/otwarchive) (AO3's own source), and the
page size against live AO3, because the repo's config is only a sample:

| Question | Where it's answered | What AO3 actually does |
|---|---|---|
| Does the listing truncate the tag list with "…"? | `blurb_tag_block` (`app/helpers/tags_helper.rb`) | **No.** Every relationship/character/freeform tag is written into the HTML. The "…" is CSS. |
| How many fics does one listing page carry? | Measured against live AO3 | **20.** So one request replaces 20. (otwarchive's *sample* `config.yml` says `ITEMS_PER_PAGE: 25`; production overrides it. Trust the live count, not the repo default.) |
| How fast may I request? | `RATE_LIMIT_NUMBER` / `RATE_LIMIT_PERIOD` (`config/config.yml`) | **300 requests / 300 seconds** = 1/sec. The old scripts' 5–8 s was ~6× stricter than required. |

So: 20× fewer requests, each ~4× sooner. A 10,000-fic tag goes from roughly
19 hours to about 13 minutes — and hits ~20× fewer 525s along the way, because
a 525 is Cloudflare failing to reach AO3's origin, not your rate limit.

The scraper doesn't hard-code the page size anywhere — it reads however many
blurbs a page actually returns, and stops when AO3 says there's no next page.
The number only feeds the estimate above.

## Usage

```bash
pip3 install requests beautifulsoup4 lxml     # lxml optional, ~3x faster parsing

# edit the EDIT THESE block at the top of ao3_fast.py, then:
python3 ao3_fast.py                      # full scrape -> complete CSV
python3 ao3_fast.py --no-fill-published  # listing pass only (faster, gappy)
python3 ao3_fast.py --verify 15          # spot-check against real fic pages
python3 ao3_fast.py --update             # later: pull in new/changed fics
```

A plain run does **both** passes and leaves `published` filled on every row.
It walks the listing pages first, then visits only the multi-chapter fics to
finish the one column listings can't supply. A multi-chapter fic ends up with
*both* dates, which is correct: `published` = when it was first posted,
`status_date` = when it was last updated.

### Filling `published` on a CSV you already have

`--fill-published` works on any CSV with `work_id` / `url` / `published`
columns, not just one this script produced:

```bash
# 1. look before you leap: fetch 3 works, print what was parsed, write nothing
python3 ao3_fast.py --fill-published --csv mi_fandom_metadata.csv --test 3

# 2. if those look right, the full pass
python3 ao3_fast.py --fill-published --csv mi_fandom_metadata.csv
```

- Only rows whose `published` is **empty** are fetched. Rows that already have
  a date are never re-downloaded and never modified.
- Only the `published` cell is written. Every other column survives verbatim,
  **including columns this script has never heard of** — the file is rewritten
  against its own header, not against the script's field list. (Add
  `--refresh-status` if you also want `status_label` / `status_date` refreshed
  from the fic page while you're paying for the request anyway.)
- A one-time `.bak` copy of the original is written before the first rewrite.
- The CSV is rewritten every `--save-every` rows (default 25), atomically via a
  temp file, so a crash or Ctrl-C can't leave you with a half-written CSV.
- **Resumable**: rows that error out are deliberately left empty, so rerunning
  the same command retries exactly those and nothing else. Restricted and
  deleted works are skipped permanently (no date exists to fetch).

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
filled from the listing — typically ~75% of a fandom. The rest cost one request
each, which the plain run spends automatically so you get a complete column.

It fetches **`/works/<id>/navigate`**, not the work page. That matters a lot:
a work page ships the entire chapter text — often megabytes on a longfic — and
we want exactly one date out of it. The navigate page is rendered with
`@work.chapters_in_order(include_content: false)`, so it's a few KB no matter
how long the fic is, it needs no login (`works_controller` lists `:navigate`
among the `users_only` exceptions), and since chapters come in order its first
entry is chapter 1 — whose date *is* the publication date. If a navigate page
ever comes back unusable, it pays for the full work page once for that row
rather than losing it.

The run prints per-fic download time and size, so if it's ever slow again you
can see immediately whether the time is going into downloading or into pacing.

The only rows that can end up without a date are multi-chapter fics that are
restricted or deleted, where AO3 won't serve the page at all. Those are left
**empty on purpose** rather than back-filled with the revised date, which would
put a wrong date in your dataset. The run tells you how many, and rerunning
retries the ones that failed for transient reasons.

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

**Paging ceiling.** `Search::Query#page` clamps with `.min` against
`(MAX_SEARCH_RESULTS / per_page).ceil`, so past the ceiling AO3 silently
re-serves the last real page instead of erroring — the old `MAX_PAGE = 5000`
just burned requests there.

Both numbers in that formula are deployment config you can't read from outside
(this is exactly where trusting the repo's sample `ITEMS_PER_PAGE` would put the
ceiling in the wrong place), so this script doesn't compute it — it *detects*
it. Two consecutive full pages with zero new fics means AO3 has stopped
paginating; it stops and tells you to split `TAG_URL` by date range. It also
deliberately does **not** mark the tag complete in that case, so a later
`--update` won't assume full coverage.

## Verifying

The parser is tested against fixtures built from otwarchive's own templates:

```bash
python3 test_parser.py          # blurb parsing
python3 test_fill_published.py  # publish-date pass, column preservation
python3 test_end_to_end.py      # a plain run leaves no empty publish date
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
