#!/usr/bin/env python3
"""Label every post in all_posts.jsonl for sentiment and stance with Claude.

    ./classify.py --sync --limit 40          # quick synchronous sample → labels.jsonl
    ./classify.py --batch                    # submit the rest via the Batches API (50% price)
    ./classify.py --collect                  # pull finished batch results → labels.jsonl

Labels are keyed on post id; already-labelled ids are skipped on every mode,
so the three modes compose and re-runs are idempotent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

MODEL = "claude-opus-5"
ROOT_ID = "2097476196791709843"

SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral", "mixed"],
                       "description": "overall emotional tone of the post"},
        "stance_author": {"type": "string", "enum": ["supportive", "critical", "mixed", "neutral"],
                           "description": "attitude toward the author and their decision to resign and speak out"},
        "stance_claim": {"type": "string", "enum": ["agree", "disagree", "mixed", "not_addressed"],
                          "description": "position on the author's core claim: the labs are racing irresponsibly toward superintelligence and gambling with our lives"},
        "frame": {"type": "string", "enum": [
            "solidarity_or_praise", "ai_risk_agreement", "ai_risk_dismissal_or_hype_skepticism",
            "hypocrisy_or_grift_accusation", "lab_comparison_anthropic_vs_openai",
            "policy_regulation_or_coordination", "mockery_or_personal_attack",
            "question_or_request", "news_relay_or_neutral_summary", "off_topic_or_spam", "other"],
            "description": "the single dominant frame of the post"},
        "targets": {"type": "array", "items": {"type": "string", "enum": [
            "author", "anthropic", "openai", "ai_industry", "ai_safety_community",
            "government_or_regulators", "public", "none"]},
            "description": "who the post is mainly about or addressed to"},
        "is_bot_or_spam": {"type": "boolean"},
        "summary": {"type": "string", "description": "the post's point in at most 15 words"},
        "confidence": {"type": "number", "description": "0 to 1"},
    },
    "required": ["sentiment", "stance_author", "stance_claim", "frame", "targets",
                 "is_bot_or_spam", "summary", "confidence"],
    "additionalProperties": False,
}


def rows(p: Path):
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                yield json.loads(line)


def build_system(data: Path) -> list[dict]:
    root = json.loads((data / "root.json").read_text())["data"]
    thread = [t for t in rows(data / "all_posts.jsonl") if t["kind"] == "thread"]
    thread_text = "\n\n".join([root["text"]] + [t["full_text"] for t in sorted(thread, key=lambda t: t["created_at"])])
    text = f"""You label public reactions to an X post for a sentiment study. The post is a resignation announcement by an AI researcher (@hilbertspaess). The author's full thread:

<thread>
{thread_text}
</thread>

You will receive one reaction at a time: a reply (direct, or nested under another reply, in which case the parent reply is shown) or a quote tweet (commentary posted alongside the thread). Label it with the schema. Notes:
- `stance_author` is about the person and their act of resigning and speaking out; `stance_claim` is about the substantive claim (labs racing irresponsibly, real risk of catastrophe). A post can praise the author while disagreeing with the claim, or vice versa.
- Sarcasm and irony are common; read for intended meaning.
- Non-English posts: label on meaning, do not translate in the summary.
- Bots, engagement farming, crypto spam, and reply-guy templates get `is_bot_or_spam: true` and frame `off_topic_or_spam`.
- `confidence` reflects how clear the intended meaning is; short or ambiguous posts get lower values."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def build_user(t: dict, by_id: dict[str, dict]) -> str:
    parts = [f"kind: {t['kind']}", f"depth: {t['depth']}", f"lang: {t.get('lang', '?')}",
             f"author followers: {t.get('followers')}",
             f"metrics: likes={t['public_metrics'].get('like_count')} replies={t['public_metrics'].get('reply_count')}"]
    if t["depth"] == 2 and t.get("parent_id") in by_id:
        parts.append(f"<parent_reply>\n{by_id[t['parent_id']]['full_text']}\n</parent_reply>")
    parts.append(f"<post>\n{t['full_text']}\n</post>")
    return "\n".join(parts)


def params(system: list[dict], user: str) -> MessageCreateParamsNonStreaming:
    return MessageCreateParamsNonStreaming(
        model=MODEL, max_tokens=512, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )


def parse(msg) -> dict:
    if msg.stop_reason == "refusal":
        return {"error": "refusal"}
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "bad_json", "raw": text[:300]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / ROOT_ID)
    ap.add_argument("--sync", action="store_true", help="label synchronously (threads)")
    ap.add_argument("--batch", action="store_true", help="submit unlabelled posts as a Message Batch")
    ap.add_argument("--collect", action="store_true", help="collect results of submitted batches")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        for line in (Path.home() / ".env").read_text().split("\n"):
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    client = anthropic.Anthropic()

    posts = [t for t in rows(args.data / "all_posts.jsonl") if t["kind"] in ("reply", "quote")]
    by_id = {t["id"]: t for t in rows(args.data / "all_posts.jsonl")}
    labels_path = args.data / "labels.jsonl"
    done = {r["id"] for r in rows(labels_path)}
    todo = [t for t in posts if t["id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    system = build_system(args.data)
    print(f"{len(posts)} posts, {len(done)} labelled, {len(todo)} to do")

    def write(rs: list[dict]) -> None:
        with labels_path.open("a") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if args.sync:
        usage = {"in": 0, "out": 0, "cache_read": 0}

        def one(t):
            msg = client.messages.create(**params(system, build_user(t, by_id)))
            usage["in"] += msg.usage.input_tokens; usage["out"] += msg.usage.output_tokens
            usage["cache_read"] += msg.usage.cache_read_input_tokens or 0
            return {"id": t["id"], **parse(msg)}

        results = []
        with ThreadPoolExecutor(args.workers) as ex:
            for fut in as_completed([ex.submit(one, t) for t in todo]):
                results.append(fut.result())
                if len(results) % 20 == 0:
                    print(f"  {len(results)}/{len(todo)}")
        write(results)
        print(f"labelled {len(results)}; tokens in={usage['in']} (cache_read={usage['cache_read']}) out={usage['out']}")

    if args.batch:
        reqs = [Request(custom_id=t["id"], params=params(system, build_user(t, by_id))) for t in todo]
        ids = []
        for i in range(0, len(reqs), 10000):
            b = client.messages.batches.create(requests=reqs[i:i + 10000])
            ids.append(b.id)
            print(f"submitted batch {b.id} with {len(reqs[i:i+10000])} requests")
        bp = args.data / "batches.json"
        prev = json.loads(bp.read_text()) if bp.exists() else []
        bp.write_text(json.dumps(prev + ids, indent=2))

    if args.collect:
        bp = args.data / "batches.json"
        for bid in json.loads(bp.read_text()):
            b = client.messages.batches.retrieve(bid)
            print(f"{bid}: {b.processing_status} {b.request_counts}")
            if b.processing_status != "ended":
                continue
            results = []
            for r in client.messages.batches.results(bid):
                if r.custom_id in done:
                    continue
                if r.result.type == "succeeded":
                    results.append({"id": r.custom_id, **parse(r.result.message)})
                else:
                    results.append({"id": r.custom_id, "error": r.result.type})
            write(results)
            done.update(r["id"] for r in results)
            print(f"  collected {len(results)}")


if __name__ == "__main__":
    main()
