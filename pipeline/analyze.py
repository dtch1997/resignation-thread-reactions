#!/usr/bin/env python3
"""Join posts with labels, write results.jsonl + summary tables + figures.

    ./analyze.py            # → data/<id>/results.jsonl, summary.md, figures/*.png
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import xy.pyplot as plt

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
FIG = Path(__file__).parent / "figures"
FIELDS = ["sentiment", "stance_author", "stance_claim", "frame"]
ORDER = {
    "sentiment": ["positive", "neutral", "mixed", "negative"],
    "stance_author": ["supportive", "neutral", "mixed", "critical"],
    "stance_claim": ["agree", "not_addressed", "mixed", "disagree"],
}


def rows(p: Path):
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                yield json.loads(line)


def pct_table(items: list[dict], field: str, weight=None) -> tuple[list[str], dict[str, list[float]]]:
    """Return (columns=kinds, {value: [pct per kind]})."""
    kinds = ["reply", "quote", "all"]
    tot = {k: 0.0 for k in kinds}
    cnt: dict[str, dict[str, float]] = defaultdict(lambda: {k: 0.0 for k in kinds})
    for r in items:
        w = weight(r) if weight else 1.0
        for k in (r["kind"], "all"):
            tot[k] += w
            cnt[r[field]][k] += w
    vals = ORDER.get(field) or [v for v, _ in Counter(r[field] for r in items).most_common()]
    return kinds, {v: [100 * cnt[v][k] / tot[k] if tot[k] else 0 for k in kinds] for v in vals}


def md_table(title: str, kinds: list[str], table: dict[str, list[float]], n: dict[str, int]) -> str:
    head = f"\n**{title}**\n\n| value | " + " | ".join(f"{k} (n={n[k]})" for k in kinds) + " |\n|---|" + "---|" * len(kinds) + "\n"
    return head + "".join(f"| {v} | " + " | ".join(f"{p:.1f}%" for p in ps) + " |\n" for v, ps in table.items())


def bar(table: dict[str, list[float]], kinds: list[str], title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.5))
    vals = list(table)
    width = 0.8 / len(kinds)
    for i, k in enumerate(kinds):
        xs = [j + i * width for j in range(len(vals))]
        ax.bar(xs, [table[v][i] for v in vals], width=width, label=k)
    ax.set_xticks([j + width * (len(kinds) - 1) / 2 for j in range(len(vals))])
    ax.set_xticklabels(vals, rotation=20)
    ax.set_ylabel("% of posts")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    posts = {t["id"]: t for t in rows(DATA / "all_posts.jsonl")}
    labels = {l["id"]: l for l in rows(DATA / "labels.jsonl") if "error" not in l}
    errors = sum(1 for l in rows(DATA / "labels.jsonl") if "error" in l)
    root = json.loads((DATA / "root.json").read_text())["data"]
    t0 = datetime.fromisoformat(root["created_at"].replace("Z", "+00:00"))

    items = []
    for pid, lab in labels.items():
        t = posts.get(pid)
        if not t or t["kind"] not in ("reply", "quote"):
            continue
        created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
        if t.get("media_only"):
            lab = {**lab, "frame": "media_only"}
        items.append({
            "id": pid, "kind": t["kind"], "depth": t["depth"], "username": t["username"],
            "followers": t.get("followers") or 0, "lang": t.get("lang"),
            "likes": t["public_metrics"].get("like_count", 0),
            "impressions": t["public_metrics"].get("impression_count", 0),
            "hours_after": round((created - t0).total_seconds() / 3600, 2),
            "created_at": t["created_at"], "text": t["full_text"],
            "url": f"https://x.com/{t['username']}/status/{pid}",
            "has_media": t.get("has_media", False), "media_only": t.get("media_only", False),
            **{k: lab[k] for k in FIELDS},
            "targets": ",".join(lab["targets"]), "spam": lab["is_bot_or_spam"],
            "summary": lab["summary"], "confidence": lab["confidence"],
        })
    with (DATA / "results.jsonl").open("w") as f:
        for r in items:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = Counter(r["kind"] for r in items); n["all"] = len(items)
    n_spam = sum(r["spam"] for r in items)
    clean = [r for r in items if not r["spam"]]
    nc = Counter(r["kind"] for r in clean); nc["all"] = len(clean)
    FIG.mkdir(exist_ok=True)
    out = [f"# Reaction labels for x.com/hilbertspaess/status/{ROOT_ID}\n",
           f"Posts labelled: {len(items)} ({dict(Counter(r['kind'] for r in items))}); "
           f"label errors: {errors}; flagged spam/bot: {n_spam} ({100*n_spam/max(1,len(items)):.1f}%). "
           f"Tables below exclude spam.\n"]
    for field in FIELDS:
        kinds, table = pct_table(clean, field)
        out.append(md_table(f"{field} (share of posts)", kinds, table, nc))
        bar(table, kinds, f"{field} — share of posts", FIG / f"{field}.png")
        kinds, wtable = pct_table(clean, field, weight=lambda r: 1 + r["likes"])
        out.append(md_table(f"{field} (like-weighted, 1+likes)", kinds, wtable, nc))
        bar(wtable, kinds, f"{field} — like-weighted", FIG / f"{field}_weighted.png")

    # sentiment over time (2-hour buckets, non-spam, share supportive/critical of author)
    buckets: dict[int, Counter] = defaultdict(Counter)
    for r in clean:
        buckets[int(r["hours_after"] // 2)][r["stance_author"]] += 1
    hs = sorted(buckets)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    for stance in ORDER["stance_author"]:
        ax.plot([2 * h for h in hs], [100 * buckets[h][stance] / sum(buckets[h].values()) for h in hs], label=stance)
    ax.set_xlabel("hours after the post (2h buckets)"); ax.set_ylabel("% of posts in bucket")
    ax.set_title("stance toward the author over time"); ax.legend(); fig.tight_layout()
    fig.savefig(FIG / "stance_author_over_time.png"); plt.close(fig)
    out.append("\n**Posts per 2h bucket**: " + ", ".join(f"{2*h}h: {sum(buckets[h].values())}" for h in hs) + "\n")

    # languages
    langs = Counter(r["lang"] for r in clean).most_common(8)
    out.append("\n**Languages**: " + ", ".join(f"{l} {c}" for l, c in langs) + "\n")

    # top-liked examples per frame
    out.append("\n## Most-liked example per frame (non-spam)\n")
    by_frame: dict[str, list] = defaultdict(list)
    for r in clean:
        by_frame[r["frame"]].append(r)
    for frame, rs in sorted(by_frame.items(), key=lambda kv: -len(kv[1])):
        rs.sort(key=lambda r: -r["likes"])
        out.append(f"\n**{frame}** (n={len(rs)})\n")
        for r in rs[:3]:
            txt = r["text"].replace("\n", " ")[:220]
            out.append(f"- [{r['likes']} likes, @{r['username']}, {r['kind']}]({r['url']}): {txt}\n")

    (DATA / "summary.md").write_text("".join(out))
    print(f"{len(items)} joined rows → results.jsonl; summary.md; figures in {FIG}")


if __name__ == "__main__":
    main()
