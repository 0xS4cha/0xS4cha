#!/usr/bin/env python3

import base64
import functools
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    followers { totalCount }
    following { totalCount }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date weekday } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 privacy: PUBLIC) {
      nodes {
        name
        stargazerCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

LIGHT = dict(data="#6e7681", emph="#424a53", dim="#8c959f",
             rule="#d8dee4", surface="#ffffff")
DARK = dict(data="#c9d1d9", emph="#f0f6fc", dim="#8b949e",
            rule="#30363d", surface="#0d1117")
MONO = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "&apos;Liberation Mono&apos;,monospace")
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


@functools.lru_cache(maxsize=None)
def face(filename, weight):
    """One @font-face rule with the subset inlined as a data URI.

    An external font URL cannot work here: these SVGs are loaded through <img>,
    and browsers refuse to fetch subresources for an image document. Inlining is
    also what pins the advance width — the portrait's grid assumes 0.600 em, and
    a viewer whose default monospace is narrower would otherwise see it squeezed.
    """
    with open(os.path.join(FONT_DIR, filename), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (f"@font-face{{font-family:JBMono;font-style:normal;"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def font_text():
    """Basic latin, both weights — for the data graphics."""
    return face("jbmono-400.woff2", 400) + face("jbmono-600.woff2", 600)


def font_head():
    """Only the letters the section headings use."""
    return face("jbmono-head.woff2", 600)


WIDTH = 620
LEFT = 34
REVEAL = 1.30
RAMP = [" ", ":", "+", "#", "@"]
MON = ["jan", "feb", "mar", "apr", "may", "jun",
       "jul", "aug", "sep", "oct", "nov", "dec"]


ABOUT = dict(
    name=os.environ.get("GH_LOGIN", "0xS4cha"),
    title="Freelance developer",
    bio=[
        "Passionate about FiveM development, currently studying at 42.",
        "Fascinated by astronomy, science",
        "and everything that pushes the boundaries of technology."
    ],
    facts=[
        ("based in", "Paris &amp; Lyon, FR"),
        ("focus", "AI &amp; Data science"),
        ("working on", "42 Common core"),
        ("reachable at", "sservant@student.42lyon.fr"),
    ],
    tags=[
        "python", "rust", "lua/luau", "react",
        "typescript", "docker", "SQL"],
)


def window():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    return (f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z")


def fetch(login, token):
    since, until = window()
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


def pretty(iso):
    d = date.fromisoformat(iso)
    return f"{MON[d.month - 1]} {d.day}"


def streaks(days):
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


def languages(repos):
    by_size, by_repo = {}, {}
    for node in repos:
        edges = (node.get("languages") or {}).get("edges") or []
        for e in edges:
            name = e["node"]["name"]
            by_size[name] = by_size.get(name, 0) + e["size"]
        if edges:
            top = edges[0]["node"]["name"]
            by_repo[top] = by_repo.get(top, 0) + 1

    def rank(d):
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    return rank(by_size), rank(by_repo)


def top_repos(repos, n=5):
    """Highest-starred public repos, each with its primary language.

    Ties broken by name so the ranking never reshuffles between runs when
    two repos share a star count.
    """
    rows = []
    for node in repos:
        edges = (node.get("languages") or {}).get("edges") or []
        lang = edges[0]["node"]["name"] if edges else ""
        rows.append((node.get("name", ""), node.get("stargazerCount", 0), lang))
    return sorted(rows, key=lambda r: (-r[1], r[0]))[:n]


def weekday_totals(days):
    """Contributions summed by weekday, Monday first.

    GitHub's `weekday` is 0=Sunday, so it's rotated here to a Monday-first
    order to match how the year map and most calendars read.
    """
    totals = [0] * 7
    for d in days:
        totals[(d["weekday"] - 1) % 7] += d["contributionCount"]
    return totals


def month_totals(days):
    """Contributions summed by calendar month, oldest to newest.

    Keeps insertion order (rather than sorting keys) so the chart reads
    chronologically left-to-right instead of alphabetically.
    """
    totals, order = {}, []
    for d in days:
        m = d["date"][:7]
        if m not in totals:
            totals[m] = 0
            order.append(m)
        totals[m] += d["contributionCount"]
    return [(m, totals[m]) for m in order]


def activity_breakdown(cc):
    """Commits / PRs / reviews / issues opened in the window, high to low."""
    rows = [
        ("commits", cc.get("totalCommitContributions", 0)),
        ("pull requests", cc.get("totalPullRequestContributions", 0)),
        ("reviews", cc.get("totalPullRequestReviewContributions", 0)),
        ("issues", cc.get("totalIssueContributions", 0)),
    ]
    return sorted(rows, key=lambda kv: -kv[1])


def summarise(user):
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = [w["contributionDays"] for w in cal["weeks"]]
    days = [d for w in weeks for d in w]
    weekly = [sum(d["contributionCount"] for d in w) for w in weeks]
    cur, best = streaks(days)
    repos = user["repositories"]["nodes"]
    by_size, by_repo = languages(repos)
    return dict(
        total=cal["totalContributions"],
        active=sum(1 for d in days if d["contributionCount"] > 0),
        best_week=max(weekly) if weekly else 0,
        weekly=weekly, weeks=weeks,
        current=cur, longest=best,
        by_size=by_size, by_repo=by_repo,
        top_repos=top_repos(repos),
        by_weekday=weekday_totals(days),
        by_month=month_totals(days),
        activity=activity_breakdown(user["contributionsCollection"]),
        followers=user["followers"]["totalCount"],
        following=user["following"]["totalCount"],
        stars=sum(r.get("stargazerCount", 0) for r in repos))


def style(extra="", font=None):
    def block(t):
        return (f".d-f{{fill:{t['data']}}}.d-s{{stroke:{t['data']}}}"
                f".e-f{{fill:{t['emph']}}}.m-f{{fill:{t['dim']}}}"
                f".u-s{{stroke:{t['rule']}}}.r{{stroke:{t['surface']}}}")
    return (f"<style>{font or font_text()}"
            f"{block(LIGHT)}.w{{fill:{LIGHT['data']};opacity:.13}}{extra}"
            f"@media(prefers-color-scheme:dark){{{block(DARK)}"
            f".w{{fill:{DARK['data']};opacity:.16}}}}</style>")


def head(w, h, font=None):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" fill="none" font-family="{MONO}">'
            + style(font=font))


def fade(delay, dur=0.45):
    return (f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>')


def wipe(cid, x, y, w, h, delay, dur=REVEAL):
    """clipPath reveal plus the cursor block that rides its edge."""
    clip = (f'<clipPath id="{cid}"><rect x="{x}" y="{y}" height="{h}" width="0">'
            f'<animate attributeName="width" from="0" to="{w}" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/></rect></clipPath>')
    cursor = (f'<rect y="{y}" width="2" height="{h}" class="d-f" opacity="0">'
              f'<animate attributeName="x" from="{x}" to="{x + w}" '
              f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>'
              f'<set attributeName="opacity" to="0.55" begin="{delay:.2f}s"/>'
              f'<set attributeName="opacity" to="0" '
              f'begin="{delay + dur:.2f}s"/></rect>')
    return clip, cursor


def label(x, y, text, size=11, cls="m-f", anchor="start", extra=""):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}"{a}'
            f'{extra}>{text}</text>')


def hbar(x, y, w, h, cls="d-f", r=3.0):
    """Horizontal bar: rounded data-end on the right, square at the baseline."""
    if w <= 0.6:
        return ""
    r = min(r, h / 2.0, w)
    return (f'<path d="M{x:.1f} {y:.1f}H{x + w - r:.1f}'
            f'Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}'
            f'V{y + h - r:.1f}Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}'
            f'H{x:.1f}Z" class="{cls}"/>')


def kv(x, y, k, v, size=11):
    """One 'label  value' line, label dim and value emphasised, same text node
    so the two never drift out of baseline alignment."""
    return (f'<text x="{x}" y="{y}" font-size="{size}">'
            f'<tspan class="m-f">{k}</tspan>'
            f'<tspan class="e-f" dx="6">{v}</tspan></text>')


def _advance(text, fs):
    """Rough monospace advance width, for layout math only (never per-glyph
    kerning) — the same 0.6em ratio draw_heading and draw_year already
    assume for this font."""
    return len(str(text)) * fs * 0.6


def _flow(items, x0, y0, max_w, h=20, gap_x=8, gap_y=10, pad_x=10, fs=10):
    """Left-to-right layout that wraps to a new row once max_w is exceeded.

    Returns (placed, bottom_y): placed is a list of (text, x, y, w) and
    bottom_y is where the last row ends, so callers can size their canvas
    to however many rows the tag list happened to need.
    """
    placed, x, y, started = [], x0, y0, False
    for text in items:
        w = _advance(text, fs) + pad_x * 2
        if started and x + w > x0 + max_w:
            x, y = x0, y + h + gap_y
        placed.append((text, x, y, w))
        x += w + gap_x
        started = True
    return placed, (y + h if placed else y0)


def draw_stats(s):
    """Hero number, the two secondary counts, and the weekly sparkline."""
    H = 148
    weekly = s["weekly"] or [0]
    peak = max(weekly) or 1
    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(0, 50, s["total"], 52, "e-f", extra=' font-weight="600"')
             + label(0, 72, "contributions in the last year", 12) + '</g>')
    for i, (val, lab) in enumerate([(s["active"], "active days"),
                                    (s["best_week"], "best week")]):
        p.append(f'<g opacity="0">{fade(0.30 + i * 0.12)}'
                 + label(WIDTH, 30 + i * 40, val, 19, "e-f", "end",
                         ' font-weight="600"')
                 + label(WIDTH, 47 + i * 40, lab, 11, "m-f", "end") + '</g>')

    base, top = H - 10, H - 58
    span = base - top
    step = WIDTH / max(len(weekly) - 1, 1)
    pts = [(i * step, base - (v / peak) * span) for i, v in enumerate(weekly)]
    clip, cursor = wipe("rs", 0, top - 6, WIDTH, span + 8, 0.50)
    p.append(clip)
    p.append('<g clip-path="url(#rs)">')
    p.append(f'<path d="M{pts[0][0]:.1f} {base:.1f}'
             + "".join(f'L{x:.1f} {y:.1f}' for x, y in pts)
             + f'L{pts[-1][0]:.1f} {base:.1f}Z" class="w"/>')
    p.append(f'<path d="M{pts[0][0]:.1f} {pts[0][1]:.1f}'
             + "".join(f'L{x:.1f} {y:.1f}' for x, y in pts[1:])
             + f'" class="d-s" stroke-width="2" stroke-linejoin="round" '
             f'stroke-linecap="round"/>')
    p.append("</g>")
    p.append(cursor)
    ex, ey = pts[-1]
    p.append(f'<circle cx="{ex - 2:.1f}" cy="{ey:.1f}" r="4.5" class="e-f r" '
             f'stroke-width="2" opacity="0">{fade(0.50 + REVEAL, 0.35)}</circle>')
    p.append("</svg>")
    return "".join(p)


def draw_streak(s):
    """Current and longest streak, split by a hairline."""
    H = 96
    cells = []
    for k, lab in (("current", "current streak"), ("longest", "longest streak")):
        r = s[k]
        span = (f"{pretty(r['start'])} &#8211; {pretty(r['end'])}"
                if r["length"] else "&#8212;")
        cells.append((r["length"], lab, span))

    p = [head(WIDTH, H)]
    mid = WIDTH / 2
    p.append(f'<line x1="{mid:.0f}" y1="16" x2="{mid:.0f}" y2="80" '
             f'class="u-s" stroke-width="1" opacity="0">{fade(0.20)}</line>')
    for i, (val, lab, span) in enumerate(cells):
        x = LEFT if i == 0 else mid + LEFT
        p.append(f'<g opacity="0">{fade(0.12 + i * 0.14)}'
                 + label(x, 44, f"{val}", 34, "e-f", extra=' font-weight="600"')
                 + label(x, 64, lab, 11)
                 + label(x, 80, span, 10) + '</g>')
    p.append("</svg>")
    return "".join(p)


def draw_social(s):
    """Followers, following, and stars earned across public repos.

    Three columns instead of draw_streak's two: x = colw*i + LEFT still
    lands the first column at LEFT and later ones past each hairline,
    exactly as it does for the two-column case.
    """
    H = 96
    cells = [(s["followers"], "followers"),
             (s["following"], "following"),
             (s["stars"], "stars earned")]
    n = len(cells)
    colw = WIDTH / n

    p = [head(WIDTH, H)]
    for i in range(1, n):
        x = colw * i
        p.append(f'<line x1="{x:.0f}" y1="16" x2="{x:.0f}" y2="80" '
                 f'class="u-s" stroke-width="1" opacity="0">{fade(0.20)}</line>')
    for i, (val, lab) in enumerate(cells):
        x = colw * i + LEFT
        p.append(f'<g opacity="0">{fade(0.12 + i * 0.14)}'
                 + label(x, 44, f"{val}", 30, "e-f", extra=' font-weight="600"')
                 + label(x, 64, lab, 11) + '</g>')
    p.append("</svg>")
    return "".join(p)


def draw_activity(s):
    """Contribution mix: commits, pull requests, reviews, issues."""
    rows = s["activity"]
    H = 20 + max(len(rows), 1) * 24 + 6
    name_w, val_w = 130, 44
    bar_max = WIDTH - LEFT - name_w - val_w - 10

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(LEFT, 12, "CONTRIBUTION MIX", 9, "m-f",
                     extra=' letter-spacing="1.3"') + '</g>')
    top = max((v for _, v in rows), default=0) or 1
    clip, cursor = wipe("ra", LEFT + name_w, 20, bar_max,
                        len(rows) * 24, 0.34, 1.05)
    p.append(clip)
    for i, (name, val) in enumerate(rows):
        y = 24 + i * 24
        p.append(f'<g opacity="0">{fade(0.24 + i * 0.06)}'
                 + label(LEFT, y + 8, name, 11, "e-f")
                 + label(WIDTH, y + 8, f"{val}", 11, "m-f", "end") + '</g>')
        p.append(f'<g clip-path="url(#ra)">'
                 + hbar(LEFT + name_w, y, bar_max * val / top, 7)
                 + '</g>')
    p.append(cursor)
    p.append("</svg>")
    return "".join(p)


