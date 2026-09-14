# Interactive phone for an AO3 fic

A working phone UI your readers can tap through inside a fic — lock screen,
home screen, apps, message threads, photos, notes, voicemail, and an app
locked behind a 4-digit passcode they have to find clues for elsewhere in
the phone.

No JavaScript, because AO3 strips it out of works. No `id` attributes either
— see below, that one is the whole trick.

```
src/workskin.css      the stylesheet you paste into AO3   ← edit this
src/body.html         the markup you paste into the work  ← and this
build.py              python3 build.py  → regenerates dist/
ao3check.py           python3 ao3check.py → fails on anything AO3 would drop
ao3sim.py             applies AO3's sanitizer, used by build.py

dist/workskin.css     paste target 1
dist/work-body.html   paste target 2 (one long line, on purpose)
dist/preview.html     what you wrote
dist/preview-ao3.html the same page after AO3's sanitizer has had it
```

Open **`dist/preview-ao3.html`**, not `preview.html`, when you want to know
whether something will really work. It is the source markup with AO3's own
attribute stripping and paragraph wrapping applied first, so it renders what
the archive will actually serve.

## How the navigation works

AO3's HTML sanitizer allows exactly these attributes:

```ruby
attributes: { all: %w[align dir lang title], "a" => %w[href name], ... }   # + class
```

`id` is not on the list, on any element. So the obvious approach — hidden
screens revealed by `:target` — cannot work on AO3: the archive deletes every
`id`, `:target` then matches nothing, and you get a phone that renders
perfectly and does absolutely nothing when tapped. (Selectors themselves are
never sanitized, so it isn't `:target` that AO3 objects to. It's the anchor.)

What AO3 does keep is `name` on `<a>`, its documented way to anchor within a
work. So the phone is built as a **scrolling strip**:

- `.vp` is a 290×580 window with `overflow: hidden`.
- Each screen is a `.pane` inside it, exactly 580px tall, stacked vertically.
- Each pane opens with `<p class="anc"><a name="msgs"></a></p>`, a zero-size
  out-of-flow anchor pinned to the pane's top corner.
- Every tap is `<a href="#msgs">`. Fragment navigation scrolls the window to
  put that anchor's **top edge** at the window's top edge, which lands the
  pane square in the window.

No pseudo-classes, no ids, no scripts. The first pane in the markup is what
readers see before they tap anything, which is why the lock screen comes
first, and the browser's back button walks the history like a back gesture.

Two more things the archive does to your markup, both harmless but worth
knowing when something looks 18 pixels off:

- It wraps every run of loose inline tags in a `<p>` of its own — about 170
  paragraphs get injected into this phone. Hence `.phone p{margin:0}`, and
  hence the `<p class="anc">` wrapper: a bare `<a>` would get wrapped in a
  paragraph AO3 owns and you cannot style.
- It adds `rel="nofollow"` to every link.

## Posting it on AO3

1. **Make the work skin.** Dashboard → Skins → My Work Skins → *Create Work
   Skin*. Give it a title, paste all of `dist/workskin.css` into the CSS box,
   Submit. AO3 prefixes every rule with `#workskin` itself — don't add it.
   If AO3 rejects a line, delete that line; nothing in the skin is
   load-bearing on its own. (`python3 ao3check.py` should catch these first.)
2. **Post the work.** In the work form, click the **HTML** tab above the
   text box first (not Rich Text), then paste `dist/work-body.html`.
3. **Attach the skin.** Further down the work form, *Select Work Skin* →
   pick the skin you made.
4. Preview, and tap around.

`dist/work-body.html` is deliberately one long line. AO3 converts stray line
breaks inside a work into `<br>` tags, which would shove the phone apart —
that's what `build.py` strips out.

### Two things to know about readers

- Anyone can turn work skins off, and the AO3 app and EPUB downloads ignore
  them. Those readers see every screen stacked as plain text, in pane order —
  readable, just not a phone. Order your panes so that fallback still reads
  like a story, and consider putting a plain-text transcript in the end notes.
- A tap scrolls the phone to the top of the window, so the phone jumps into
  place. That's normal for this kind of fic and readers are used to it.
- If you put **two** phones in one work (or one per chapter in a single-page
  "Entire Work" view), every anchor name has to be unique. Suffix them:
  `<a name="home2">`, `href="#home2"`, and so on.

## Making it yours

Edit `src/`, run `python3 build.py`, check `python3 ao3check.py`, repaste.
Or edit `dist/` by hand if you don't want to run anything.

**A new message.** One line, inside a thread's `.bd`:

```html
<div class="row"><span class="b them">what they said</span></div>
<div class="row"><span class="b me">what you said</span></div>
<div class="ts">Sunday 3:04 AM</div>          <!-- timestamp divider -->
<div class="rd">Read 3:05 AM</div>            <!-- read receipt -->
<div class="row"><span class="b typing">&bull;&bull;&bull;</span></div>
```

**A new screen.** Copy a whole `<div class="pane">` block, give its anchor a
new name, and link to it from somewhere:

```html
<div class="pane"><p class="anc"><a name="your-new-screen"></a></p>
  <div class="hd"><a class="bk" href="#home">&#8249; Home</a><span class="ti">Title</span></div>
  <div class="bd"> ... </div>
</div>
```

Keep it a direct child of `.vp`, alongside the other panes, and don't nest
panes — the strip only works because every pane is the same height.

**A new app icon.** Add to `.apps` on the home pane:

```html
<a class="app" href="#your-screen"><span class="ic g5">&#9834;</span><span class="lb">Label</span></a>
```

`g1`–`g9` are the icon colours; add `<span class="bdg">2</span>` inside the
`.ic` for an unread badge. Icons are text characters (`&#9993;` and friends)
so they need no image hosting.

**The passcode** is `0419`. Four panes, `#pc1` → `#pc4`: on each one, the
correct digit links to the next pane and all nine others link to `#pcx`
("Passcode Incorrect"). To change it to, say, `7812`, move the forward link
to `7` on `#pc1`, `8` on `#pc2`, `1` on `#pc3`, `2` on `#pc4` — and plant the
new clue somewhere (right now the date is in a note, a photo caption, and the
unknown number's last four digits).

**Real photos.** AO3 allows `<img>` from any https host, so if you have images
hosted somewhere, swap a coloured tile for one:

```html
<a class="ph" href="#ph1"><img src="https://example.com/pic.jpg" alt=""/></a>
```

**Colours.** The screen background is `#101218`, incoming bubbles `#262b37`,
outgoing `#2f6df6`, the wallpaper is the gradient on `.wall` and `.lockpane`.
Every gradient has a flat colour declared right before it, so if AO3 ever
strips the gradient the phone just goes solid.

## What the checker knows

`ao3check.py` holds AO3's real whitelists, transcribed from the archive's
source, and fails the build on anything the archive would drop:

| what | where it comes from |
| --- | --- |
| allowed elements and attributes | `config/initializers/gem-plugin_config/sanitizer_config.rb` |
| allowed CSS properties | `config/config.yml` — `SUPPORTED_CSS_PROPERTIES` |
| allowed CSS values | `lib/css_cleaner.rb` |
| paragraph wrapping | `lib/paragraph_maker.rb` |

Worth re-running if you add anything: `display: grid`, `gap`, `calc()` and
custom properties all look fine locally and all vanish on the archive.

## The demo story in it

Placeholder content — swap the names out. A narrator with a 2:14 AM problem:
Wren has a photo, an unknown number has a deadline, Mom left a voicemail
about an anniversary, building management has stairwell footage, and the
thread that explains all of it is behind the passcode.
