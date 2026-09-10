#!/usr/bin/env python3
"""Bottom-up taxonomy of responses: induce categories from a sample, assign all posts.

    ./taxonomy.py induce            # sample → Opus 5 → data/<id>/taxonomy.json
    ./taxonomy.py assign            # Batches API: every reply/quote → subcategory
    ./taxonomy.py collect           # pull results → data/<id>/taxonomy_labels.jsonl
    ./taxonomy.py report            # → data/<id>/taxonomy_report.md + figures/taxonomy*.png
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
FIG = Path(__file__).parent / "figures"
INDUCE_MODEL = "claude-opus-5"
ASSIGN_MODEL = "claude-opus-5"


def rows(p: Path):
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn line from concurrent appends; the id gets relabelled next pass


def client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        for line in (Path.home() / ".env").read_text().split("\n"):
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    return anthropic.Anthropic()


def thread_text() -> str:
    root = json.loads((DATA / "root.json").read_text())["data"]
    thread = sorted((t for t in rows(DATA / "all_posts.jsonl") if t["kind"] == "thread"), key=lambda t: t["created_at"])
    return "\n\n".join([root["text"]] + [t["full_text"] for t in thread])


def corpus() -> tuple[list[dict], dict[str, dict]]:
    """Non-spam replies and quotes with a stripped text, plus their labels."""
    labels = {l["id"]: l for l in rows(DATA / "labels.jsonl") if "error" not in l}
    posts = []
    for t in rows(DATA / "all_posts.jsonl"):
        if t["kind"] not in ("reply", "quote") or not t.get("text_stripped"):
            continue
        lab = labels.get(t["id"])
        if lab and lab["is_bot_or_spam"]:
            continue
        posts.append(t)
    return posts, labels


def fmt(t: dict, labels: dict, n: int) -> str:
    s = t["text_stripped"].replace("\n", " ")[:300]
    extra = f" | gist: {labels[t['id']]['summary']}" if t["id"] in labels and t.get("lang") != "en" else ""
    return f"[{n}] ({t['kind']}, {t['public_metrics'].get('like_count', 0)} likes, {t.get('lang')}) {s}{extra}"


# ---------------------------------------------------------------------------

def induce(args) -> None:
    posts, labels = corpus()
    rng = random.Random(args.seed)
    by_kind = defaultdict(list)
    for t in posts:
        by_kind[t["kind"]].append(t)
    sample = []
    for kind, ts in by_kind.items():
        ts.sort(key=lambda t: -t["public_metrics"].get("like_count", 0))
        top = ts[: args.top_per_kind]
        rest = rng.sample(ts[args.top_per_kind:], min(args.random_per_kind, max(0, len(ts) - args.top_per_kind)))
        sample += top + rest
    rng.shuffle(sample)
    listing = "\n".join(fmt(t, labels, i) for i, t in enumerate(sample))
    print(f"induce: {len(sample)} posts in sample ({dict(Counter(t['kind'] for t in sample))})")

    system = f"""You are a qualitative researcher building a coding scheme for public reactions to an X post. The post is a resignation thread by an AI researcher:

<thread>
{thread_text()}
</thread>

