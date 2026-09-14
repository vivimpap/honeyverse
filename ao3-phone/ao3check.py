#!/usr/bin/env python3
"""Check the built files against what AO3 actually allows.

    python3 ao3check.py

The archive silently drops disallowed HTML attributes and refuses to save a
work skin containing a disallowed CSS property or value, so a mistake here
shows up as "the phone renders but nothing happens" rather than an error.
The lists below are transcribed from the archive's own source:

  elements / attributes  otwarchive config/initializers/gem-plugin_config/sanitizer_config.rb
  class names            otwarchive lib/otw_sanitize/user_class_sanitizer.rb
  CSS properties         otwarchive config/config.yml (SUPPORTED_CSS_PROPERTIES)
  CSS values             otwarchive lib/css_cleaner.rb

Two rules here have already cost a posting cycle each:

  `id` is not an allowed attribute on anything, which is why this phone
  navigates with <a name=""> anchors instead of :target; and

  a class name must match /^[a-zA-Z][\w\-]+$/ -- note the + -- so a
  single-character class like `class="b"` is dropped from the posted work
  while the skin rule for it stays behind, styling nothing.
"""
import re, sys, pathlib

ELEMENTS = set("""a abbr acronym address b big blockquote br caption center cite code col
colgroup details figcaption figure dd del dfn div dl dt em h1 h2 h3 h4 h5 h6 hr
i img ins kbd li ol p pre q rp rt ruby s samp small span strike strong
sub summary sup table tbody td tfoot th thead tr tt u ul var""".split())

VALID_CLASS = re.compile(r"^[a-zA-Z][\w\-]+$")

ATTRS_ALL = {"align", "dir", "lang", "title", "class"}
ATTRS_BY_TAG = {
    "a": {"href", "name"}, "blockquote": {"cite"}, "col": {"span", "width"},
    "colgroup": {"span", "width"}, "details": {"open"}, "hr": {"align", "width"},
    "img": {"align", "alt", "border", "height", "src", "width"},
    "ol": {"start", "type"}, "q": {"cite"},
    "table": {"border", "summary", "width"},
    "td": {"abbr", "axis", "colspan", "height", "rowspan", "width"},
    "th": {"abbr", "axis", "colspan", "height", "rowspan", "scope", "width"},
    "ul": {"type"},
}

PROPERTIES = set(['-replace', '-use-link-source', 'accelerator', 'accent-color', 'align-content', 'align-items', 'align-self', 'alignment-adjust', 'alignment-baseline', 'appearance', 'aspect-ratio', 'azimuth', 'baseline-shift', 'behavior', 'binding', 'bookmark-label', 'bookmark-level', 'bookmark-target', 'bottom', 'box-align', 'box-direction', 'box-flex', 'box-flex-group', 'box-lines', 'box-orient', 'box-pack', 'box-shadow', 'box-sizing', 'caption-side', 'clear', 'clip', 'color', 'color-profile', 'color-scheme', 'content', 'counter-increment', 'counter-reset', 'crop', 'cue', 'cue-after', 'cue-before', 'cursor', 'direction', 'display', 'dominant-baseline', 'drop-initial-after-adjust', 'drop-initial-after-align', 'drop-initial-before-adjust', 'drop-initial-before-align', 'drop-initial-size', 'drop-initial-value', 'elevation', 'empty-cells', 'fill', 'filter', 'fit', 'fit-position', 'float', 'float-offset', 'font', 'font-effect', 'font-emphasize', 'font-emphasize-position', 'font-emphasize-style', 'font-family', 'font-size', 'font-size-adjust', 'font-smooth', 'font-stretch', 'font-style', 'font-variant', 'font-weight', 'grid-columns', 'grid-rows', 'hanging-punctuation', 'height', 'hyphenate-after', 'hyphenate-before', 'hyphenate-character', 'hyphenate-lines', 'hyphenate-resource', 'hyphens', 'icon', 'image-orientation', 'image-resolution', 'ime-mode', 'include-source', 'inline-box-align', 'justify-content', 'layout-flow', 'left', 'letter-spacing', 'line-break', 'line-height', 'line-stacking', 'line-stacking-ruby', 'line-stacking-shift', 'line-stacking-strategy', 'mark', 'mark-after', 'mark-before', 'marks', 'marquee-direction', 'marquee-play-count', 'marquee-speed', 'marquee-style', 'max-height', 'max-width', 'min-height', 'min-width', 'move-to', 'nav-down', 'nav-index', 'nav-left', 'nav-right', 'nav-up', 'opacity', 'order', 'orphans', 'page', 'page-policy', 'phonemes', 'pitch', 'pitch-range', 'play-during', 'position', 'presentation-level', 'punctuation-trim', 'quotes', 'rendering-intent', 'resize', 'rest', 'rest-after', 'rest-before', 'richness', 'right', 'rotation', 'rotation-point', 'ruby-align', 'ruby-overhang', 'ruby-position', 'ruby-span', 'size', 'speak', 'speak-header', 'speak-numeral', 'speak-punctuation', 'speech-rate', 'stress', 'string-set', 'stroke', 'stroke-width', 'tab-side', 'table-layout', 'target', 'target-name', 'target-new', 'target-position', 'top', 'unicode-bibi', 'unicode-bidi', 'user-select', 'vertical-align', 'visibility', 'voice-balance', 'voice-duration', 'voice-family', 'voice-pitch', 'voice-pitch-range', 'voice-rate', 'voice-stress', 'voice-volume', 'volume', 'white-space', 'white-space-collapse', 'widows', 'width', 'word-break', 'word-spacing', 'word-wrap', 'writing-mode', 'z-index', 'z', 'or', 'separated'])
SHORTHAND = ['background', 'border', 'column', 'cue', 'flex', 'font', 'layer-background', 'layout-grid', 'list-style', 'margin', 'marker', 'outline', 'overflow', 'padding', 'page-break', 'pause', 'scrollbar', 'text', 'transform', 'transition']

