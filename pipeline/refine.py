#!/usr/bin/env python3
"""Propose finer types inside one response type: ./refine.py <sub_id> [--n 400]"""
import argparse, json, random
from pathlib import Path
from taxonomy import DATA, client, corpus, rows, thread_text

ap = argparse.ArgumentParser(); ap.add_argument("sub"); ap.add_argument("--n", type=int, default=400); ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
tax = json.loads((DATA / "taxonomy.json").read_text())
sub = next(s for c in tax["categories"] for s in c["subcategories"] if s["id"] == a.sub)
posts, labels = corpus()
by_id = {t["id"]: t for t in posts}
rs = [r for r in rows(DATA / "taxonomy_results.jsonl") if r["sub"] == a.sub and r["id"] in by_id]
rng = random.Random(a.seed); rng.shuffle(rs)
sample = rs[: a.n]
lines = []
for i, r in enumerate(sample):
    t = by_id[r["id"]]
    gist = f" | gist: {labels[r['id']]['summary']}" if t.get("lang") != "en" and r["id"] in labels else ""
    lines.append(f"[{i}] ({r['kind']}, {r['likes']} likes, {t.get('lang')}) {t['text_stripped'][:240].replace(chr(10),' ')}{gist}")
system = f"""You are refining one code in a coding scheme for reactions to an X post (a resignation thread by an AI researcher warning of catastrophic risk; full thread below).

<thread>
{thread_text()}
</thread>

The code is: "{sub['name']}" — {sub['description']}
It currently holds {len(rs)} posts. Propose 3 to 7 finer types that split it along a distinction a reader would care about (what the post is doing, its object, or its stance), each covering at least ~5% of the sample. For each: id, name, one-sentence description, estimated share of this code, and 3 example numbers. Then say in two sentences whether the split is worth making or the code is already homogeneous."""
schema = {"type": "object", "properties": {
    "types": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
        "share_pct": {"type": "number"}, "example_ids": {"type": "array", "items": {"type": "integer"}}},
        "required": ["id", "name", "description", "share_pct", "example_ids"], "additionalProperties": False}},
    "verdict": {"type": "string"}}, "required": ["types", "verdict"], "additionalProperties": False}
c = client()
with c.messages.stream(model="claude-opus-5", max_tokens=8000, system=system,
                       messages=[{"role": "user", "content": "<sample>\n" + "\n".join(lines) + "\n</sample>"}],
                       output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}}) as st:
    msg = st.get_final_message()
out = json.loads(next(b.text for b in msg.content if b.type == "text"))
print(f"## {sub['name']} ({len(rs)} posts)")
for t in out["types"]:
    ex = "; ".join(by_id[sample[i]["id"]]["text_stripped"][:90].replace("\n", " ") for i in t["example_ids"][:2] if i < len(sample))
    print(f"  {t['share_pct']:>4.0f}%  {t['name']}: {t['description']}\n         e.g. {ex}")
print("  verdict:", out["verdict"])
(DATA / f"refine_{a.sub}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
