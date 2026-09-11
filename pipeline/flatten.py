#!/usr/bin/env python3
"""Flatten data/<tweet-id>/*.jsonl into one tweets.csv for sentiment work.

    ./flatten.py data/2097476196791709843   # writes tweets.csv next to the jsonl
"""
import csv
import json
import sys
from pathlib import Path


def rows(path: Path):
    if path.exists():
        for line in path.read_text().split("\n"):
            if line.strip():
                yield json.loads(line)


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "data/2097476196791709843")
    users = {u["id"]: u for u in rows(d / "users.jsonl")}
    root = json.loads((d / "root.json").read_text())
    for u in root.get("includes", {}).get("users", []):
        users.setdefault(u["id"], u)
    root_id = root["data"]["id"]

    out = d / "tweets.csv"
    fields = ["id", "kind", "depth", "created_at", "author_id", "username", "followers",
              "in_reply_to", "lang", "likes", "replies", "retweets", "quotes", "impressions", "text"]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        n = 0
        for kind, src in [("root", [root["data"]]), ("reply", rows(d / "replies.jsonl")),
                          ("quote", rows(d / "quotes.jsonl"))]:
            for t in src:
                if kind == "reply" and t["id"] == root_id:
                    continue  # search returns the root itself; keep one copy
                pm = t.get("public_metrics", {})
                u = users.get(t.get("author_id"), {})
                parent = next((r["id"] for r in t.get("referenced_tweets", []) if r["type"] == "replied_to"), "")
                text = (t.get("note_tweet") or {}).get("text") or t.get("text", "")
                w.writerow({
                    "id": t["id"], "kind": kind,
                    "depth": 0 if kind == "root" else (1 if parent == root_id else 2),
                    "created_at": t.get("created_at", ""), "author_id": t.get("author_id", ""),
                    "username": u.get("username", ""),
                    "followers": u.get("public_metrics", {}).get("followers_count", ""),
                    "in_reply_to": parent, "lang": t.get("lang", ""),
                    "likes": pm.get("like_count", ""), "replies": pm.get("reply_count", ""),
                    "retweets": pm.get("retweet_count", ""), "quotes": pm.get("quote_count", ""),
                    "impressions": pm.get("impression_count", ""), "text": text,
                })
                n += 1
    print(f"wrote {n} rows to {out}")


if __name__ == "__main__":
    main()
