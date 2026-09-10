#!/usr/bin/env python3
"""Render blogpost.md: narrative intro + figure + a collapsible taxonomy tree.

H2 = move (argues / reacts / judges the author / noise), H3 = category,
<details> = response type with definition and three example posts, translated
when not English (translations cached in data/<id>/translations.json).
"""
from __future__ import annotations

import json
import os
import random
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
OUT = Path(__file__).parent / "blogpost.md"
GROUPS = [
    ("Argues", "argue", ["risk_substance", "risk_denial", "race_logic", "policy_power", "exit_critique"],
     "Posts that engage the claim: that the labs are racing irresponsibly and the risk is real."),
    ("Reacts", "react", ["existential_reaction", "cultural_framing"],
     "Posts that respond with feeling or with a frame from fiction, history, or religion, without arguing."),
    ("Judges the author", "author", ["endorse_amplify", "author_attacks"],
     "Posts about the person: praising and relaying, or attacking credibility and motive."),
    ("Noise and meta", "noise", ["meta_and_noise"],
     "Emoji, off-topic, trading takes, commentary on the virality, bots."),
]
LANG = {"en": "English", "es": "Spanish", "th": "Thai", "fr": "French", "ja": "Japanese", "pt": "Portuguese",
        "in": "Indonesian", "de": "German", "it": "Italian", "tr": "Turkish", "ko": "Korean", "ar": "Arabic",
        "hi": "Hindi", "ru": "Russian", "zh": "Chinese", "nl": "Dutch", "pl": "Polish", "vi": "Vietnamese",
        "tl": "Tagalog", "fa": "Persian", "uk": "Ukrainian", "sv": "Swedish"}


def rows(p: Path):
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def clean(text: str) -> str:
    text = re.sub(r"https?://t\.co/\S+", "", text)
    text = re.sub(r"^(@\w+\s+)+", "", text.strip())
    return text.strip()


def pick(rs: list[dict], k: int = 3, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    good = [r for r in rs if r["confidence"] >= 0.75 and 40 <= len(clean(r["text"])) <= 420]
    pool = sorted(good or rs, key=lambda r: -r["likes"])
    out = pool[:1]
    rest = pool[1:]
    rng.shuffle(rest)
    en = [r for r in rest if r["lang"] == "en"]
    other = [r for r in rest if r["lang"] != "en"]
    # one non-English example when the type has them, so translations get shown
    for cand in (other[:1] + en + other[1:]):
        if len(out) >= k:
            break
        if cand["id"] not in {o["id"] for o in out}:
            out.append(cand)
    return out


def translate(items: list[dict]) -> dict[str, str]:
    cache_p = DATA / "translations.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    todo = [r for r in items if r["lang"] not in ("en", None, "qme", "zxx", "und") and r["id"] not in cache]
    if todo:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            for line in (Path.home() / ".env").read_text().split("\n"):
                if line.startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
        import anthropic
        c = anthropic.Anthropic()

        def one(r):
            msg = c.messages.create(
                model="claude-opus-5", max_tokens=1024,
                system="Translate the X post into natural English. Keep tone, slang and sarcasm. Output only the translation.",
                messages=[{"role": "user", "content": clean(r["text"])}],
                output_config={"effort": "low"})
            return r["id"], next(b.text for b in msg.content if b.type == "text").strip()
        with ThreadPoolExecutor(8) as ex:
            for pid, t in ex.map(one, todo):
                cache[pid] = t
        cache_p.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
        print(f"translated {len(todo)}")
    return cache


def quote(r: dict, tr: dict[str, str]) -> str:
    text = clean(r["text"]).replace("\n", " ").strip()
    lines = [f"> {text}"]
    norm = lambda x: re.sub(r"[^a-z0-9]+", "", x.lower())
    if r["id"] in tr and norm(tr[r["id"]]) != norm(text):  # X mislabels some English posts; skip identical "translations"
        lines.append(">")
        lines.append(f"> *({LANG.get(r['lang'], r['lang'])}) {tr[r['id']].replace(chr(10), ' ')}*")
    lines.append(">")
    likes = f"{r['likes']:,} like" + ("" if r["likes"] == 1 else "s")
    lines.append(f"> — [{r['kind']}, {likes}]({r['url']})")
    return "\n".join(lines)


def main() -> None:
    tax = json.loads((DATA / "taxonomy.json").read_text())
    cats = {c["id"]: c for c in tax["categories"]}
    posts = {t["id"]: t for t in rows(DATA / "all_posts.jsonl")}
    items = list(rows(DATA / "taxonomy_results.jsonl"))
    for r in items:
        r["lang"] = posts[r["id"]].get("lang")
    n = len(items)
    cat_n = Counter(r["cat"] for r in items)
    sub_n = Counter(r["sub"] for r in items)
    n_reply = sum(r["kind"] == "reply" for r in items)
    n_quote = n - n_reply

    # choose examples first so translation runs once
    chosen: dict[str, list[dict]] = {}
    for cid, c in cats.items():
        for s in c["subcategories"]:
            rs = [r for r in items if r["sub"] == s["id"]]
            if rs:
                chosen[s["id"]] = pick(rs)
    tr = translate([r for ex in chosen.values() for r in ex])

    def pct(x: int) -> str:
        return f"{100 * x / n:.1f}%"

    out = []
    out.append(f"""# Taxonomizing ~17k responses to Jacob Coxon's viral tweet on quitting Anthropic


![Ten response categories by share, grouped by move](figures/taxonomy_bars.png)

**Method, briefly.** X exposed 5,000 of the 13,000 replies and 14,000 of the quote tweets; the rest are hidden as low quality or come from restricted accounts. After dropping spam, {n:,} posts remained ({n_reply:,} replies, {n_quote:,} quotes). Claude Opus 5 read a 1,300-post sample and proposed ten categories with 48 response types, then assigned every post to one type. I grouped the ten categories into four moves. Percentages below are shares of all {n:,} posts. Each response type opens to its definition and three examples: the most-liked confident one, and two drawn at random so you see the typical case. Non-English posts carry a translation.


---
""")
    for gname, gid, cids, gdesc in GROUPS:
        gn = sum(cat_n[c] for c in cids)
        out.append(f"\n## {gname} — {pct(gn)}\n\n{gdesc}\n")
        for cid in sorted(cids, key=lambda c: -cat_n[c]):
            c = cats[cid]
            out.append(f"\n### {c['name']} — {pct(cat_n[cid])}\n\n{c['description']}\n")
            for s in sorted(c["subcategories"], key=lambda s: -sub_n[s["id"]]):
                if s["id"] not in chosen:
                    continue
                ex = "\n\n".join(quote(r, tr) for r in chosen[s["id"]])
                out.append(f"""
<details>
<summary><b>{s['name']}</b> — {pct(sub_n[s['id']])} ({sub_n[s['id']]:,} posts)</summary>

{s['description']}

{ex}

</details>
""")
    out.append("""
""")
    OUT.write_text("".join(out))
    words = len(OUT.read_text().split())
    print(f"wrote {OUT} ({words} words, {len(chosen)} response types, {len(tr)} translations)")


if __name__ == "__main__":
    main()
