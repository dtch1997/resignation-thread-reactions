#!/usr/bin/env python3
"""Render the response-taxonomy results as a self-contained HTML page (Claude artifact).

    ./build_artifact.py [--out ../../../jarvis-artifacts/x-resignation-reactions/index.html]

Reads data/<id>/taxonomy.json, taxonomy_results.jsonl (from `taxonomy.py report`),
labels.jsonl and all_posts.jsonl. Everything is inlined; no external scripts.
"""
from __future__ import annotations

import argparse
import html
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
POST_URL = f"https://x.com/hilbertspaess/status/{ROOT_ID}"


def rows(p: Path):
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                yield json.loads(line)


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def fmt_int(n: int) -> str:
    return f"{n:,}"


def pick_examples(rs: list[dict], k: int = 3, seed: int = 0) -> list[dict]:
    """One top-liked post plus random confident ones, favouring readable length."""
    rng = random.Random(seed)
    good = [r for r in rs if r["confidence"] >= 0.75 and 30 <= len(r["text"]) <= 320]
    pool = good or rs
    pool = sorted(pool, key=lambda r: -r["likes"])
    out = pool[:1]
    rest = [r for r in pool[1:] if r["id"] not in {o["id"] for o in out}]
    en = [r for r in rest if r.get("lang") == "en"]
    rng.shuffle(en); rng.shuffle(rest)
    for cand in en + rest:
        if len(out) >= k:
            break
        if cand["id"] not in {o["id"] for o in out}:
            out.append(cand)
    return out


def bar_svg(series: list[tuple[str, float, float]], max_v: float, height_per: int = 26) -> str:
    """Horizontal paired bars: (label, reply%, quote%)."""
    w, lw, pad = 720, 250, 10
    plot_w = w - lw - 70
    rows_svg = []
    for i, (label, a, b) in enumerate(series):
        y = i * height_per + pad
        ax = plot_w * a / max_v
        bx = plot_w * b / max_v
        rows_svg.append(
            f'<text x="{lw-10}" y="{y+16}" text-anchor="end" class="axis-label">{esc(label)}</text>'
            f'<rect class="bar bar-reply" x="{lw}" y="{y+2}" width="{ax:.1f}" height="9" rx="2"><title>share of posts: {a:.1f}%</title></rect>'
            f'<rect class="bar bar-quote" x="{lw}" y="{y+13}" width="{bx:.1f}" height="9" rx="2"><title>share of like-mass: {b:.1f}%</title></rect>'
            f'<text x="{lw+ax+6:.1f}" y="{y+10}" class="val">{a:.0f}%</text>'
            f'<text x="{lw+bx+6:.1f}" y="{y+21}" class="val">{b:.0f}%</text>'
        )
    h = len(series) * height_per + 2 * pad
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="category shares by venue">{"".join(rows_svg)}</svg>'


