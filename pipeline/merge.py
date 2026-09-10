#!/usr/bin/env python3
"""Union every download directory for one post into data/<id>/all_posts.jsonl.

Replies come from several query styles (conversation_id, in_reply_to_tweet_id,
to:author, full-archive), each in its own data/<id>-<suffix>/ dir; quotes from
the main dir. Dedupes on id, keeps the first copy, tags each row with `kind`
(reply|quote|thread) and `depth` (1 = direct reply to root, 2 = deeper).

    ./merge.py [tweet-id]
"""
import json
import re
import sys
from pathlib import Path


def rows(p: Path):
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                yield json.loads(line)


def main() -> None:
    root_id = sys.argv[1] if len(sys.argv) > 1 else "2097476196791709843"
    data = Path(__file__).parent / "data"
    main_dir = data / root_id
    root = json.loads((main_dir / "root.json").read_text())
    author = root["data"]["author_id"]

    users: dict[str, dict] = {}
    posts: dict[str, dict] = {}
    sources: dict[str, list[str]] = {}
    for d in sorted(data.glob(f"{root_id}*")):
        if not d.is_dir():
            continue
        for u in rows(d / "users.jsonl"):
            users.setdefault(u["id"], u)
        for fname in ["replies.jsonl", "quotes.jsonl"]:
            for t in rows(d / fname):
                if t["id"] == root_id:
                    continue
                refs = {r["type"]: r["id"] for r in t.get("referenced_tweets", [])}
                # classify by what the post references, not by which file it came from
                if "retweeted" in refs or t.get("text", "").startswith("RT @"):
                    kind = "retweet"
                elif t.get("conversation_id") == root_id:
                    kind = "reply"
                elif refs.get("quoted") == root_id or root_id in json.dumps(t.get("entities", {})):
                    kind = "quote"
                else:
                    continue
                sources.setdefault(t["id"], []).append(d.name.replace(root_id, "") or "-conv")
                if t["id"] in posts:
                    continue
                parent = refs.get("replied_to", "")
                t["kind"] = "thread" if (kind == "reply" and t["author_id"] == author) else kind
                t["depth"] = (1 if parent == root_id else 2) if kind == "reply" else 0
                t["parent_id"] = parent
                t["retweet_of"] = refs.get("retweeted", "")
                t["full_text"] = (t.get("note_tweet") or {}).get("text") or t.get("text", "")
                urls = (t.get("entities") or {}).get("urls", [])
                t["has_media"] = any("/photo/" in u.get("expanded_url", "") or "/video/" in u.get("expanded_url", "")
                                     or u.get("display_url", "").startswith("pic.") for u in urls)
                stripped = re.sub(r"https?://\S+|@\w+", "", t["full_text"]).strip()
                t["text_stripped"] = stripped
                t["media_only"] = t["has_media"] and not stripped
                u = users.get(t["author_id"], {})
                t["username"] = u.get("username", "")
                t["followers"] = u.get("public_metrics", {}).get("followers_count")
                posts[t["id"]] = t
    for pid, t in posts.items():
        t["sources"] = sorted(set(sources[pid]))

    out = main_dir / "all_posts.jsonl"
    with out.open("w") as f:
        for t in sorted(posts.values(), key=lambda t: t["created_at"]):
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with (main_dir / "all_users.jsonl").open("w") as f:
        for u in users.values():
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    from collections import Counter
    c = Counter((t["kind"], t["depth"]) for t in posts.values())
    print(f"wrote {len(posts)} posts to {out}: {dict(c)}; {len(users)} users")


if __name__ == "__main__":
    main()
