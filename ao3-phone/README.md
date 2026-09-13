# Interactive phone for an AO3 fic

A working phone UI your readers can tap through inside a fic — lock screen,
home screen, apps, message threads, photos, notes, voicemail, and an app
locked behind a 4-digit passcode they have to find clues for elsewhere in
the phone.

AO3 strips JavaScript out of works, so none of this uses any. Navigation is
pure CSS: every screen is a `<div id="…">` that stays hidden until its id is
the one in the URL (`:target`), and every tap is an ordinary `<a href="#…">`.
Back arrows are links too, and the browser's own back button works.

```
src/workskin.css   the stylesheet you paste into AO3   ← edit this
src/body.html      the markup you paste into the work  ← and this
build.py           python3 build.py  → regenerates dist/
dist/workskin.css  paste target 1
dist/work-body.html paste target 2 (one long line, on purpose)
dist/preview.html  open in a browser — looks exactly like the posted work
```

## Posting it on AO3

1. **Make the work skin.** Dashboard → Skins → My Work Skins → *Create Work
   Skin*. Give it a title, paste all of `dist/workskin.css` into the CSS box,
   Submit. AO3 prefixes every rule with `#workskin` itself — don't add it.
   *If AO3 rejects a line, delete that line.* Everything in the skin is
   either layout or decoration; nothing breaks catastrophically without one
   declaration.
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
  them. Those readers see every screen stacked as plain text, in DOM order —
  readable, just not a phone. Order your screens so that fallback still reads
  like a story, and consider putting a plain-text transcript in the end notes.
- A tap changes the page's `#anchor`, so the browser scrolls the phone to the
  top of the window. That's normal for this kind of fic and readers are used
  to it.
- If you put **two** phones in one work (or one per chapter of a single-page
  "Entire Work" view), every `id` has to be unique. Suffix them:
  `id="home2"`, `href="#home2"`, and so on.

## Making it yours

Edit `src/`, run `python3 build.py`, repaste. Or edit `dist/` by hand if you
don't want to run anything.

**A new message.** One line, inside a thread's `.bd`:

```html
<div class="row"><span class="b them">what they said</span></div>
<div class="row"><span class="b me">what you said</span></div>
<div class="ts">Sunday 3:04 AM</div>          <!-- timestamp divider -->
<div class="rd">Read 3:05 AM</div>            <!-- read receipt -->
<div class="row"><span class="b typing">&bull;&bull;&bull;</span></div>
```

**A new screen.** Copy any `<div class="scr" id="…">` block, give it a new id,
and link to it from somewhere with `href="#your-new-id"`. Keep it a direct
child of `.vp`, alongside the others — screens are siblings, never nested.

**A new app icon.** Add to `.apps` on the home screen:

```html
<a class="app" href="#your-screen"><span class="ic g5">&#9834;</span><span class="lb">Label</span></a>
```

`g1`–`g9` are the icon colours; add `<span class="bdg">2</span>` inside the
`.ic` for an unread badge. Icons are just text characters (`&#9993;` etc.)
so they need no image hosting.

**The passcode** is `0419`. Four screens, `#pc1` → `#pc4`: on each one, the
correct digit links to the next screen and all nine others link to `#pcx`
("Passcode Incorrect"). To change it to, say, `7812`, move the forward link
to `7` on `#pc1`, `8` on `#pc2`, `1` on `#pc3`, `2` on `#pc4` — and plant the
new clue somewhere (right now the date is in a note, a photo caption, and
the unknown number's last four digits).

**Real photos.** AO3 allows `<img>` from any https host, so if you have images
hosted somewhere, swap a coloured tile for one:

```html
<a class="ph" href="#ph1"><img src="https://example.com/pic.jpg" alt=""/></a>
```

**Colours.** The screen background is `#101218`, incoming bubbles `#262b37`,
outgoing `#2f6df6`, the wallpaper is the gradient on `.wall` and `.lockscr`.
Every gradient has a flat colour declared right before it, so if AO3 ever
strips the gradient the phone just goes solid.

## The demo story in it

Placeholder content — swap the names out. A narrator with a 2:14 AM problem:
Wren has a photo, an unknown number has a deadline, Mom left a voicemail
about an anniversary, building management has stairwell footage, and the
thread that explains all of it is behind the passcode.
