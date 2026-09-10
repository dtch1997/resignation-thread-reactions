#!/usr/bin/env python3
"""Render the LW-style taxonomy post as a self-contained HTML page (Claude artifact).

    ./build_blogpost_html.py [--out ../../../jarvis-artifacts/x-resignation-reactions/post.html]

Reuses the example selection and translation cache from build_blogpost.py.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

from build_blogpost import DATA, GROUPS, LANG, ROOT_ID, clean, pick, rows, translate

FIG_SVG = Path(__file__).parent / "figures" / "taxonomy_sunburst.svg"


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def card(r: dict, tr: dict[str, str], names: dict[str, str]) -> str:
    text = clean(r["text"])
    norm = lambda x: re.sub(r"[^a-z0-9]+", "", x.lower())
    trans = ""
    if r["id"] in tr and norm(tr[r["id"]]) != norm(text):
        trans = f'<p class="trans"><span class="lang">{esc(LANG.get(r["lang"], r["lang"] or ""))}</span>{esc(tr[r["id"]])}</p>'
    likes = f"{r['likes']:,} like" + ("" if r["likes"] == 1 else "s")
    return (f'<article class="post {r["kind"]}">'
            f'<header><span class="name">{esc(names.get(r["username"], r["username"]))}</span>'
            f'<span class="handle">@{esc(r["username"])}</span><span class="chip {r["kind"]}">{r["kind"]}</span></header>'
            f'<p class="text">{esc(text)}</p>{trans}'
            f'<footer><span class="likes">{likes}</span><a href="{esc(r["url"])}" target="_blank" rel="noopener">open on X ↗</a></footer>'
            f'</article>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).parents[3] / "jarvis-artifacts" / "x-resignation-reactions" / "post.html")
    ap.add_argument("--standalone", action="store_true", help="emit a full HTML document (for GitHub Pages) instead of the artifact body")
    args = ap.parse_args()

    tax = json.loads((DATA / "taxonomy.json").read_text())
    cats = {c["id"]: c for c in tax["categories"]}
    posts = {t["id"]: t for t in rows(DATA / "all_posts.jsonl")}
    names = {u["username"]: u.get("name", u["username"]) for u in rows(DATA / "all_users.jsonl")}
    items = list(rows(DATA / "taxonomy_results.jsonl"))
    for r in items:
        r["lang"] = posts[r["id"]].get("lang")
    n = len(items)
    n_reply = sum(r["kind"] == "reply" for r in items)
    n_quote = n - n_reply
    cat_n = Counter(r["cat"] for r in items)
    sub_n = Counter(r["sub"] for r in items)
    chosen = {}
    for cid, c in cats.items():
        for s in c["subcategories"]:
            rs = [r for r in items if r["sub"] == s["id"]]
            if rs:
                chosen[s["id"]] = pick(rs)
    tr = translate([r for ex in chosen.values() for r in ex])
    pct = lambda x: f"{100 * x / n:.1f}%"

    svg = FIG_SVG.read_text()
    svg = re.sub(r'<svg [^>]*>', '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1760 900" width="100%" role="img" aria-label="Two-ring donut of response categories">', svg, count=1)
    svg = svg.replace('<rect width="1760" height="900" fill="#FFFFFF"/>', '')
    # strip the in-SVG title/subtitle/source lines; the page supplies its own caption
    svg = re.sub(r'<text x="30" y="34" class="title">.*?</text>', '', svg)
    svg = re.sub(r'<text x="30" y="56" class="sub">.*?</text>', '', svg)
    svg = re.sub(r'<text x="30" y="884" class="sub">.*?</text>', '', svg)

    toc = "".join(f'<li><a href="#{gid}">{esc(gname)}</a> <span>{pct(sum(cat_n[c] for c in cids))}</span></li>' for gname, gid, cids, _ in GROUPS)

    sections = []
    for gname, gid, cids, gdesc in GROUPS:
        gn = sum(cat_n[c] for c in cids)
        cat_html = []
        for cid in sorted(cids, key=lambda c: -cat_n[c]):
            c = cats[cid]
            subs = []
            for s in sorted(c["subcategories"], key=lambda s: -sub_n[s["id"]]):
                if s["id"] not in chosen:
                    continue
                cards = "".join(card(r, tr, names) for r in chosen[s["id"]])
                subs.append(f'''<details class="type" id="{s["id"]}">
<summary><span class="type-name">{esc(s["name"])}</span><span class="type-stat"><b>{pct(sub_n[s["id"]])}</b> · {sub_n[s["id"]]:,} posts</span></summary>
<p class="type-desc">{esc(s["description"])}</p>
<div class="cards">{cards}</div>
</details>''')
            cat_html.append(f'''<section class="cat" id="{cid}">
<h3>{esc(c["name"])} <span class="share">{pct(cat_n[cid])}</span></h3>
<p class="cat-desc">{esc(c["description"])}</p>
{"".join(subs)}
</section>''')
        sections.append(f'''<section class="group {gid}" id="{gid}">
<h2><span class="swatch"></span>{esc(gname)} <span class="share">{pct(gn)}</span></h2>
<p class="group-desc">{esc(gdesc)}</p>
{"".join(cat_html)}
</section>''')

    page = f"""<title>What 17,000 People Said</title>
