#!/usr/bin/env python3
"""Render blogpost/draft.html from blogpost/draft_template.html.

Placeholders: {{fig:stance|moves|objections}} inline the SVGs; {{q:<sub>:<username>}}
renders a quoted post (text, translation, handle, venue, likes, followers, link)
looked up in blogpost/examples.json. Run lw_draft_data.py first.
"""
import json, re, html
from pathlib import Path

BP = Path(__file__).parent.parent / "blogpost"
EX = json.loads((BP / "examples.json").read_text())
BY = {(sub, e["user"]): e for sub, lst in EX.items() for e in lst}

def clean(t):
    t = re.sub(r"https://t\.co/\S+", "", t)          # media / quoted-post links
    t = re.sub(r"^(@\w+\s+)+", "", t.strip())        # leading reply mentions
    return html.escape(t.strip())

def card(sub, user):
    e = BY[(sub, user)]
    venue = "reply" if e["kind"] == "reply" else "quote tweet"
    likes = f'{e["likes"]:,} like' + ("" if e["likes"] == 1 else "s")
    fol = f'{int(e["followers"]):,} followers' if isinstance(e["followers"], (int, float)) else ""
    tr = f'<p class="trans">{html.escape(e["translation"])}</p>' if e.get("translation") and e["lang"] != "en" else ""
    body = "".join(f"<p>{html.escape(p.strip())}</p>" for p in re.sub(r"https://t\.co/\S+", "", re.sub(r"^(@\w+\s+)+", "", e["text"].strip())).split("\n\n") if p.strip())
    return (f'<figure class="post"><blockquote>{body}</blockquote>{tr}'
            f'<figcaption><a href="{e["url"]}" target="_blank" rel="noopener">@{html.escape(user)}</a>'
            f'<span>{venue}</span><span>{likes}</span><span>{fol}</span></figcaption></figure>')

tpl = (BP / "draft_template.html").read_text()
tpl = re.sub(r"\{\{fig:(\w+)\}\}", lambda m: (BP / f"fig_{m.group(1)}.svg").read_text(), tpl)
tpl = re.sub(r"\{\{q:([\w_]+):([\w_]+)\}\}", lambda m: card(m.group(1), m.group(2)), tpl)
(BP / "draft.html").write_text(tpl)
print("wrote", BP / "draft.html", len(tpl), "bytes")