def draw_months(s):
    """Contributions summed by calendar month over the trailing year."""
    rows = s["by_month"]
    H = 20 + max(len(rows), 1) * 20 + 6
    name_w, val_w = 60, 34
    bar_max = WIDTH - LEFT - name_w - val_w - 10

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(LEFT, 12, "BY MONTH", 9, "m-f",
                     extra=' letter-spacing="1.3"') + '</g>')
    if not rows:
        p.append("</svg>")
        return "".join(p)

    top = max(v for _, v in rows) or 1
    clip, cursor = wipe("rm", LEFT + name_w, 20, bar_max,
                        len(rows) * 20, 0.34, 1.05)
    p.append(clip)
    for i, (m, val) in enumerate(rows):
        y = 22 + i * 20
        yy, mm = m.split("-")
        lab = MON[int(mm) - 1] + (f" &#8217;{yy[2:]}" if mm == "01" or i == 0 else "")
        p.append(f'<g opacity="0">{fade(0.24 + i * 0.05)}'
                 + label(LEFT, y + 8, lab, 11)
                 + label(WIDTH, y + 8, f"{val}", 11, "m-f", "end") + '</g>')
        p.append(f'<g clip-path="url(#rm)">'
                 + hbar(LEFT + name_w, y, bar_max * val / top, 7)
                 + '</g>')
    p.append(cursor)
    p.append("</svg>")
    return "".join(p)


