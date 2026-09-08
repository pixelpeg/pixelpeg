# Embedded typeface

[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) v2.304, subset to
only the characters each graphic actually draws, and inlined into the SVGs as
base64 `@font-face`.

Why inline it at all:

* **Metrics.** `draw_tdd` places each run of text by multiplying a character
  count by an advance width of exactly 0.600 em, and reveals it with a clipPath
  sized the same way. JetBrains Mono is 600/1000 units, so the geometry holds —
  but a viewer whose default monospace is narrower (Consolas is ≈0.55) would see
  those runs drift left of the clip that is meant to uncover them. Inlining
  pins it.
* **An external font URL cannot work here.** These SVGs are loaded through
  `<img>`, and a browser refuses to fetch subresources for an image document.
  A base64 data URI is the only mechanism, and it keeps the page free of
  third-party requests.

| file | weight | covers |
|---|---|---|
| `jbmono-400.woff2` | 400 | basic latin, for the panels |
| `jbmono-600.woff2` | 600 | basic latin, for the panels and the headings |

Two other cuts have been removed. `jbmono-head.woff2` held exactly the letters
the section headings spelled: it saved about 3 KB and broke silently the first
time a section was renamed, dropping the new word's missing glyphs back to
whatever monospace the viewer happens to have — section names are content, so
the headings use the full latin cut now. `jbmono-ramp.woff2` held the character
ramp for the ASCII portrait, which the page no longer has.

Licensed under the SIL Open Font License 1.1 — see `OFL.txt`. Subsetting and
redistribution in this form are permitted; the reserved font name is unchanged.
