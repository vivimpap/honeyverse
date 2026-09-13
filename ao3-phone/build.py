#!/usr/bin/env python3
"""Build the AO3-ready files from src/.

    python3 build.py

Writes:
  dist/work-body.html  paste into the AO3 work text box (HTML editor tab)
  dist/workskin.css    paste into the AO3 work skin
  dist/preview.html    open in a browser to see it exactly as AO3 renders it

AO3 turns stray line breaks inside a work into <br> tags, which would push
the phone apart, so the work body is emitted as one long line with comments
removed.
"""
import re, pathlib

here = pathlib.Path(__file__).parent
css = (here / "src" / "workskin.css").read_text()
body = (here / "src" / "body.html").read_text()

# strip HTML comments, then every run of whitespace that sits between tags
flat = re.sub(r"<!--.*?-->", "", body, flags=re.S)
flat = re.sub(r">\s+<", "><", flat)
flat = re.sub(r"\s*\n\s*", " ", flat).strip()

dist = here / "dist"
dist.mkdir(exist_ok=True)
(dist / "work-body.html").write_text(flat + "\n")
(dist / "workskin.css").write_text(css)

preview = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>AO3 interactive phone &mdash; preview</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
/* AO3's own page, roughly: it wraps every work in #workskin and prefixes
   each rule of your work skin with that id. Nothing below is part of the
   skin you paste into AO3. */
body{margin:0;padding:28px 16px 60px;background:#f5f1e8;color:#2a2621;
     font:16px/1.6 Georgia,'Times New Roman',serif}
#workskin{max-width:640px;margin:0 auto}
h1{font:600 20px/1.3 system-ui,sans-serif;text-align:center;margin:0 0 4px}
.meta{text-align:center;font:13px/1.5 system-ui,sans-serif;color:#7a7266;margin:0 0 26px}
#workskin a{color:#a04a28}
</style>
<style>
%s
</style>
</head><body>
<h1>Chapter 1: 2:14 AM</h1>
<p class="meta">preview only &mdash; this file is not what you paste into AO3</p>
<div id="workskin">
%s
</div>
</body></html>
""" % (
    # AO3 scopes every skin rule to #workskin; do the same so the preview matches
    re.sub(r"(?m)^([.#][^{@\n][^{\n]*)\{", r"#workskin \1{", css),
    flat,
)
(dist / "preview.html").write_text(preview)
print("wrote dist/work-body.html  (%d chars)" % len(flat))
print("wrote dist/workskin.css    (%d chars)" % len(css))
print("wrote dist/preview.html")