def draw_langs(s):
    """Two small charts: share of bytes, and count of repos by main language."""
    rows = max(len(s["by_size"]), len(s["by_repo"]), 1)
    H = 26 + rows * 22 + 6
    colw = (WIDTH - LEFT - 30) / 2
    name_w, bar_max = 82, colw - 82 - 44

    p = [head(WIDTH, H)]
    groups = [(LEFT, "by bytes", s["by_size"], True),
              (LEFT + colw + 30, "by repos", s["by_repo"], False)]
    for gi, (gx, title, data, as_pct) in enumerate(groups):
        p.append(f'<g opacity="0">{fade(0.10 + gi * 0.10)}'
                 + label(gx, 12, title.upper(), 9, "m-f",
                         extra=' letter-spacing="1.3"') + '</g>')
        if not data:
            continue
        top = max(v for _, v in data) or 1
        total = sum(v for _, v in data) or 1
        cid = f"rl{gi}"
        clip, cursor = wipe(cid, gx + name_w, 20, bar_max, rows * 22,
                            0.34 + gi * 0.12, 0.95)
        p.append(clip)
        for ri, (name, val) in enumerate(data):
            y = 26 + ri * 22
            shown = (f"{val / total * 100:.0f}%" if as_pct else f"{val}")
            p.append(f'<g opacity="0">{fade(0.24 + gi * 0.10 + ri * 0.05)}'
                     + label(gx, y + 8, name.lower()[:11], 11, "e-f")
                     + label(gx + colw - 6, y + 8, shown, 11, "m-f", "end")
                     + '</g>')
            p.append(f'<g clip-path="url(#{cid})">'
                     + hbar(gx + name_w, y, bar_max * val / top, 7)
                     + '</g>')
        p.append(cursor)
    p.append("</svg>")
    return "".join(p)


