#!/usr/bin/env python3
"""Draw the profile README's SVG graphics.

No third-party services and no dependencies — standard library only.

The page is prose plus section headings, so this writes only the hd-*.svg
headings and needs no network and no token. The data graphics below are kept
and still work; name one in STAT_FILES and add its <img> to the README to
bring it back, and the API fetch turns itself on.

  stats.svg   hero total + weekly sparkline        (draw_contributions)
  streak.svg  current and longest streak           (draw_streaks)
  langs.svg   top languages, by bytes and by repo  (draw_languages)
  year.svg    the year as a character map          (draw_year_map)

Everything shares one visual language: the same grey ink, a monospace face,
a transparent background, and a left-to-right clipPath reveal with a cursor
riding the edge. Motion is SMIL because GitHub strips <script> from READMEs.

Env:
  GITHUB_TOKEN  required only when STAT_FILES is non-empty
  GH_LOGIN      user to summarise (default: pixelpeg)
  OUT_DIR       where to write (default: repository root)
"""
import base64
import functools
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.github.com/graphql"

# Two things are pinned for determinism, both learned the hard way:
#  * the contribution window, to whole UTC days — otherwise "the past year" is
#    measured from request time and days drift between week buckets, moving the
#    sparkline a fraction of a pixel and committing noise every night;
#  * privacy: PUBLIC on repositories — otherwise a personal token sees private
#    repos and a workflow token doesn't, so language totals disagree.
QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date weekday } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 privacy: PUBLIC) {
      nodes {
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

# One ink across every graphic, so the page reads as one material.
LIGHT = dict(ink="#6e7681", strong="#424a53", mute="#8c959f",
             rule="#d8dee4", surface="#ffffff",
             passed="#1a7f37", failed="#cf222e")
DARK = dict(ink="#c9d1d9", strong="#f0f6fc", mute="#8b949e",
            rule="#30363d", surface="#0d1117",
            passed="#3fb950", failed="#f85149")
# JBMono is the inlined subset below; the rest is a fallback for the unlikely
# case a renderer ignores the embedded face.
MONO_STACK = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "&apos;Liberation Mono&apos;,monospace")
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


@functools.lru_cache(maxsize=None)
def font_face(filename, weight):
    """One @font-face rule with the subset inlined as a data URI.

    An external font URL cannot work here: these SVGs are loaded through <img>,
    and browsers refuse to fetch subresources for an image document. Inlining is
    also what pins the advance width. draw_tdd places each run of text by
    multiplying a character count by 0.600 em, so a viewer whose default
    monospace is narrower would see those runs drift left of where the
    clipPath that reveals them ends.
    """
    with open(os.path.join(FONT_DIR, filename), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (f"@font-face{{font-family:JBMono;font-style:normal;"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def panel_font():
    """Basic latin, both weights — for the data graphics."""
    return font_face("jbmono-400.woff2", 400) + font_face("jbmono-600.woff2", 600)


def heading_font():
    """Basic latin at 600.

    This was once a subset cut to exactly the letters the headings spelled,
    which is smaller but silently breaks the moment a section is renamed: a
    missing glyph falls back to the viewer's own monospace mid-word. Section
    names are content, so they get the face that covers all of them.
    """
    return font_face("jbmono-600.woff2", 600)

WIDTH = 620            # every graphic shares one column width
LEFT = 34              # shared left inset, so stacked blocks line up
                       # (year.svg needs it for the weekday gutter)
REVEAL = 1.30          # seconds; one reveal sweep
RAMP = [" ", ":", "+", "#", "@"]      # quiet to loud, for draw_year_map
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
       "jul", "aug", "sep", "oct", "nov", "dec"]


# ---------------------------------------------------------------- data

def year_window():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    return (f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z")


def fetch_profile(login, token):
    since, until = year_window()
    body = json.dumps({"query": QUERY,
                       "variables": {"login": login,
                                     "from": since, "to": until}}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": f"bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": f"{login}-profile-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(f"GraphQL errors: {payload['errors']}")
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise SystemExit(f"no such user: {login}")
    return user


def day_label(iso):
    d = date.fromisoformat(iso)
    return f"{MONTHS[d.month - 1]} {d.day}"


def month_label(iso):
    d = date.fromisoformat(iso)
    return f"{MONTHS[d.month - 1]} {d.year}"


def streak_runs(days):
    """Current and longest runs of days with at least one contribution.

    A zero on the final day doesn't break the current streak — the day isn't
    over yet. Any earlier zero does.
    """
    best = dict(length=0, start=None, end=None)
    run, run_start = 0, None
    for d in days:
        if d["contributionCount"] > 0:
            run += 1
            run_start = run_start or d["date"]
            if run > best["length"]:
                best = dict(length=run, start=run_start, end=d["date"])
        else:
            run, run_start = 0, None

    cur = dict(length=0, start=None, end=None)
    tail = days[:-1] if days and days[-1]["contributionCount"] == 0 else days
    for d in reversed(tail):
        if d["contributionCount"] == 0:
            break
        cur["length"] += 1
        cur["start"] = d["date"]
        cur["end"] = cur["end"] or d["date"]
    return cur, best


def language_totals(repos):
    by_size, by_repo = {}, {}
    for node in repos:
        edges = (node.get("languages") or {}).get("edges") or []
        for e in edges:
            name = e["node"]["name"]
            by_size[name] = by_size.get(name, 0) + e["size"]
        if edges:                       # primary language of the repo
            top = edges[0]["node"]["name"]
            by_repo[top] = by_repo.get(top, 0) + 1

    def rank(d):
        # sort by value, then name, so equal values never reorder between runs
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    return rank(by_size), rank(by_repo)


def summarise_profile(user):
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = [w["contributionDays"] for w in cal["weeks"]]
    days = [d for w in weeks for d in w]
    weekly = [sum(d["contributionCount"] for d in w) for w in weeks]
    cur, best = streak_runs(days)
    by_size, by_repo = language_totals(user["repositories"]["nodes"])
    return dict(
        total=cal["totalContributions"],
        active=sum(1 for d in days if d["contributionCount"] > 0),
        best_week=max(weekly) if weekly else 0,
        weekly=weekly, weeks=weeks,
        current=cur, longest=best,
        by_size=by_size, by_repo=by_repo)


# ---------------------------------------------------------------- drawing

def stylesheet(extra="", font=None):
    def block(t):
        return (f".ink{{fill:{t['ink']}}}.ink-line{{stroke:{t['ink']}}}"
                f".strong{{fill:{t['strong']}}}.mute{{fill:{t['mute']}}}"
                f".rule{{stroke:{t['rule']}}}.halo{{stroke:{t['surface']}}}"
                f".pass{{fill:{t['passed']}}}.pass-line{{stroke:{t['passed']}}}"
                f".fail{{fill:{t['failed']}}}.fail-line{{stroke:{t['failed']}}}")
    return (f"<style>{font or panel_font()}"
            f"{block(LIGHT)}.wash{{fill:{LIGHT['ink']};opacity:.13}}{extra}"
            f"@media(prefers-color-scheme:dark){{{block(DARK)}"
            f".wash{{fill:{DARK['ink']};opacity:.16}}}}</style>")


def svg_open(w, h, font=None):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" fill="none" font-family="{MONO_STACK}">'
            + stylesheet(font=font))


def fade_in(delay, dur=0.45):
    return (f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>')


def reveal_wipe(clip_id, x, y, w, h, delay, dur=REVEAL):
    """clipPath reveal plus the cursor block that rides its edge."""
    clip = (f'<clipPath id="{clip_id}"><rect x="{x}" y="{y}" height="{h}" width="0">'
            f'<animate attributeName="width" from="0" to="{w}" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/></rect></clipPath>')
    cursor = (f'<rect y="{y}" width="2" height="{h}" class="ink" opacity="0">'
              f'<animate attributeName="x" from="{x}" to="{x + w}" '
              f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>'
              f'<set attributeName="opacity" to="0.55" begin="{delay:.2f}s"/>'
              f'<set attributeName="opacity" to="0" '
              f'begin="{delay + dur:.2f}s"/></rect>')
    return clip, cursor


def text_at(x, y, text, size=11, cls="mute", anchor="start", extra=""):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}"{a}'
            f'{extra}>{text}</text>')


def bar(x, y, w, h, cls="ink", r=3.0):
    """Horizontal bar: rounded data-end on the right, square at the baseline."""
    if w <= 0.6:
        return ""
    r = min(r, h / 2.0, w)
    return (f'<path d="M{x:.1f} {y:.1f}H{x + w - r:.1f}'
            f'Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}'
            f'V{y + h - r:.1f}Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}'
            f'H{x:.1f}Z" class="{cls}"/>')


def draw_contributions(summary):
    """Hero number, the two secondary counts, and the weekly sparkline."""
    H = 148
    weekly = summary["weekly"] or [0]
    peak = max(weekly) or 1
    out = [svg_open(WIDTH, H)]
    out.append(f'<g opacity="0">{fade_in(0.10)}'
             + text_at(0, 50, summary["total"], 52, "strong", extra=' font-weight="600"')
             + text_at(0, 72, "contributions in the last year", 12) + '</g>')
    for i, (val, lab) in enumerate([(summary["active"], "active days"),
                                    (summary["best_week"], "best week")]):
        out.append(f'<g opacity="0">{fade_in(0.30 + i * 0.12)}'
                 + text_at(WIDTH, 30 + i * 40, val, 19, "strong", "end",
                         ' font-weight="600"')
                 + text_at(WIDTH, 47 + i * 40, lab, 11, "mute", "end") + '</g>')

    base, top = H - 10, H - 58
    span = base - top
    step = WIDTH / max(len(weekly) - 1, 1)
    pts = [(i * step, base - (v / peak) * span) for i, v in enumerate(weekly)]
    clip, cursor = reveal_wipe("rs", 0, top - 6, WIDTH, span + 8, 0.50)
    out.append(clip)
    out.append('<g clip-path="url(#rs)">')
    out.append(f'<path d="M{pts[0][0]:.1f} {base:.1f}'
             + "".join(f'L{x:.1f} {y:.1f}' for x, y in pts)
             + f'L{pts[-1][0]:.1f} {base:.1f}Z" class="wash"/>')
    out.append(f'<path d="M{pts[0][0]:.1f} {pts[0][1]:.1f}'
             + "".join(f'L{x:.1f} {y:.1f}' for x, y in pts[1:])
             + f'" class="ink-line" stroke-width="2" stroke-linejoin="round" '
             f'stroke-linecap="round"/>')
    out.append("</g>")
    out.append(cursor)
    ex, ey = pts[-1]
    out.append(f'<circle cx="{ex - 2:.1f}" cy="{ey:.1f}" r="4.5" class="strong halo" '
             f'stroke-width="2" opacity="0">{fade_in(0.50 + REVEAL, 0.35)}</circle>')
    out.append("</svg>")
    return "".join(out)


def draw_streaks(summary):
    """Current and longest streak, split by a hairline."""
    H = 96
    cells = []
    for k, lab in (("current", "current streak"), ("longest", "longest streak")):
        r = summary[k]
        span = (f"{day_label(r['start'])} &#8211; {day_label(r['end'])}"
                if r["length"] else "&#8212;")
        cells.append((r["length"], lab, span))

    out = [svg_open(WIDTH, H)]
    mid = WIDTH / 2
    out.append(f'<line x1="{mid:.0f}" y1="16" x2="{mid:.0f}" y2="80" '
             f'class="rule" stroke-width="1" opacity="0">{fade_in(0.20)}</line>')
    for i, (val, lab, span) in enumerate(cells):
        x = LEFT if i == 0 else mid + LEFT
        out.append(f'<g opacity="0">{fade_in(0.12 + i * 0.14)}'
                 + text_at(x, 44, f"{val}", 34, "strong", extra=' font-weight="600"')
                 + text_at(x, 64, lab, 11)
                 + text_at(x, 80, span, 10) + '</g>')
    out.append("</svg>")
    return "".join(out)


def draw_languages(summary):
    """Two small charts: share of bytes, and count of repos by main language."""
    rows = max(len(summary["by_size"]), len(summary["by_repo"]), 1)
    H = 26 + rows * 22 + 6
    colw = (WIDTH - LEFT - 30) / 2
    name_w, bar_max = 82, colw - 82 - 44

    out = [svg_open(WIDTH, H)]
    groups = [(LEFT, "by bytes", summary["by_size"], True),
              (LEFT + colw + 30, "by repos", summary["by_repo"], False)]
    for gi, (gx, title, ink, as_pct) in enumerate(groups):
        out.append(f'<g opacity="0">{fade_in(0.10 + gi * 0.10)}'
                 + text_at(gx, 12, title.upper(), 9, "mute",
                         extra=' letter-spacing="1.3"') + '</g>')
        if not ink:
            continue
        top = max(v for _, v in ink) or 1
        total = sum(v for _, v in ink) or 1
        clip_id = f"rl{gi}"
        clip, cursor = reveal_wipe(clip_id, gx + name_w, 20, bar_max, rows * 22,
                            0.34 + gi * 0.12, 0.95)
        out.append(clip)
        for ri, (name, val) in enumerate(ink):
            y = 26 + ri * 22
            shown = (f"{val / total * 100:.0f}%" if as_pct else f"{val}")
            out.append(f'<g opacity="0">{fade_in(0.24 + gi * 0.10 + ri * 0.05)}'
                     + text_at(gx, y + 8, name.lower()[:11], 11, "strong")
                     + text_at(gx + colw - 6, y + 8, shown, 11, "mute", "end")
                     + '</g>')
            out.append(f'<g clip-path="url(#{clip_id})">'
                     + bar(gx + name_w, y, bar_max * val / top, 7)
                     + '</g>')
        out.append(cursor)
    out.append("</svg>")
    return "".join(out)


# One pass of the red-green loop, in seconds. Every keyframe below is a
# wall-clock time inside this window; _keys turns them into SMIL fractions.
TDD_CYCLE = 12.0
TDD_CLEAR, TDD_BLANK = 9.20, 10.00   # transcript fades, then an empty beat


def _key_times(*times):
    return ";".join(f"{t / TDD_CYCLE:.4f}" for t in times)


def _cycle(attr, values, times):
    return (f'<animate attributeName="{attr}" values="{values}" '
            f'keyTimes="{_key_times(*times)}" dur="{TDD_CYCLE}s" '
            f'repeatCount="indefinite"/>')


def _fail_mark(x, cy):
    return (f'<path d="M{x} {cy - 4.5}l9 9M{x + 9} {cy - 4.5}l-9 9" '
            f'class="fail-line" stroke-width="1.9" stroke-linecap="round"/>')


def _pass_mark(x, cy):
    return (f'<path d="M{x} {cy}l3.4 3.6 6.4-8.4" class="pass-line" '
            f'stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round" fill="none"/>')


def draw_tdd():
    """The red-green loop, typing itself out and then starting over.

    GitHub strips <script> from a README, so "interactive" can only mean SMIL
    inside the SVG. Each line is revealed by a clipPath whose width is
    keyframed across one repeating cycle — that is what gives the typed feel,
    and it costs nothing to replay. Opacity keyframes clear the transcript
    before the cycle wraps, so the loop always restarts on an empty pane
    rather than snapping from full to empty miinkrame.

    The tick and cross are drawn as paths, not typed: U+2713 and U+2717 are
    outside the inlined latin subset and would fall back to whatever monospace
    the viewer happens to have.

    The scenario is the pivot of Robert C. Martin's bowling game kata. Rolls
    of 5, 5, 3 sum to 13, and summing is what the earlier tests in the kata
    let you get away with; the spare is the first case that sum() cannot
    fake, and it scores 16 — frame one is 10 plus the next roll, frame two
    is 3. The failing assertion is what forces the frame logic into
    existence, which is the whole argument for writing it first.

    Only characters in the inlined latin subset can appear here, so the test
    description uses a colon rather than an em dash.
    """
    FS, CW, H = 12.5, 12.5 * 0.6, 178
    out = [svg_open(WIDTH, H)]

    def span(x, y, text, cls):
        # xml:space is load-bearing: x advances by the character count, so the
        # leading spaces in a run have to survive into the rendered text or
        # the column drifts left by exactly the padding.
        return text_at(x, y, text, FS, cls, extra=' xml:space="preserve"')

    # Header: the label, and a phase badge that flips with the transcript.
    out.append(f'<g opacity="0">{fade_in(0.10)}'
             + text_at(LEFT, 16, "FIRST PRINCIPLES", 9, "mute",
                     extra=' letter-spacing="1.3"') + '</g>')
    for word, cls, on, off in (("RED", "fail", 3.55, 6.70),
                               ("GREEN", "pass", 6.70, TDD_CLEAR)):
        out.append('<g opacity="0">'
                 + _cycle("opacity", "0;0;1;1;0;0",
                         (0, on, on + 0.30, off, off + 0.40, TDD_CYCLE))
                 + text_at(WIDTH, 16, word, 9, cls, "end",
                         ' letter-spacing="1.3"') + '</g>')

    # Typed lines: (start, y, [(text, class), ...])
    typed_lines = [
        (0.30, 48, [("$ ", "mute"),
                    ("gradle test --tests BowlingGameTest", "strong")]),
        (1.90, 69, [("  spare, then a 3: the score is 16", "ink")]),
        (4.65, 129, [("+ ", "pass"),
                     ("if (isSpare(i)) score += 10 + rolls[i + 2];", "strong")]),
    ]
    for i, (start, y, parts) in enumerate(typed_lines):
        chars = sum(len(t) for t, _ in parts)
        w = chars * CW
        end = start + max(0.55, chars * 0.038)

        out.append(f'<clipPath id="tt{i}">'
                 f'<rect x="{LEFT}" y="{y - 14}" height="20" width="0">'
                 + _cycle("width", f"0;0;{w:.1f};{w:.1f}",
                         (0, start, end, TDD_CYCLE))
                 + '</rect></clipPath>')

        x = LEFT
        body = []
        for text, cls in parts:
            body.append(span(x, y, text, cls))
            x += len(text) * CW
        out.append(f'<g clip-path="url(#tt{i})">'
                 + _cycle("opacity", "1;1;0;0",
                         (0, TDD_CLEAR, TDD_BLANK, TDD_CYCLE))
                 + "".join(body) + '</g>')

        out.append(f'<rect y="{y - 12}" width="2" height="15" class="ink" '
                 f'opacity="0">'
                 + _cycle("x", f"{LEFT};{LEFT};{LEFT + w:.1f};{LEFT + w:.1f}",
                         (0, start, end, TDD_CYCLE))
                 + _cycle("opacity", "0;0;0.55;0.55;0;0",
                         (0, start - 0.08, start, end, end + 0.08, TDD_CYCLE))
                 + '</rect>')

    # Result lines: a drawn mark, then the verdict. No typing — a test result
    # arrives all at once.
    for at, y, mark, parts in (
            (3.55, 99, _fail_mark, [("FAIL", "fail"),
                                ("  expected 16, was 13", "mute")]),
            (6.70, 159, _pass_mark, [("PASS", "pass"),
                                 ("  5 tests, 0.02s", "mute")])):
        x = LEFT + 20
        body = []
        for text, cls in parts:
            body.append(span(x, y, text, cls))
            x += len(text) * CW
        out.append('<g opacity="0">'
                 + _cycle("opacity", "0;0;1;1;0;0",
                         (0, at, at + 0.30, TDD_CLEAR, TDD_BLANK, TDD_CYCLE))
                 + mark(LEFT, y - 4) + "".join(body) + '</g>')

    out.append("</svg>")
    return "".join(out)


def draw_heading(word):
    """A section heading in the mono face, with a hairline running right.

    GitHub strips <style> and style= from markdown, so a real markdown heading
    can only ever be GitHub's own sans. Rendering the label as an SVG is the
    only way to put the page's own typeface on it. The rule starts past the
    longest plausible advance (0.6em is the widest common monospace ratio), so
    a narrower font on the viewer's machine widens the gap slightly rather than
    colliding with the text.
    """
    FS = 16
    H = 26
    text_end = len(word) * FS * 0.6 + 18
    out = [svg_open(WIDTH, H, font=heading_font())]
    out.append(text_at(0, 18, word, FS, "strong", extra=' font-weight="600"'))
    out.append(f'<line x1="{text_end:.0f}" y1="12.5" x2="{WIDTH}" y2="12.5" '
             f'class="rule" stroke-width="1"/>')
    out.append("</svg>")
    return "".join(out)


def draw_year_map(summary):
    """Seven rows by fifty-three weeks, intensity as a character."""
    FS, LH, COLW = 9.2, 11.0, 2
    CW = FS * 0.6
    pad_l, pad_t = LEFT, 44
    weeks = summary["weeks"]
    ncols = len(weeks) * COLW
    H = int(pad_t + 7 * LH + 26)

    def level(v):
        for i, cut in enumerate((0, 2, 5, 9)):
            if v <= cut:
                return i
        return 4

    # A window label rather than a count: the graphic already says how full
    # the year is, and saying it twice turns a texture into a score.
    span = (f"{month_label(weeks[0][0]['date'])} &#8211; "
            f"{month_label(weeks[-1][-1]['date'])}") if weeks else ""

    out = [svg_open(WIDTH, H)]
    out.append(f'<g opacity="0">{fade_in(0.10)}'
             + text_at(pad_l, 16, "THE YEAR", 9, "mute",
                     extra=' letter-spacing="1.3"')
             + text_at(pad_l, 32, span, 11)
             + '</g>')

    # ramp legend, so the encoding is never carried by shade alone
    lx = WIDTH - 6
    out.append(f'<g opacity="0">{fade_in(1.30)}'
             + text_at(lx - 78, 32, "less", 9, "mute", "end")
             + f'<text xml:space="preserve" x="{lx - 72}" y="32" class="ink" '
             f'font-size="{FS}">{" ".join(RAMP[1:])}</text>'
             + text_at(lx, 32, "more", 9, "mute", "end") + '</g>')

    for r in range(7):
        chars = []
        for w in weeks:
            day = next((d for d in w if d.get("weekday") == r), None)
            v = day["contributionCount"] if day else 0
            chars.append(RAMP[level(v)] * COLW)
        line = "".join(chars).rstrip()
        if not line:
            continue
        y = pad_t + r * LH
        w_px = max(len(line), 1) * CW
        clip_id = f"ry{r}"
        delay = 0.30 + r * 0.07
        out.append(f'<clipPath id="{clip_id}"><rect x="{pad_l}" y="{y}" '
                 f'height="{LH}" width="0"><animate attributeName="width" '
                 f'from="0" to="{w_px:.1f}" begin="{delay:.2f}s" dur="0.40s" '
                 f'fill="freeze"/></rect></clipPath>')
        safe = line.replace("&", "&amp;").replace("<", "&lt;")
        out.append(f'<g clip-path="url(#{clip_id})"><text xml:space="preserve" '
                 f'x="{pad_l}" y="{y + FS - 0.6:.1f}" class="ink" '
                 f'font-size="{FS}">{safe}</text></g>')

    for r, lab in ((1, "mon"), (3, "wed"), (5, "fri")):
        out.append(text_at(pad_l - 7, pad_t + r * LH + FS - 0.6, lab, 9, "mute",
                       "end"))

    last_m, last_x = None, -999.0
    base_y = pad_t + 7 * LH + 13
    for i, w in enumerate(weeks):
        m = int(w[0]["date"][5:7])
        x = pad_l + i * COLW * CW
        if m != last_m and i < len(weeks) - 1 and x - last_x >= 34:
            out.append(text_at(x, base_y, MONTHS[m - 1], 9, "mute"))
            last_x = x
        last_m = m

    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- main

def write_if_changed(path, svg):
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old == svg:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return True


# The page's sections, in order. Each becomes hd-<word>.svg.
HEADINGS = ("about", "stack", "vibecoding tools", "currently", "socials")

# Data graphics to draw. Empty, so no token and no network call is needed.
# Add a name here — and its <img> to the README — to switch one back on.
DATA_PANELS = ()


def main():
    out_dir = os.environ.get("OUT_DIR", ".")
    files = {f"hd-{w.replace(' ', '-')}.svg": draw_heading(w)
             for w in HEADINGS}
    files["tdd.svg"] = draw_tdd()

    if DATA_PANELS:
        drawers = {"stats.svg": draw_contributions, "streak.svg": draw_streaks,
                   "langs.svg": draw_languages, "year.svg": draw_year_map}
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN is not set")
        summary = summarise_profile(fetch_profile(os.environ.get("GH_LOGIN", "pixelpeg"), token))
        files.update({n: drawers[n](summary) for n in DATA_PANELS})

    changed = [n for n, svg in files.items()
               if write_if_changed(os.path.join(out_dir, n), svg)]
    print("updated: " + (", ".join(sorted(changed)) if changed else "nothing"))


if __name__ == "__main__":
    main()
