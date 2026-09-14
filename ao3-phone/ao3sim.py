#!/usr/bin/env python3
"""Apply AO3's own two transformations to the work body, so the preview shows
what the archive renders rather than what we wrote.

Transcribed from the archive's source:
  attribute stripping  config/initializers/gem-plugin_config/sanitizer_config.rb
  class validation     lib/otw_sanitize/user_class_sanitizer.rb
  paragraph wrapping   lib/paragraph_maker.rb  (wrap_all)

Two of those are easy to get wrong. AO3 wraps any run of loose inline
children in a <p> of its own, so markup that never mentions <p> comes back
with paragraphs in it. And a class name must match /^[a-zA-Z][\w\-]+$/ --
note the + -- so every single-character class is thrown away.
"""
import re
from html.parser import HTMLParser

VOID = {"br", "hr", "img", "col"}
VALID_CLASS = re.compile(r"^[a-zA-Z][\w\-]+$")
ATTRS_ALL = {"align", "dir", "lang", "title", "class"}
ATTRS_BY_TAG = {
    "a": {"href", "name"}, "blockquote": {"cite"}, "col": {"span", "width"},
    "colgroup": {"span", "width"}, "details": {"open"}, "hr": {"align", "width"},
    "img": {"align", "alt", "border", "height", "src", "width"},
    "ol": {"start", "type"}, "q": {"cite"}, "table": {"border", "summary", "width"},
    "td": {"abbr", "axis", "colspan", "height", "rowspan", "width"},
    "th": {"abbr", "axis", "colspan", "height", "rowspan", "scope", "width"},
    "ul": {"type"},
}
SKIP = set("""a abbr acronym address audio dl embed figure h1 h2 h3 h4 h5 h6 hr img ol
object p pre source summary table track ul video button input label map select
textarea iframe math noembed noframes noscript plaintext script style svg xmp""".split())
WRAP = set("""a abbr acronym b big br cite code del dfn em i img ins kbd q rp rt ruby
s samp small span strike strong sub sup tt u var button input label map select
textarea""".split())


class Node:
    def __init__(self, tag=None, attrs=None):
        self.tag, self.attrs, self.kids, self.text = tag, attrs or [], [], None


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        allowed = ATTRS_ALL | ATTRS_BY_TAG.get(tag, set())
        kept = []
        for k, v in attrs:
            if k not in allowed:
                continue
            if k == "class" and v:
                v = " ".join(c for c in v.split() if VALID_CLASS.match(c))
            kept.append((k, v))
        node = Node(tag, kept)
        self.stack[-1].kids.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def _text(self, data):
        n = Node()
        n.text = data
        self.stack[-1].kids.append(n)

    handle_data = _text
    handle_entityref = lambda self, name: self._text("&%s;" % name)
    handle_charref = lambda self, name: self._text("&#%s;" % name)


def wrap_all(node, in_p=False):
    """AO3's wrap_all: bundle each run of inline/text children into one <p>."""
    if node.tag in SKIP or in_p or node.tag == "p":
        return
    out, run = [], []
    for kid in node.kids:
        inline = kid.text is not None or kid.tag in WRAP
        if inline:
            run.append(kid)
            continue
        if run:
            p = Node("p")
            p.kids = run
            out.append(p)
            run = []
        wrap_all(kid)
        out.append(kid)
    if run:
        p = Node("p")
        p.kids = run
        out.append(p)
    node.kids = out


def render(node):
    if node.text is not None:
        return node.text
    inner = "".join(render(k) for k in node.kids)
    if node.tag in (None, "#root"):
        return inner
    attrs = "".join(' %s="%s"' % (k, v) for k, v in node.attrs)
    if node.tag == "a":
        attrs += ' rel="nofollow"'          # AO3 adds this to every link
    if node.tag in VOID:
        return "<%s%s/>" % (node.tag, attrs)
    return "<%s%s>%s</%s>" % (node.tag, attrs, inner, node.tag)


def sanitize(html):
    t = Tree()
    t.feed(html)
    wrap_all(t.root)
    return render(t.root)


if __name__ == "__main__":
    import sys
    print(sanitize(open(sys.argv[1]).read()))