def draw_repos(s):
    """Top starred public repos, one bar each, language noted in dim ink."""
    rows = s["top_repos"]
    H = 20 + max(len(rows), 1) * 24 + 6
    name_w, val_w = 210, 34
    bar_max = WIDTH - LEFT - name_w - val_w - 10

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(LEFT, 12, "TOP REPOS", 9, "m-f",
                     extra=' letter-spacing="1.3"') + '</g>')
    if not rows:
        p.append("</svg>")
        return "".join(p)

    top = max(stars for _, stars, _ in rows) or 1
    clip, cursor = wipe("rr", LEFT + name_w, 20, bar_max,
                        len(rows) * 24, 0.34, 1.05)
    p.append(clip)
    for i, (name, stars, lang) in enumerate(rows):
        y = 24 + i * 24
        tag = f'  <tspan class="m-f" font-size="10">{lang.lower()}</tspan>' if lang else ""
        p.append(f'<g opacity="0">{fade(0.24 + i * 0.06)}'
                 + label(LEFT, y + 8, name[:22] + tag, 11, "e-f")
                 + label(WIDTH, y + 8, f"&#9733; {stars}", 11, "m-f", "end")
                 + '</g>')
        p.append(f'<g clip-path="url(#rr)">'
                 + hbar(LEFT + name_w, y, bar_max * stars / top, 7)
                 + '</g>')
    p.append(cursor)
    p.append("</svg>")
    return "".join(p)