You will be given a large sample of replies and quote tweets. Build a two-level taxonomy of the *kinds of response* people gave. Requirements:
- Categories are about what the response is doing or arguing (its content and rhetorical move), not about tone alone. "Negative" is not a category; "accuses the author of hypocrisy for having taken the salary" is.
- 6 to 10 top-level categories, each with 2 to 6 subcategories. Every subcategory must be common enough to matter (appear at least ~1% of the sample) and distinct enough that a labeller could assign a post to exactly one.
- Cover the whole space: include a small residual subcategory only if genuinely needed, and keep it under 5%.
- Ids are short snake_case. Descriptions say what qualifies and what does not, in one or two sentences. Give 3 example post numbers per subcategory from the sample.
- Estimate each subcategory's share of the sample as a percentage.
Think carefully about the argumentative structure of the discourse: what are the recurring claims, counterclaims, and moves?"""

    schema = {
        "type": "object",
        "properties": {
            "categories": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
                "subcategories": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
                    "example_ids": {"type": "array", "items": {"type": "integer"}},
                    "estimated_share_pct": {"type": "number"},
                }, "required": ["id", "name", "description", "example_ids", "estimated_share_pct"],
                    "additionalProperties": False}},
            }, "required": ["id", "name", "description", "subcategories"], "additionalProperties": False}},
            "notes": {"type": "string", "description": "observations about the discourse structure that the taxonomy does not capture"},
        },
        "required": ["categories", "notes"], "additionalProperties": False,
    }
    c = client()
    with c.messages.stream(
        model=INDUCE_MODEL, max_tokens=32000, system=system,
        messages=[{"role": "user", "content": f"<sample>\n{listing}\n</sample>\n\nBuild the taxonomy."}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        msg = stream.get_final_message()
    text = next(b.text for b in msg.content if b.type == "text")
    tax = json.loads(text)
    # resolve example numbers to post ids + text so the taxonomy file is self-contained
    for cat in tax["categories"]:
        for sub in cat["subcategories"]:
            sub["examples"] = [{"id": sample[i]["id"], "text": sample[i]["text_stripped"][:200]}
                               for i in sub.pop("example_ids") if 0 <= i < len(sample)]
    (DATA / "taxonomy.json").write_text(json.dumps(tax, indent=2, ensure_ascii=False))
    (DATA / "taxonomy_sample.json").write_text(json.dumps([t["id"] for t in sample]))
    print(f"usage: {msg.usage}")
    for cat in tax["categories"]:
        print(f"\n{cat['id']}: {cat['name']}")
        for sub in cat["subcategories"]:
            print(f"   {sub['id']:40} ~{sub['estimated_share_pct']:>4}%  {sub['name']}")
    print("\nnotes:", tax["notes"])


# ---------------------------------------------------------------------------

def assign_system(tax: dict) -> list[dict]:
    lines = []
    for cat in tax["categories"]:
        lines.append(f"## {cat['id']} — {cat['name']}\n{cat['description']}")
        for sub in cat["subcategories"]:
            ex = "; ".join(f"“{e['text'][:120]}”" for e in sub["examples"][:2])
            lines.append(f"- `{sub['id']}` — {sub['name']}: {sub['description']} Examples: {ex}")
    text = f"""You assign public reactions to an X post to a fixed coding scheme. The post is a resignation thread by an AI researcher:

<thread>
{thread_text()}
</thread>

Coding scheme (assign exactly one subcategory id; pick the dominant move if a post makes several):

{chr(10).join(lines)}

For nested replies the parent reply is shown for context; label the post, not the parent. Non-English posts: label on meaning."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def sub_ids(tax: dict) -> list[str]:
    return [s["id"] for c in tax["categories"] for s in c["subcategories"]]