<meta name="description" content="A taxonomy of the reaction to the 'I resigned from Anthropic' post, down to example tweets">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {{
  --bg: #F4F5F7; --surface: #FFFFFF; --ink: #1A2130; --ink-2: #545D6B; --ink-3: #8A93A1; --line: #D9DDE3;
  --reply: #2F6DB5; --quote: #C2571A; --reply-soft: #DDE8F6; --quote-soft: #F6E3D6;
  --argue: #2F6DB5; --react: #C2571A; --author: #3B8F5E; --noise: #8A93A1;
  --display: "Bricolage Grotesque", "Helvetica Neue", Arial, sans-serif;
  --body: "Source Serif 4", Georgia, "Times New Roman", serif;
  --mono: "JetBrains Mono", "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #14181F; --surface: #1C2129; --ink: #E7EAEF; --ink-2: #A9B1BD; --ink-3: #6F7886; --line: #2C333E;
  --reply: #4F8FDB; --quote: #D4691F; --reply-soft: #22344C; --quote-soft: #45301F;
  --argue: #4F8FDB; --react: #D4691F; --author: #57B27A; --noise: #7C8593;
}} }}
:root[data-theme="dark"] {{
  --bg: #14181F; --surface: #1C2129; --ink: #E7EAEF; --ink-2: #A9B1BD; --ink-3: #6F7886; --line: #2C333E;
  --reply: #4F8FDB; --quote: #D4691F; --reply-soft: #22344C; --quote-soft: #45301F;
  --argue: #4F8FDB; --react: #D4691F; --author: #57B27A; --noise: #7C8593;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 17px; line-height: 1.55; }}
main {{ max-width: 780px; margin: 0 auto; padding: 44px 20px 80px; }}
h1, h2, h3 {{ font-family: var(--display); font-weight: 700; letter-spacing: -0.01em; text-wrap: balance; margin: 0; }}
h1 {{ font-size: clamp(30px, 5vw, 42px); line-height: 1.08; }}
h2 {{ font-size: 26px; margin: 52px 0 8px; display: flex; align-items: center; gap: 10px; }}
h3 {{ font-size: 20px; margin: 30px 0 6px; }}
.share {{ font-family: var(--mono); font-weight: 500; font-size: 0.75em; color: var(--ink-3); margin-left: 6px; }}
.swatch {{ width: 14px; height: 14px; border-radius: 3px; background: var(--ink-3); display: inline-block; }}
.group.argue .swatch {{ background: var(--argue); }} .group.react .swatch {{ background: var(--react); }}
.group.author .swatch {{ background: var(--author); }} .group.noise .swatch {{ background: var(--noise); }}
p {{ max-width: 68ch; margin: 0 0 14px; }}
a {{ color: inherit; }}
.eyebrow {{ font-family: var(--mono); font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-2); margin-bottom: 14px; }}
.lede {{ font-size: 19px; color: var(--ink-2); margin: 14px 0 22px; }}
.figure {{ background: #FFFFFF; border: 1px solid var(--line); padding: 10px 12px 4px; margin: 22px 0 6px; overflow-x: auto; }}
.figure svg {{ display: block; min-width: 720px; }}
figcaption {{ font-family: var(--display); font-size: 13px; color: var(--ink-2); margin: 6px 0 24px; }}
.toc {{ list-style: none; padding: 0; margin: 18px 0 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }}
.toc li {{ font-family: var(--display); font-size: 14px; border: 1px solid var(--line); background: var(--surface); padding: 8px 10px; display: flex; justify-content: space-between; }}
.toc a {{ text-decoration: none; font-weight: 700; }}
.toc span {{ font-family: var(--mono); color: var(--ink-3); }}
hr {{ border: 0; border-top: 1px solid var(--line); margin: 36px 0 0; }}
.group-desc, .cat-desc {{ color: var(--ink-2); }}
.cat-desc {{ font-size: 15.5px; }}
details.type {{ border: 1px solid var(--line); background: var(--surface); margin: 8px 0; }}
details.type summary {{ cursor: pointer; padding: 10px 14px; display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; justify-content: space-between; list-style: none; }}
details.type summary::-webkit-details-marker {{ display: none; }}
details.type summary::before {{ content: "+"; font-family: var(--mono); color: var(--ink-3); margin-right: 8px; }}
details.type[open] summary::before {{ content: "–"; }}
details.type summary:focus-visible {{ outline: 2px solid var(--reply); outline-offset: -2px; }}
.type-name {{ font-family: var(--display); font-weight: 700; font-size: 16px; }}
.type-stat {{ font-family: var(--display); font-size: 13px; color: var(--ink-2); }}
.type-stat b {{ font-family: var(--mono); font-weight: 500; color: var(--ink); }}
.type-desc {{ padding: 0 14px; font-size: 15px; color: var(--ink-2); }}
.cards {{ display: grid; gap: 10px; padding: 0 14px 14px; }}
article.post {{ background: var(--bg); border: 1px solid var(--line); border-left: 3px solid var(--reply); padding: 12px 14px; }}
article.post.quote {{ border-left-color: var(--quote); }}
article.post header {{ display: flex; gap: 8px; align-items: baseline; font-family: var(--display); font-size: 13.5px; margin-bottom: 6px; }}
article.post .name {{ font-weight: 700; }}
article.post .handle {{ color: var(--ink-3); }}
article.post .text {{ font-size: 15.5px; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; max-width: none; }}
article.post .trans {{ font-size: 14.5px; color: var(--ink-2); font-style: italic; margin: 8px 0 0; padding-top: 8px; border-top: 1px dashed var(--line); max-width: none; }}
article.post .trans .lang {{ font-family: var(--mono); font-style: normal; font-size: 11px; color: var(--ink-3); margin-right: 8px; text-transform: uppercase; letter-spacing: 0.05em; }}
article.post footer {{ margin-top: 8px; display: flex; gap: 12px; align-items: center; font-family: var(--display); font-size: 12.5px; color: var(--ink-2); }}
article.post footer a {{ margin-left: auto; text-decoration: none; color: var(--ink-3); }}
article.post footer a:hover {{ color: var(--ink); }}
.chip {{ font-family: var(--mono); font-size: 11px; padding: 1px 7px; border-radius: 3px; background: var(--reply-soft); color: var(--reply); margin-left: auto; }}
.chip.quote {{ background: var(--quote-soft); color: var(--quote); }}
.likes {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.method {{ font-size: 15px; color: var(--ink-2); }}
footer.page {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--line); font-family: var(--mono); font-size: 12px; color: var(--ink-3); }}
</style>
<main>
<div class="eyebrow">X reaction study · {n:,} posts</div>
<h1>What 17,000 people said to the researcher who quit Anthropic</h1>
<p class="lede">A taxonomy of the reaction to the most-read AI post of the year, from four broad moves down to the individual tweets.</p>

<p>On 9 September a pretraining researcher posted that he had resigned from Anthropic because neither it nor OpenAI was acting responsibly. Within a day the post had 100 million impressions, 13,000 replies and 28,000 quote tweets. I wanted to know what that reaction consisted of, so I pulled every visible reply and quote tweet through the X API and had a language model sort them.</p>

<figure class="figure">{svg}</figure>
<figcaption>Share of {n:,} visible replies and quote tweets, spam excluded. Inner ring: ten categories. Outer ring: 48 response types. Colour: the four moves below.</figcaption>

<p class="method"><b>Method, briefly.</b> X exposed 5,000 of the 13,000 replies and 14,000 of the quote tweets; the rest are hidden as low quality or come from restricted accounts. After dropping spam, {n:,} posts remained ({n_reply:,} replies, {n_quote:,} quotes). Claude Opus 5 read a 1,300-post sample and proposed ten categories with 48 response types, then assigned every post to one type. I grouped the ten categories into four moves. Each response type opens to its definition and three examples: the most-liked confident one, then two drawn at random so you see the typical case. Non-English posts carry a translation.</p>


<ul class="toc">{toc}</ul>
<hr>
{"".join(sections)}
<footer class="page">Data: X API v2, collected 2026-09-09 · labels: Claude Opus 5, bottom-up taxonomy, one pass, no human validation set · reply coverage is the visible thread only · source: jarvis-os/experiments/x-conversation-sentiment</footer>
</main>
"""
    if args.standalone:
        head_end = page.index("</style>") + len("</style>")
        page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                + page[:head_end] + '\n</head>\n<body>\n' + page[head_end:] + '\n</body>\n</html>\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print(f"wrote {args.out} ({len(page)//1024} KB, {len(chosen)} types, {len(tr)} translations)")


if __name__ == "__main__":
    main()