def draw_weekday(s):
    """Contributions summed by weekday, Monday first — where the week lands."""
    labels = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    totals = s["by_weekday"]
    H = 20 + 7 * 20 + 6
    name_w, val_w = 40, 34
    bar_max = WIDTH - LEFT - name_w - val_w - 10

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(LEFT, 12, "BY WEEKDAY", 9, "m-f",
                     extra=' letter-spacing="1.3"') + '</g>')
    top = max(totals) or 1
    clip, cursor = wipe("rw", LEFT + name_w, 20, bar_max, 7 * 20, 0.34, 1.05)
    p.append(clip)
    for i, (lab, val) in enumerate(zip(labels, totals)):
        y = 22 + i * 20
        cls = "e-f" if val == top and val else "m-f"
        p.append(f'<g opacity="0">{fade(0.24 + i * 0.05)}'
                 + label(LEFT, y + 8, lab, 11, cls)
                 + label(WIDTH, y + 8, f"{val}", 11, "m-f", "end") + '</g>')
        p.append(f'<g clip-path="url(#rw)">'
                 + hbar(LEFT + name_w, y, bar_max * val / top, 7)
                 + '</g>')
    p.append(cursor)
    p.append("</svg>")
    return "".join(p)


def draw_about(cfg=ABOUT):
    """Static profile card: name, bio, quick facts, and a tag cloud.

    Nothing here is fetched from the API — it all comes straight from the
    ABOUT dict above — so every block sizes itself to whatever's actually
    in it rather than assuming a fixed line or tag count. Add a tenth fact
    or a thirtieth tag and the card just grows to fit.
    """
    name = cfg["name"]
    title = cfg.get("title", "")
    bio = cfg.get("bio", [])
    facts = cfg.get("facts", [])
    tags = cfg.get("tags", [])

    NAME_FS, BIO_LH, FACT_LH, TAG_H, TAG_GAP = 26, 18, 20, 20, 10
    y_name = 32
    y = y_name + 14

    bio_start = y + 12
    if bio:
        y = bio_start + len(bio) * BIO_LH

    facts_start = y + (14 if bio else 6)
    fact_rows = -(-len(facts) // 2)
    if facts:
        y = facts_start + fact_rows * FACT_LH

    tags_start = y + (14 if facts else 6)
    tag_rows, tags_bottom = ((_flow(tags, LEFT, tags_start,
                                    WIDTH - LEFT - 6, h=TAG_H, gap_y=TAG_GAP))
                            if tags else ([], tags_start))

    H = int((tags_bottom if tags else y) + 14)

    d_name, d_title = 0.10, 0.24
    d_bio = d_title + 0.14
    d_facts = d_bio + (len(bio) * 0.08 + 0.14 if bio else 0)
    d_tags = d_facts + (fact_rows * 0.06 + 0.14 if facts else 0)

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(d_name)}'
             + label(0, y_name, name, NAME_FS, "e-f",
                     extra=' font-weight="600"') + '</g>')
    if title:
        tx = _advance(name, NAME_FS) + 14
        p.append(f'<g opacity="0">{fade(d_title)}'
                 + label(tx, y_name, title, 13) + '</g>')

    for i, line in enumerate(bio):
        p.append(f'<g opacity="0">{fade(d_bio + i * 0.08)}'
                 + label(0, bio_start + i * BIO_LH, line, 12) + '</g>')

    if facts:
        colw = (WIDTH - LEFT) / 2
        for i, (k, v) in enumerate(facts):
            col, row = i % 2, i // 2
            x = LEFT if col == 0 else LEFT + colw
            fy = facts_start + row * FACT_LH
            p.append(f'<g opacity="0">{fade(d_facts + row * 0.06)}'
                     + kv(x, fy, k, v) + '</g>')

    for i, (text, x, ty, w) in enumerate(tag_rows):
        p.append(f'<g opacity="0">{fade(d_tags + i * 0.045)}'
                 f'<rect x="{x:.1f}" y="{ty:.1f}" width="{w:.1f}" '
                 f'height="{TAG_H}" rx="{TAG_H / 2:.0f}" fill="none" '
                 f'class="u-s" stroke-width="1"/>'
                 f'<text x="{x + w / 2:.1f}" y="{ty + TAG_H * 0.67:.1f}" '
                 f'font-size="10" class="d-f" text-anchor="middle">'
                 f'{text}</text></g>')

    p.append("</svg>")
    return "".join(p)


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
    p = [head(WIDTH, H, font=font_head())]
    p.append(label(0, 18, word, FS, "e-f", extra=' font-weight="600"'))
    p.append(f'<line x1="{text_end:.0f}" y1="12.5" x2="{WIDTH}" y2="12.5" '
             f'class="u-s" stroke-width="1"/>')
    p.append("</svg>")
    return "".join(p)