def assign(args) -> None:
    tax = json.loads((DATA / "taxonomy.json").read_text())
    posts, labels = corpus()
    by_id = {t["id"]: t for t in rows(DATA / "all_posts.jsonl")}
    done = {r["id"] for r in rows(DATA / "taxonomy_labels.jsonl") if "error" not in r}
    todo = [t for t in posts if t["id"] not in done]
    if args.limit and not args.sync:
        todo = todo[: args.limit]
    schema = {"type": "object", "properties": {
        "subcategory": {"type": "string", "enum": sub_ids(tax)},
        "addressed_to": {"type": "string", "enum": ["author", "other_commenter", "general_audience"],
                         "description": "who the post is talking to: the thread author, another commenter it replies to or argues with, or its own audience"},
        "confidence": {"type": "number", "description": "0 to 1"}},
        "required": ["subcategory", "addressed_to", "confidence"], "additionalProperties": False}
    system = assign_system(tax)

    def user(t):
        parts = [f"kind: {t['kind']}", f"lang: {t.get('lang')}"]
        if t["depth"] == 2 and t.get("parent_id") in by_id:
            parts.append(f"<parent_reply>\n{by_id[t['parent_id']]['full_text']}\n</parent_reply>")
        parts.append(f"<post>\n{t['full_text']}\n</post>")
        return "\n".join(parts)

    if args.sync:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        rng = random.Random(args.seed)
        rng.shuffle(todo)
        todo = todo[: args.limit or 1000]
        c = client()
        out = DATA / "taxonomy_labels.jsonl"
        print(f"assign --sync: {len(todo)} posts")

        def one(t):
            msg = c.messages.create(**MessageCreateParamsNonStreaming(
                model=ASSIGN_MODEL, max_tokens=1024, system=system,
                messages=[{"role": "user", "content": user(t)}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}}))
            if msg.stop_reason == "refusal":
                return {"id": t["id"], "error": "refusal"}
            return {"id": t["id"], **json.loads(next(b.text for b in msg.content if b.type == "text"))}

        n = 0
        with ThreadPoolExecutor(args.workers) as ex, out.open("a") as f:
            for fut in as_completed([ex.submit(one, t) for t in todo]):
                f.write(json.dumps(fut.result()) + "\n"); n += 1
                if n % 100 == 0:
                    print(f"  {n}/{len(todo)}", flush=True)
        return

    reqs = [Request(custom_id=t["id"], params=MessageCreateParamsNonStreaming(
        model=ASSIGN_MODEL, max_tokens=1024, system=system,
        messages=[{"role": "user", "content": user(t)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )) for t in todo]
    print(f"assign: {len(posts)} posts, {len(done)} done, {len(reqs)} to submit")
    c = client()
    bp = DATA / "taxonomy_batches.json"
    ids = json.loads(bp.read_text()) if bp.exists() else []
    for i in range(0, len(reqs), 10000):
        b = c.messages.batches.create(requests=reqs[i:i + 10000])
        ids.append(b.id)
        print(f"submitted {b.id} ({len(reqs[i:i+10000])} requests)")
    bp.write_text(json.dumps(ids, indent=2))


def collect(args) -> None:
    c = client()
    out = DATA / "taxonomy_labels.jsonl"
    done = {r["id"] for r in rows(out)}
    for bid in json.loads((DATA / "taxonomy_batches.json").read_text()):
        b = c.messages.batches.retrieve(bid)
        print(f"{bid}: {b.processing_status} {b.request_counts}")
        if b.processing_status != "ended":
            continue
        n = 0
        with out.open("a") as f:
            for r in c.messages.batches.results(bid):
                if r.custom_id in done:
                    continue
                if r.result.type == "succeeded" and r.result.message.stop_reason != "refusal":
                    text = next((bk.text for bk in r.result.message.content if bk.type == "text"), "{}")
                    try:
                        rec = {"id": r.custom_id, **json.loads(text)}
                    except json.JSONDecodeError:
                        rec = {"id": r.custom_id, "error": f"bad_json:{r.result.message.stop_reason}"}
                else:
                    rec = {"id": r.custom_id, "error": r.result.type if r.result.type != "succeeded" else "refusal"}
                f.write(json.dumps(rec) + "\n"); done.add(r.custom_id); n += 1
        print(f"  collected {n}")


# ---------------------------------------------------------------------------

def report(args) -> None:
    import xy.pyplot as plt
    tax = json.loads((DATA / "taxonomy.json").read_text())
    sub_to_cat = {s["id"]: c for c in tax["categories"] for s in c["subcategories"]}
    sub_name = {s["id"]: s["name"] for c in tax["categories"] for s in c["subcategories"]}
    posts = {t["id"]: t for t in rows(DATA / "all_posts.jsonl")}
    seen = set()
    labs = []
    for l in rows(DATA / "taxonomy_labels.jsonl"):
        if "error" in l or "subcategory" not in l or l["id"] not in posts or l["id"] in seen or posts[l["id"]]["kind"] not in ("reply", "quote"):
            continue
        seen.add(l["id"]); labs.append(l)
    items = []
    for l in labs:
        t = posts[l["id"]]
        items.append({"id": l["id"], "kind": t["kind"], "sub": l["subcategory"], "cat": sub_to_cat[l["subcategory"]]["id"],
                      "addressed_to": l.get("addressed_to"),
                      "likes": t["public_metrics"].get("like_count", 0), "username": t["username"],
                      "text": t["full_text"], "confidence": l["confidence"],
                      "url": f"https://x.com/{t['username']}/status/{l['id']}"})
    with (DATA / "taxonomy_results.jsonl").open("w") as f:
        for r in items:
            f.write(json.dumps({**r, "sub_name": sub_name[r["sub"]], "cat_name": sub_to_cat[r["sub"]]["name"]}, ensure_ascii=False) + "\n")

    kinds = ["reply", "quote", "all"]
    n = Counter(r["kind"] for r in items); n["all"] = len(items)
    likemass = {k: sum(1 + r["likes"] for r in items if k == "all" or r["kind"] == k) for k in kinds}

    def share(pred, k, weighted):
        sel = [r for r in items if (k == "all" or r["kind"] == k) and pred(r)]
        if weighted:
            return 100 * sum(1 + r["likes"] for r in sel) / likemass[k]
        return 100 * len(sel) / max(1, n[k])

    out = [f"# Response taxonomy for x.com/hilbertspaess/status/{ROOT_ID}\n",
           f"{len(items)} non-spam posts assigned ({dict(Counter(r['kind'] for r in items))}). "
           f"Share = % of posts; weighted = % of like-mass (1+likes).\n",
           "\n| category | subcategory | reply % | quote % | all % | reply wtd | quote wtd | all wtd |\n|---|---|---|---|---|---|---|---|\n"]
    cat_rows = []
    for cat in tax["categories"]:
        cid = cat["id"]
        cat_rows.append((cid, cat["name"], [share(lambda r, c=cid: r["cat"] == c, k, False) for k in kinds],
                         [share(lambda r, c=cid: r["cat"] == c, k, True) for k in kinds]))
    cat_rows.sort(key=lambda x: -x[2][2])
    for cid, name, sh, wt in cat_rows:
        out.append(f"| **{name}** | | " + " | ".join(f"**{v:.1f}**" for v in sh + wt) + " |\n")
        cat = next(c for c in tax["categories"] if c["id"] == cid)
        subs = sorted(cat["subcategories"], key=lambda s: -share(lambda r, s=s: r["sub"] == s["id"], "all", False))
        for s in subs:
            sh = [share(lambda r, s=s: r["sub"] == s["id"], k, False) for k in kinds]
            wt = [share(lambda r, s=s: r["sub"] == s["id"], k, True) for k in kinds]
            out.append(f"| | {s['name']} | " + " | ".join(f"{v:.1f}" for v in sh + wt) + " |\n")

    # figure: category shares by venue
    FIG.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    names = [r[1] for r in cat_rows]
    for i, k in enumerate(["reply", "quote"]):
        ax.barh([j + i * 0.4 for j in range(len(names))], [r[2][i] for r in cat_rows], height=0.4, label=k)
    ax.set_yticks([j + 0.2 for j in range(len(names))]); ax.set_yticklabels(names)
    ax.invert_yaxis(); ax.set_xlabel("% of posts"); ax.set_title("response categories by venue"); ax.legend()
    fig.tight_layout(); fig.savefig(FIG / "taxonomy_categories.png"); plt.close(fig)

    out.append("\n## Categories\n")
    for cid, name, sh, wt in cat_rows:
        cat = next(c for c in tax["categories"] if c["id"] == cid)
        out.append(f"\n### {name} — {sh[2]:.1f}% of posts, {wt[2]:.1f}% of like-mass\n\n{cat['description']}\n")
        for s in cat["subcategories"]:
            rs = sorted((r for r in items if r["sub"] == s["id"]), key=lambda r: -r["likes"])
            out.append(f"\n**{s['name']}** (n={len(rs)}): {s['description']}\n")
            for r in rs[:3]:
                out.append(f"- [{r['likes']} likes, @{r['username']}, {r['kind']}]({r['url']}): {r['text'].replace(chr(10), ' ')[:200]}\n")
    out.append(f"\n## Inducer's notes\n\n{tax['notes']}\n")
    (DATA / "taxonomy_report.md").write_text("".join(out))
    print("".join(out[:3 + len(cat_rows) * 4])[:6000])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["induce", "assign", "collect", "report"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--top-per-kind", type=int, default=150)
    ap.add_argument("--random-per-kind", type=int, default=500)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sync", action="store_true", help="assign synchronously (random sample of --limit)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    {"induce": induce, "assign": assign, "collect": collect, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