def strip_svg(parts: list[tuple[str, float, str]], width: int = 720) -> str:
    """Stacked 100% strip: (label, pct, css-class)."""
    x = 0.0
    segs, labels = [], []
    for label, pct, cls in parts:
        w = width * pct / 100
        segs.append(f'<rect class="{cls}" x="{x:.1f}" y="0" width="{max(0,w-2):.1f}" height="18" rx="2"><title>{esc(label)}: {pct:.1f}%</title></rect>')
        if w > 60:
            labels.append(f'<text x="{x+w/2:.1f}" y="13" text-anchor="middle" class="strip-label">{esc(label)} {pct:.0f}%</text>')
        x += w
    return f'<svg viewBox="0 0 {width} 18" width="100%" role="img">{"".join(segs)}{"".join(labels)}</svg>'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).parents[3] / "jarvis-artifacts" / "x-resignation-reactions" / "index.html")
    args = ap.parse_args()

    tax = json.loads((DATA / "taxonomy.json").read_text())
    root = json.loads((DATA / "root.json").read_text())
    rm = root["data"]["public_metrics"]
    posts = {t["id"]: t for t in rows(DATA / "all_posts.jsonl")}
    labels = {l["id"]: l for l in rows(DATA / "labels.jsonl") if "error" not in l}
    items = [r for r in rows(DATA / "taxonomy_results.jsonl")]
    for r in items:
        r["lang"] = posts[r["id"]].get("lang")
        r["gist"] = labels.get(r["id"], {}).get("summary", "")
        r["stance"] = labels.get(r["id"], {}).get("stance_author")
        r["claim"] = labels.get(r["id"], {}).get("stance_claim")
    n_reply = sum(r["kind"] == "reply" for r in items)
    n_quote = sum(r["kind"] == "quote" for r in items)
    n_all = len(items)
    likemass = {k: sum(1 + r["likes"] for r in items if k == "all" or r["kind"] == k) for k in ("reply", "quote", "all")}
    n_spam = sum(1 for l in labels.values() if l["is_bot_or_spam"] and posts.get(l["id"], {}).get("kind") in ("reply", "quote"))
    n_retweets = sum(1 for t in posts.values() if t["kind"] == "retweet")

    def share(pred, kind="all", weighted=False):
        sel = [r for r in items if (kind == "all" or r["kind"] == kind) and pred(r)]
        if weighted:
            return 100 * sum(1 + r["likes"] for r in sel) / likemass[kind]
        denom = {"reply": n_reply, "quote": n_quote, "all": n_all}[kind]
        return 100 * len(sel) / max(1, denom)

    cats = []
    for c in tax["categories"]:
        cid = c["id"]
        cats.append({
            **c,
            "n": sum(r["cat"] == cid for r in items),
            "all": share(lambda r: r["cat"] == cid),
            "reply": share(lambda r: r["cat"] == cid, "reply"),
            "quote": share(lambda r: r["cat"] == cid, "quote"),
            "wtd": share(lambda r: r["cat"] == cid, "all", True),
            "wtd_reply": share(lambda r: r["cat"] == cid, "reply", True),
        })
    cats.sort(key=lambda c: -c["all"])
    max_v = max(max(c["reply"], c["quote"]) for c in cats) * 1.15

    # stance strips from the first-pass labels
    def strip_for(field, order, kind):
        sel = [r for r in items if (kind == "all" or r["kind"] == kind) and r.get(field)]
        cnt = Counter(r[field] for r in sel)
        return [(v, 100 * cnt[v] / max(1, len(sel)), f"seg-{v}") for v in order]
    stance_order = ["supportive", "neutral", "mixed", "critical"]
    claim_order = ["agree", "not_addressed", "mixed", "disagree"]

    addressed = Counter((r["kind"], r.get("addressed_to")) for r in items)
    langs = Counter(r["lang"] for r in items).most_common(6)
    lang_names = {"en": "English", "es": "Spanish", "th": "Thai", "fr": "French", "ja": "Japanese", "pt": "Portuguese",
                  "in": "Indonesian", "de": "German", "zxx": "no text", "it": "Italian", "tr": "Turkish", "ko": "Korean",
                  "ar": "Arabic", "und": "undetermined", "qme": "media only"}

    # ---------------------------------------------------------------- sections
    cat_sections = []
    for c in cats:
        subs = []
        for s in c["subcategories"]:
            rs = [r for r in items if r["sub"] == s["id"]]
            if not rs:
                continue
            ex = pick_examples(rs)
            ex_html = "".join(
                f'<figure class="post {r["kind"]}">'
                f'<blockquote>{esc(r["text"])}</blockquote>'
                + (f'<p class="gist">gist: {esc(r["gist"])}</p>' if r.get("lang") not in ("en", None) and r.get("gist") else "")
                + f'<figcaption><span class="chip {r["kind"]}">{r["kind"]}</span>'
                f'<span class="likes">{fmt_int(r["likes"])} likes</span>'
                f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">@{esc(r["username"])} ↗</a></figcaption></figure>'
                for r in ex)
            pct = 100 * len(rs) / n_all
            subs.append(
                f'<details class="sub"><summary><span class="sub-name">{esc(s["name"])}</span>'
                f'<span class="sub-stat"><b>{pct:.1f}%</b> · {fmt_int(len(rs))} posts · '
                f'{share(lambda r, s=s: r["sub"] == s["id"], "all", True):.1f}% of like-mass</span></summary>'
                f'<p class="sub-desc">{esc(s["description"])}</p><div class="posts">{ex_html}</div></details>')
        cat_sections.append(
            f'<section class="cat" id="{c["id"]}">'
            f'<div class="cat-head"><h3>{esc(c["name"])}</h3>'
            f'<div class="cat-stats"><span><b>{c["all"]:.1f}%</b> of posts</span>'
            f'<span><b>{c["wtd"]:.1f}%</b> of like-mass</span>'
            f'<span class="venue">replies {c["reply"]:.0f}% · quotes {c["quote"]:.0f}%</span></div></div>'
            f'<p class="cat-desc">{esc(c["description"])}</p>{"".join(subs)}</section>')

    max_v = max(max(c["all"], c["wtd"]) for c in cats) * 1.15
    chart = bar_svg([(c["name"], c["all"], c["wtd"]) for c in cats], max_v)
    posted = datetime.fromisoformat(root["data"]["created_at"].replace("Z", "+00:00"))
    built = datetime.now(timezone.utc)

    # headline findings computed live
    top_reply = max(cats, key=lambda c: c["reply"])
    top_quote = max(cats, key=lambda c: c["quote"])
    china = next((s for c in tax["categories"] for s in c["subcategories"] if s["id"] == "china_must_win"), None)
    china_pct = share(lambda r: r["sub"] == "china_must_win", "reply") if china else 0
    attacks = next((c for c in cats if c["id"] == "author_attacks"), None)
    endorse = next((c for c in cats if c["id"] == "endorse_amplify"), None)
    nested = 100 * sum(1 for r in items if r["kind"] == "reply" and posts[r["id"]]["depth"] == 2) / max(1, n_reply)
    meta = next((c for c in cats if c["id"] == "meta_and_noise"), None)
    noise_sub = share(lambda r: r["sub"] == "content_free_offtopic", "reply")
    noise_wtd = share(lambda r: r["sub"] == "content_free_offtopic", "reply", True)
    affect = next((c for c in cats if c["id"] == "existential_reaction"), None)
    substance = next((c for c in cats if c["id"] == "risk_substance"), None)
    denial = next((c for c in cats if c["id"] == "risk_denial"), None)

    page = f"""<title>Reading the Resignation Thread</title>
<meta name="description" content="What 10 kinds of people said in reply to the 'I resigned from Anthropic' post">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {{
  --bg: #F4F5F7; --surface: #FFFFFF; --ink: #1A2130; --ink-2: #545D6B; --ink-3: #8A93A1; --line: #D9DDE3;
  --reply: #2F6DB5; --quote: #C2571A; --reply-soft: #DDE8F6; --quote-soft: #F6E3D6;
  --sup: #3B8F5E; --neu: #B9BFC8; --mix: #D9A441; --crit: #C24B3A;
  --display: "Bricolage Grotesque", "Helvetica Neue", Arial, sans-serif;
  --body: "Source Serif 4", Georgia, "Times New Roman", serif;
  --mono: "JetBrains Mono", "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #14181F; --surface: #1C2129; --ink: #E7EAEF; --ink-2: #A9B1BD; --ink-3: #6F7886; --line: #2C333E;
  --reply: #4F8FDB; --quote: #D4691F; --reply-soft: #22344C; --quote-soft: #45301F;
  --sup: #57B27A; --neu: #4E5663; --mix: #D9A441; --crit: #D9604E;
}} }}
:root[data-theme="dark"] {{
  --bg: #14181F; --surface: #1C2129; --ink: #E7EAEF; --ink-2: #A9B1BD; --ink-3: #6F7886; --line: #2C333E;
  --reply: #4F8FDB; --quote: #D4691F; --reply-soft: #22344C; --quote-soft: #45301F;
  --sup: #57B27A; --neu: #4E5663; --mix: #D9A441; --crit: #D9604E;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 17px; line-height: 1.55; }}
main {{ max-width: 860px; margin: 0 auto; padding: 40px 20px 80px; }}
h1, h2, h3 {{ font-family: var(--display); font-weight: 700; letter-spacing: -0.01em; text-wrap: balance; margin: 0; }}
h1 {{ font-size: clamp(30px, 5vw, 44px); line-height: 1.05; }}
h2 {{ font-size: 24px; margin: 56px 0 14px; }}
h3 {{ font-size: 21px; }}
p {{ max-width: 68ch; margin: 0 0 14px; }}
a {{ color: inherit; }}
.eyebrow {{ font-family: var(--mono); font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-2); margin-bottom: 14px; }}
.lede {{ font-size: 19px; color: var(--ink-2); margin-top: 16px; }}
.root {{ margin: 28px 0 8px; padding: 18px 22px; border-left: 3px solid var(--ink); background: var(--surface); font-size: 16px; }}
.root p {{ margin: 0 0 8px; }}
.root .meta {{ font-family: var(--mono); font-size: 12px; color: var(--ink-2); }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 26px 0; }}
.stat {{ background: var(--surface); border: 1px solid var(--line); padding: 12px 14px; }}
.stat b {{ display: block; font-family: var(--mono); font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; }}
.stat span {{ font-family: var(--display); font-size: 13px; color: var(--ink-2); }}
.stat.reply b {{ color: var(--reply); }} .stat.quote b {{ color: var(--quote); }}
.legend {{ display: flex; gap: 18px; font-family: var(--display); font-size: 13px; color: var(--ink-2); margin: 6px 0 4px; }}
.legend i {{ display: inline-block; width: 12px; height: 9px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }}
.chart {{ background: var(--surface); border: 1px solid var(--line); padding: 14px 16px 6px; overflow-x: auto; }}
svg text {{ font-family: var(--display); font-size: 12px; fill: var(--ink-2); }}
svg .val {{ font-family: var(--mono); font-size: 10px; fill: var(--ink-3); }}
svg .axis-label {{ fill: var(--ink); }}
.bar-reply {{ fill: var(--reply); }} .bar-quote {{ fill: var(--quote); }}
.bar:hover {{ opacity: 0.8; }}
.strip-label {{ font-family: var(--mono); font-size: 10px; fill: #fff; }}
.seg-supportive, .seg-agree {{ fill: var(--sup); }} .seg-neutral, .seg-not_addressed {{ fill: var(--neu); }}
.seg-mixed {{ fill: var(--mix); }} .seg-critical, .seg-disagree {{ fill: var(--crit); }}
.strips {{ display: grid; grid-template-columns: 1fr; gap: 10px; margin: 10px 0 6px; }}
.strip-row {{ display: grid; grid-template-columns: 110px 1fr; gap: 12px; align-items: center; }}
.strip-row label {{ font-family: var(--display); font-size: 13px; color: var(--ink-2); }}
.key {{ font-family: var(--display); font-size: 12px; color: var(--ink-2); margin: 4px 0 0; }}
.key i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 10px; vertical-align: middle; }}
.findings {{ margin: 18px 0 0; padding: 0; list-style: none; display: grid; gap: 10px; max-width: 70ch; }}
.findings li {{ padding-left: 18px; position: relative; }}
.findings li::before {{ content: ""; position: absolute; left: 0; top: 11px; width: 8px; height: 2px; background: var(--ink); }}
.cat {{ margin: 34px 0 0; padding-top: 22px; border-top: 1px solid var(--line); }}
.cat-head {{ display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: baseline; justify-content: space-between; }}
.cat-stats {{ display: flex; flex-wrap: wrap; gap: 14px; font-family: var(--display); font-size: 13px; color: var(--ink-2); }}
.cat-stats b {{ font-family: var(--mono); font-weight: 500; color: var(--ink); font-variant-numeric: tabular-nums; }}
.cat-stats .venue {{ color: var(--ink-3); }}
.cat-desc {{ color: var(--ink-2); margin: 8px 0 12px; }}
details.sub {{ border: 1px solid var(--line); background: var(--surface); margin: 8px 0; }}
details.sub summary {{ cursor: pointer; padding: 10px 14px; display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; justify-content: space-between; list-style: none; }}
details.sub summary::-webkit-details-marker {{ display: none; }}
details.sub summary::before {{ content: "+"; font-family: var(--mono); color: var(--ink-3); margin-right: 8px; }}
details.sub[open] summary::before {{ content: "–"; }}
details.sub summary:focus-visible {{ outline: 2px solid var(--reply); outline-offset: -2px; }}
.sub-name {{ font-family: var(--display); font-weight: 700; font-size: 16px; }}
.sub-stat {{ font-family: var(--display); font-size: 13px; color: var(--ink-2); }}
.sub-stat b {{ font-family: var(--mono); font-weight: 500; color: var(--ink); }}
.sub-desc {{ padding: 0 14px; font-size: 15px; color: var(--ink-2); }}
.posts {{ display: grid; gap: 10px; padding: 0 14px 14px; }}
figure.post {{ margin: 0; padding: 12px 14px; border-left: 3px solid var(--reply); background: var(--bg); }}
figure.post.quote {{ border-left-color: var(--quote); }}
figure.post blockquote {{ margin: 0; font-size: 15.5px; white-space: pre-wrap; overflow-wrap: anywhere; }}
figure.post .gist {{ margin: 6px 0 0; font-size: 13px; color: var(--ink-2); font-style: italic; }}
figure.post figcaption {{ margin-top: 8px; display: flex; gap: 12px; align-items: center; font-family: var(--display); font-size: 12px; color: var(--ink-2); }}
figure.post figcaption a {{ margin-left: auto; text-decoration: none; color: var(--ink-3); }}
figure.post figcaption a:hover {{ color: var(--ink); }}
.chip {{ font-family: var(--mono); font-size: 11px; padding: 1px 7px; border-radius: 3px; background: var(--reply-soft); color: var(--reply); }}
.chip.quote {{ background: var(--quote-soft); color: var(--quote); }}
.likes {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
table {{ border-collapse: collapse; font-family: var(--display); font-size: 14px; margin: 10px 0; }}
th, td {{ text-align: left; padding: 6px 14px 6px 0; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }}
th {{ color: var(--ink-2); font-weight: 500; }}
td.num {{ font-family: var(--mono); text-align: right; }}
.table-wrap {{ overflow-x: auto; }}
.method {{ font-size: 15px; color: var(--ink-2); }}
.method p {{ max-width: 72ch; }}
footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--line); font-family: var(--mono); font-size: 12px; color: var(--ink-3); }}
@media (prefers-reduced-motion: no-preference) {{ details.sub summary::before {{ transition: transform .15s; }} }}
</style>
<main>
<div class="eyebrow">X reaction study · {n_all:,} posts · built {built:%Y-%m-%d %H:%M} UTC</div>
<h1>Reading the Resignation Thread</h1>
<p class="lede">Ten kinds of response to the most-read AI post of the year, measured across {n_all:,} visible replies and quote tweets.</p>

<div class="root">
<p>{esc(root["data"]["text"])}</p>
<p class="meta"><a href="{POST_URL}" target="_blank" rel="noopener">@hilbertspaess</a> · {posted:%Y-%m-%d %H:%M} UTC · {fmt_int(rm["impression_count"])} impressions · {fmt_int(rm["like_count"])} likes · {fmt_int(rm["reply_count"])} replies · {fmt_int(rm["quote_count"])} quotes at last fetch</p>
</div>

<div class="stats">
<div class="stat reply"><b>{fmt_int(n_reply)}</b><span>replies analysed<br>of {fmt_int(rm["reply_count"])} reported</span></div>
<div class="stat quote"><b>{fmt_int(n_quote)}</b><span>quote tweets analysed<br>of {fmt_int(rm["quote_count"])} reported</span></div>
<div class="stat"><b>{fmt_int(likemass["all"] - n_all)}</b><span>likes on the analysed posts</span></div>
<div class="stat"><b>{fmt_int(n_spam)}</b><span>spam or bot posts excluded</span></div>
</div>

<h2>What people were doing when they replied</h2>
<p>Each post was assigned one of 48 response types, grouped into the ten categories below. The scheme was induced bottom-up from a 1,300-post sample, then applied to every post. Replies and quote tweets are pooled here; the venue split, which matters for a few categories, is in the table further down.</p>
<div class="legend"><span><i style="background:var(--reply)"></i>share of posts (n={fmt_int(n_all)})</span><span><i style="background:var(--quote)"></i>share of like-mass (1 + likes)</span></div>
<div class="chart">{chart}</div>

<ul class="findings">
<li><b>{affect["all"]+meta["all"]:.0f}% of responses are reaction or noise, not argument.</b> Affective and existential reaction is {affect["all"]:.0f}% of posts; content-free, meta and market posts are another {meta["all"]:.0f}%.</li>
<li><b>Endorsement outruns attack.</b> Endorsement and amplification is {endorse["all"]:.0f}% of posts against {attacks["all"]:.0f}% for attacks on the author's credibility, and {denial["all"]:.0f}% for outright risk denial.</li>
<li><b>Substantive debate is a minority but carries weight.</b> Posts that engage the mechanism of harm are {substance["all"]:.0f}% of posts but {substance["wtd"]:.0f}% of like-mass.</li>
<li><b>"If we stop, China wins"</b> is the single densest counter-argument, {share(lambda r: r["sub"] == "china_must_win"):.1f}% of all posts and {china_pct:.1f}% of replies, with its own rebuttal strand ({share(lambda r: r["sub"] == "rejects_race_framing"):.1f}%).</li>
<li><b>Venue changes the mix.</b> Replies argue: substantive debate, denial and attacks are {substance["reply"]+denial["reply"]+attacks["reply"]:.0f}% of replies but {substance["quote"]+denial["quote"]+attacks["quote"]:.0f}% of quotes. Quotes emote and amplify: reaction plus endorsement are {affect["quote"]+endorse["quote"]:.0f}% of quotes but {affect["reply"]+endorse["reply"]:.0f}% of replies.</li>
</ul>

<h2>Stance, for comparison</h2>
<p>A separate first-pass label recorded stance toward the author and toward the core claim. Sentiment-style measures flatten the structure above, but they give the headline split.</p>
<div class="strips">
<div class="strip-row"><label>toward the author</label>{strip_svg(strip_for("stance", stance_order, "all"))}</div>
<div class="strip-row"><label>toward the claim</label>{strip_svg(strip_for("claim", claim_order, "all"))}</div>
</div>
<p class="key"><i style="background:var(--sup)"></i>supportive / agree<i style="background:var(--neu)"></i>neutral / not addressed<i style="background:var(--mix)"></i>mixed<i style="background:var(--crit)"></i>critical / disagree</p>

<h2>The ten categories, with representative posts</h2>
<p>Categories are ordered by overall share. Open a response type to see its definition and three posts: the most-liked confident example plus two drawn at random, so the selection is not only the outliers. Non-English posts carry a one-line gist.</p>
{"".join(cat_sections)}

<h2>Where venue changes the reading</h2>
<p>A reply argues inside the author's thread; a quote carries the thread to the quoter's own followers. The pooled figures above are three-quarters quotes by count and mostly replies by like-mass, so the split is worth a look.</p>
<div class="table-wrap"><table>
<tr><th>category</th><th>replies (n={fmt_int(n_reply)})</th><th>quotes (n={fmt_int(n_quote)})</th><th>pooled</th></tr>
{"".join(f'<tr><td>{esc(c["name"])}</td><td class="num">{c["reply"]:.1f}%</td><td class="num">{c["quote"]:.1f}%</td><td class="num">{c["all"]:.1f}%</td></tr>' for c in cats)}
</table></div>

<h2>Thread structure and language</h2>
<div class="table-wrap"><table>
<tr><th>reply position</th><th>posts</th><th>share of replies</th></tr>
<tr><td>direct reply to the author</td><td class="num">{fmt_int(sum(1 for r in items if r["kind"] == "reply" and posts[r["id"]]["depth"] == 1))}</td><td class="num">{100 - nested:.0f}%</td></tr>
<tr><td>reply to another reply</td><td class="num">{fmt_int(sum(1 for r in items if r["kind"] == "reply" and posts[r["id"]]["depth"] == 2))}</td><td class="num">{nested:.0f}%</td></tr>
</table></div>
<div class="table-wrap"><table>
<tr><th>language</th><th>posts</th><th>share</th></tr>
{"".join(f'<tr><td>{lang_names.get(l, l or "?")}</td><td class="num">{fmt_int(c)}</td><td class="num">{100*c/n_all:.0f}%</td></tr>' for l, c in langs)}
</table></div>

<h2>Method and caveats</h2>
<div class="method">
<p><b>Collection.</b> Official X API v2 on pay-per-use. Replies were unioned across four query styles (conversation search, in-reply-to search, to:author search, full-archive search) because no single query returns the tree; quotes came from the quote-tweets endpoint with retweets excluded. Without that exclusion the endpoint returned {fmt_int(n_retweets)} retweets of quote tweets, which we dropped.</p>
<p><b>Coverage.</b> X reports {fmt_int(rm["reply_count"])} replies; the search index exposed {fmt_int(n_reply + n_spam)} before spam removal. The missing replies are most likely the ones X hides as low quality, so reply figures describe the visible thread and probably understate hostility. Quotes were still arriving during collection.</p>
<p><b>Labelling.</b> Claude Opus 5 labelled every post once with the author's full thread as context. The taxonomy was induced from a sample stratified by venue with the most-liked posts oversampled; assignment used a fixed list of 48 types and forced one choice per post. Spam-flagged posts are excluded everywhere. Like-mass weights each post by 1 + likes. No human validation set exists; a few dozen spot checks found sarcasm handled well.</p>
<p><b>Inducer's notes.</b> {esc(tax["notes"])}</p>
</div>
<footer>source: jarvis-os/experiments/x-conversation-sentiment · data: gs://alignment-team-general-storage/daniel/jarvis/experiments/x-conversation-sentiment/</footer>
</main>
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print(f"wrote {args.out} ({len(page)//1024} KB) from {n_all} posts")


if __name__ == "__main__":
    main()