def draw_year(s):
    """Seven rows by fifty-three weeks, intensity as a character."""
    FS, LH, COLW = 9.2, 11.0, 2
    CW = FS * 0.6
    pad_l, pad_t = LEFT, 44
    weeks = s["weeks"]
    H = int(pad_t + 7 * LH + 26)

    def level(v):
        for i, cut in enumerate((0, 2, 5, 9)):
            if v <= cut:
                return i
        return 4

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(pad_l, 16, "THE YEAR", 9, "m-f",
                     extra=' letter-spacing="1.3"')
             + label(pad_l, 32, f"{s['active']} of "
                     f"{sum(len(w) for w in weeks)} days had a contribution", 11)
             + '</g>')

    lx = WIDTH - 6
    p.append(f'<g opacity="0">{fade(1.30)}'
             + label(lx - 78, 32, "less", 9, "m-f", "end")
             + f'<text xml:space="preserve" x="{lx - 72}" y="32" class="d-f" '
             f'font-size="{FS}">{" ".join(RAMP[1:])}</text>'
             + label(lx, 32, "more", 9, "m-f", "end") + '</g>')

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
        cid = f"ry{r}"
        delay = 0.30 + r * 0.07
        p.append(f'<clipPath id="{cid}"><rect x="{pad_l}" y="{y}" '
                 f'height="{LH}" width="0"><animate attributeName="width" '
                 f'from="0" to="{w_px:.1f}" begin="{delay:.2f}s" dur="0.40s" '
                 f'fill="freeze"/></rect></clipPath>')
        safe = line.replace("&", "&amp;").replace("<", "&lt;")
        p.append(f'<g clip-path="url(#{cid})"><text xml:space="preserve" '
                 f'x="{pad_l}" y="{y + FS - 0.6:.1f}" class="d-f" '
                 f'font-size="{FS}">{safe}</text></g>')

    for r, lab in ((1, "mon"), (3, "wed"), (5, "fri")):
        p.append(label(pad_l - 7, pad_t + r * LH + FS - 0.6, lab, 9, "m-f",
                       "end"))

    last_m, last_x = None, -999.0
    base_y = pad_t + 7 * LH + 13
    for i, w in enumerate(weeks):
        m = int(w[0]["date"][5:7])
        x = pad_l + i * COLW * CW
        if m != last_m and i < len(weeks) - 1 and x - last_x >= 34:
            p.append(label(x, base_y, MON[m - 1], 9, "m-f"))
            last_x = x
        last_m = m

    p.append("</svg>")
    return "".join(p)


