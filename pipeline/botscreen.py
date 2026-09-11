#!/usr/bin/env python3
"""Account-level screen for dedicated AI-content / engagement-bot accounts.

    ./botscreen.py --limit 40 --usernames syncshiftstudio,the_moment2746   # sanity check
    ./botscreen.py                                                          # all candidate accounts → data/<id>/bot_accounts.jsonl

Candidates: every account in taxonomy_results.jsonl with >=3 posts in the thread or any post
>= 200 characters (short posts are not worth screening and not detectable). Claude Opus 5 sees
the account profile, its activity ratio, and up to 5 of its posts here, and returns
p_bot (probability the account is a dedicated bot or AI-generated-content account, as
opposed to a person who may have used AI to polish one post). Already-screened accounts are skipped.
"""
from __future__ import annotations
import argparse, json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import anthropic

ROOT_ID = "2097476196791709843"
MODEL = "claude-opus-5"
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["p_bot", "kind", "reasons"],
          "properties": {
              "p_bot": {"type": "number", "description": "0-1 probability this is a dedicated bot / AI-content account"},
              "kind": {"type": "string", "enum": ["person", "person_ai_assisted", "ai_content_account", "reply_bot", "brand_or_media", "unclear"]},
              "reasons": {"type": "string", "description": "<= 30 words"}}}
SYSTEM = [{"type": "text", "cache_control": {"type": "ephemeral"}, "text": """You screen X accounts that replied to or quoted a viral post (an AI researcher's resignation thread) for a reaction study. The study wants ordinary people's reactions, so it must exclude dedicated bot accounts: automated reply farms, accounts whose output is wholesale LLM-generated commentary posted at volume for engagement or promotion, and reply-guy templates. It must NOT exclude real people who wrote a polished post, non-native speakers, journalists, politicians, or brands (label those brand_or_media, low p_bot).

Signals of an AI-content account: recently created; very high tweet count per day of age; bio is a generic AI/SaaS/"building in public"/growth-hacking pitch or empty; many posts in this one thread; posts are long, structurally similar, essayistic, with LLM tics (em-dashes, "It's not X. It's Y.", "The most important part is not A, it's B", abstract nouns like positional advantage / coordination / governance, no typos, no slang, no reference to the writer's own life); posts do not address anyone in particular. A single polished post from an old account with a real bio and a normal tweet rate is a person (person or person_ai_assisted, p_bot <= 0.3).

Return JSON per the schema. Calibrate p_bot: 0.9+ only when several signals align."""}]

def rows(p):
    out = []
    for l in Path(p).read_text().split("\n"):
        if l.strip():
            try: out.append(json.loads(l))
            except json.JSONDecodeError: pass
    return out

def profile(u, posts, fetched):
    pm = u.get("public_metrics", {}); created = u.get("created_at", "")
    age_days = max(1, (fetched - datetime.fromisoformat(created.replace("Z", "+00:00"))).days) if created else None
    lines = [f"username: @{u.get('username')}", f"name: {u.get('name')}", f"created: {created[:10]}  (age {age_days} days)",
             f"tweets: {pm.get('tweet_count')}  ({pm.get('tweet_count', 0) / age_days:.1f} per day of age)" if age_days else f"tweets: {pm.get('tweet_count')}",
             f"followers: {pm.get('followers_count')}  following: {pm.get('following_count')}  listed: {pm.get('listed_count')}",
             f"verified: {u.get('verified')} ({u.get('verified_type')})", f"bio: {u.get('description', '')!r}",
             f"posts by this account in the thread: {len(posts)}"]
    for i, p in enumerate(sorted(posts, key=lambda p: -len(p["text"]))[:5]):
        lines.append(f"<post kind={p['kind']} likes={p['likes']}>\n{p['text']}\n</post>")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / ROOT_ID)
    ap.add_argument("--limit", type=int); ap.add_argument("--usernames", help="comma-separated, forced into the sample")
    ap.add_argument("--workers", type=int, default=12); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        for line in (Path.home() / ".env").read_text().split("\n"):
            if line.startswith("ANTHROPIC_API_KEY="): os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    P = {r["id"]: r for r in rows(a.data / "all_posts.jsonl")}; U = {u["id"]: u for u in rows(a.data / "all_users.jsonl")}
    T = rows(a.data / "taxonomy_results.jsonl")
    fetched = datetime.fromisoformat(next(iter(P.values()))["_fetched_at"])
    by = {}
    for t in T:
        p = P[t["id"]]; by.setdefault(p["author_id"], []).append({"kind": t["kind"], "likes": int(t["likes"]), "text": p.get("full_text") or t["text"]})
    cand = [aid for aid, ps in by.items() if aid in U and (len(ps) >= 3 or any(len(p["text"]) >= 200 for p in ps))]
    out_path = a.data / "bot_accounts.jsonl"; done = {r["author_id"] for r in rows(out_path)} if out_path.exists() else set()
    forced = set(a.usernames.split(",")) if a.usernames else set()
    todo = [aid for aid in cand if aid not in done and (not forced or U[aid]["username"] in forced)]
    if a.limit and not forced: todo = todo[:a.limit]
    elif a.limit: todo = todo + [aid for aid in cand if aid not in done and U[aid]["username"] not in forced][:a.limit]
    print(f"candidates {len(cand)}, screened {len(done)}, to do {len(todo)}", file=sys.stderr)
    if a.dry: print(profile(U[todo[0]], by[todo[0]], fetched)); return
    client = anthropic.Anthropic()
    def one(aid):
        msg = client.messages.create(model=MODEL, max_tokens=300, system=SYSTEM,
                                     messages=[{"role": "user", "content": profile(U[aid], by[aid], fetched)}],
                                     output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
        if msg.stop_reason == "refusal": return {"author_id": aid, "username": U[aid]["username"], "error": "refusal"}
        r = json.loads(next(b.text for b in msg.content if b.type == "text"))
        return {"author_id": aid, "username": U[aid]["username"], "n_posts": len(by[aid]), **r}
    with out_path.open("a") as f, ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, aid): aid for aid in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            try: r = fu.result()
            except Exception as e: r = {"author_id": futs[fu], "username": U[futs[fu]]["username"], "error": repr(e)[:200]}
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
            if i % 100 == 0 or i == len(todo): print(f"{i}/{len(todo)}", file=sys.stderr)
            if forced or (a.limit and a.limit <= 60): print(f"  {r.get('p_bot', '?'):>5} {r.get('kind', r.get('error')):20s} @{r['username']:20s} {r.get('reasons', '')[:110]}")

if __name__ == "__main__": main()