# css_cleaner.rb builds values out of these pieces. Simplified, but it rejects
# everything the archive rejects in practice: calc(), custom properties used as
# var() targets we never declare, unitless keywords are fine, functions are not
# unless they are a gradient / rgba / hsla / transform / filter.
NUM = r"-?\.?\d{1,3}\.?\d{0,3}\s*(deg|cm|em|ex|in|mm|pc|pt|px|s|%)?"
WORD = r"[a-z\-]+"
FUNC = r"(rgba?|hsla?|[a-z\-]*gradient|scale[xy]?|translate[xy]?|skew[xy]?|rotate[xy]?|matrix|blur|brightness|contrast|grayscale|hue-rotate|invert|opacity|saturate|sepia|drop-shadow|var|url|rect|color-stop)\([^()]*(\([^()]*\)[^()]*)*\)"
TOKEN = re.compile(r"^(#[0-9a-f]{3,8}|%s|%s|%s)$" % (FUNC, NUM, WORD), re.I)

def check_value(prop, value):
    v = value.replace("!important", "").strip()
    if prop == "font-family":
        return all(re.match(r"^['\"]?[a-z0-9\- ]+['\"]?$", n.strip(), re.I) for n in v.split(","))
    # split on commas and spaces, but not inside parentheses
    depth, cur, toks = 0, "", []
    for ch in v:
        if ch == "(": depth += 1
        if ch == ")": depth -= 1
        if ch in " ," and depth == 0:
            if cur: toks.append(cur); cur = ""
        else:
            cur += ch
    if cur: toks.append(cur)
    return all(TOKEN.match(t) for t in toks)

def check_css(path):
    bad = []
    css = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    for block in re.findall(r"\{([^}]*)\}", css):
        for decl in block.split(";"):
            if ":" not in decl: continue
            prop, _, value = decl.partition(":")
            prop, value = prop.strip().lower(), value.strip()
            if not prop or not value: continue
            shorthand = any(s in prop for s in SHORTHAND)   # AO3 matches unanchored
            if prop not in PROPERTIES and not shorthand and not prop.startswith("--"):
                bad.append("property not supported: %s" % prop)
            elif not check_value(prop, value):
                bad.append("value rejected for %s: %s" % (prop, value))
    return bad

def check_html(path):
    bad = []
    html = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S)
    for tag, attrs in re.findall(r"<([a-z0-9]+)((?:\s+[a-z\-]+=\"[^\"]*\")*)\s*/?>", html, re.I):
        tag = tag.lower()
        if tag not in ELEMENTS:
            bad.append("element not allowed: <%s>" % tag)
        allowed = ATTRS_ALL | ATTRS_BY_TAG.get(tag, set())
        for attr in re.findall(r"\s+([a-z\-]+)=", attrs, re.I):
            if attr.lower() not in allowed:
                bad.append("attribute stripped by AO3: %s on <%s>" % (attr.lower(), tag))
    for attr in re.findall(r'class="([^"]*)"', html):
        for name in attr.split():
            if not VALID_CLASS.match(name):
                bad.append("class stripped by AO3 (needs 2+ chars, "
                           "must start with a letter): %s" % name)
    return bad


def check_selectors(path):
    """A skin rule for a class AO3 strips is dead weight — flag it too."""
    bad = []
    css = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    css = re.sub(r"\{[^}]*\}", " ", css)          # selectors only, no values
    for name in set(re.findall(r"\.([A-Za-z_][\w\-]*)", css)):
        if not VALID_CLASS.match(name):
            bad.append("selector can never match, AO3 strips this class: .%s" % name)
    return bad

here = pathlib.Path(__file__).parent
problems = []
problems += ["workskin.css: " + b for b in check_css(here / "dist" / "workskin.css")]
problems += ["workskin.css: " + b for b in check_selectors(here / "dist" / "workskin.css")]
problems += ["work-body.html: " + b for b in check_html(here / "dist" / "work-body.html")]

seen, unique = set(), []
for p in problems:
    if p not in seen:
        seen.add(p); unique.append(p)
for p in unique:
    print("FAIL", p)
if unique:
    print("\n%d problem(s). AO3 would drop or reject these." % len(unique))
    sys.exit(1)
print("OK — every element, attribute, property and value is one AO3 accepts.")