def write(path, svg):
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old == svg:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return True


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    login = os.environ.get("GH_LOGIN", "0xS4cha")
    out_dir = os.environ.get("OUT_DIR", ".")

    s = summarise(fetch(login, token))
    files = {"stats.svg": draw_stats(s), "streak.svg": draw_streak(s),
             "langs.svg": draw_langs(s), "year.svg": draw_year(s),
             "repos.svg": draw_repos(s), "weekday.svg": draw_weekday(s),
             "months.svg": draw_months(s), "activity.svg": draw_activity(s),
             "social.svg": draw_social(s), "about.svg": draw_about()}
    for word in ("about", "stack", "activity", "projects", "social",
                 "stats", "about this page"):
        files[f"hd-{word.replace(' ', '-')}.svg"] = draw_heading(word)

    changed = [n for n, svg in files.items()
               if write(os.path.join(out_dir, n), svg)]
    print(f"{s['total']} contributions, {s['active']} active days, "
          f"best week {s['best_week']}, current streak "
          f"{s['current']['length']}, longest {s['longest']['length']}")
    print("languages by bytes: "
          + ", ".join(f"{n} {v}" for n, v in s["by_size"]))
    print("updated: " + (", ".join(sorted(changed)) if changed else "nothing"))


if __name__ == "__main__":
    main()