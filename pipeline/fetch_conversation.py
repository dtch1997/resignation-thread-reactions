#!/usr/bin/env python3
"""Download an X post plus its full reply tree and quote tweets as raw JSONL.

Official X API v2, pay-per-use billing (~$0.005 per post read). Stdlib only.

    export X_BEARER_TOKEN=...            # or put it in ~/.env
    ./fetch_conversation.py --tweet-id 2097476196791709843 --budget-usd 50

Outputs (in --out, default data/<tweet-id>/):
    root.json      the post itself, with public_metrics (reply/quote counts)
    replies.jsonl  every post sharing the conversation_id (nested replies too)
    quotes.jsonl   every quote tweet of the root
    users.jsonl    author objects returned via expansions
    state.json     reads so far, dollars so far, pagination tokens for resume

Re-running is safe: existing ids are skipped, pagination resumes from
state.json, and the run stops before the cumulative spend exceeds --budget-usd.
"""
from __future__ import annotations

import argparse
import functools
print = functools.partial(print, flush=True)  # noqa: A001 — logs stream when redirected
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = os.environ.get("X_API_BASE", "https://api.x.com/2")

TWEET_FIELDS = ",".join([
    "id", "text", "author_id", "created_at", "conversation_id",
    "in_reply_to_user_id", "referenced_tweets", "public_metrics", "lang",
    "entities", "note_tweet", "possibly_sensitive", "reply_settings", "source",
])
USER_FIELDS = ",".join([
    "id", "username", "name", "created_at", "description", "public_metrics",
    "verified", "verified_type", "location",
])
EXPANSIONS = "author_id,in_reply_to_user_id,referenced_tweets.id,referenced_tweets.id.author_id"


# ----------------------------------------------------------------------------
# auth + http
# ----------------------------------------------------------------------------

def load_token() -> str:
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok:
        env = Path.home() / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if line.startswith("X_BEARER_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        sys.exit("X_BEARER_TOKEN not set (env var or ~/.env). See README.md.")
    return tok


class Client:
    def __init__(self, token: str, price_per_read: float, state: dict):
        self.token = token
        self.price = price_per_read
        self.state = state

    def get(self, path: str, params: dict) -> dict:
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "jarvis-x-conversation-fetch/0.1",
        })
        backoff = 5
        for attempt in range(8):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = json.loads(r.read())
                    self._account(body)
                    return body
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                if e.code == 429:
                    reset = e.headers.get("x-rate-limit-reset")
                    wait = max(5, int(reset) - int(time.time()) + 2) if reset else 60
                    print(f"  429 rate-limited; sleeping {wait}s", file=sys.stderr)
                    time.sleep(wait)
                    continue
                if e.code in (500, 502, 503, 504):
                    print(f"  {e.code} from API; retry in {backoff}s", file=sys.stderr)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                    continue
                sys.exit(f"HTTP {e.code} on {path}: {text[:500]}")
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"  network error {e}; retry in {backoff}s", file=sys.stderr)
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
        sys.exit("gave up after repeated failures")

    def _account(self, body: dict) -> None:
        data = body.get("data")
        n = len(data) if isinstance(data, list) else (1 if data else 0)
        # Expanded referenced tweets are also returned as post objects; X bills
        # post reads, so count those too (conservative).
        n += len(body.get("includes", {}).get("tweets", []))
        self.state["reads"] = self.state.get("reads", 0) + n
        self.state["usd"] = round(self.state["reads"] * self.price, 4)

    def usd(self) -> float:
        return self.state.get("usd", 0.0)


# ----------------------------------------------------------------------------
# io helpers
# ----------------------------------------------------------------------------

def load_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(l)["id"] for l in path.read_text().split("\n") if l.strip()}


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2))


def snowflake_time(tweet_id: str) -> dt.datetime:
    ms = (int(tweet_id) >> 22) + 1288834974657
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


# ----------------------------------------------------------------------------
# collection passes
# ----------------------------------------------------------------------------

def paginate(client: Client, path: str, params: dict, *, out: Path, users_out: Path,
             source: str, state_key: str, state: dict, state_path: Path,
             budget_usd: float, token_param: str) -> int:
    """Walk one paginated endpoint, appending new posts to `out`. Returns #new."""
    seen = load_ids(out)
    seen_users = load_ids(users_out)
    new_total = 0
    next_token = state.get(state_key, {}).get("next_token")
    if state.get(state_key, {}).get("done"):
        print(f"[{source}] already complete per state.json; skipping (delete key to redo)")
        return 0
    page = 0
    while True:
        if client.usd() >= budget_usd:
            print(f"[{source}] budget ${budget_usd:.2f} reached at ${client.usd():.2f}; stopping "
                  f"(re-run with a higher --budget-usd to resume)")
            break
        p = dict(params)
        if next_token:
            p[token_param] = next_token
        body = client.get(path, p)
        page += 1
        rows = body.get("data", []) or []
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        fresh = []
        for t in rows:
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            t["_source"] = source
            t["_fetched_at"] = now
            fresh.append(t)
        append_jsonl(out, fresh)
        new_total += len(fresh)
        users = [u for u in body.get("includes", {}).get("users", []) if u["id"] not in seen_users]
        for u in users:
            seen_users.add(u["id"])
        append_jsonl(users_out, users)
        next_token = body.get("meta", {}).get("next_token")
        state[state_key] = {"next_token": next_token, "done": next_token is None, "pages": page}
        save_state(state_path, state)
        print(f"[{source}] page {page}: +{len(fresh)} new ({len(rows)} returned) | "
              f"reads={state['reads']} spent=${client.usd():.2f}")
        if not next_token:
            break
    return new_total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tweet-id", default="2097476196791709843")
    ap.add_argument("--out", type=Path, default=None, help="output dir (default data/<tweet-id>)")
    ap.add_argument("--budget-usd", type=float, default=50.0, help="hard stop on cumulative spend")
    ap.add_argument("--price-per-read", type=float, default=0.005, help="USD per post read")
    ap.add_argument("--skip-replies", action="store_true")
    ap.add_argument("--skip-quotes", action="store_true")
    ap.add_argument("--full-archive", action="store_true",
                    help="use /search/all instead of /search/recent (post older than 7 days)")
    ap.add_argument("--query", default=None,
                    help="override the reply-pass search query (default conversation_id:<tweet-id>)")
    ap.add_argument("--exclude-retweets", action="store_true",
                    help="quote pass: drop retweets of quote tweets (the endpoint interleaves them by default)")
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask before the paid passes")
    args = ap.parse_args()

    out = args.out or Path(__file__).parent / "data" / args.tweet_id
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"reads": 0, "usd": 0.0}
    client = Client(load_token(), args.price_per_read, state)

    # pass 1: the root post ---------------------------------------------------
    root_path = out / "root.json"
    body = client.get(f"/tweets/{args.tweet_id}", {
        "tweet.fields": TWEET_FIELDS, "user.fields": USER_FIELDS, "expansions": "author_id",
    })
    if "data" not in body:
        sys.exit(f"root fetch returned no data: {json.dumps(body)[:800]}")
    root_path.write_text(json.dumps(body, indent=2, ensure_ascii=False))
    save_state(state_path, state)
    root = body["data"]
    m = root.get("public_metrics", {})
    author = (body.get("includes", {}).get("users") or [{}])[0].get("username", "?")
    posted = snowflake_time(args.tweet_id)
    age_days = (dt.datetime.now(dt.timezone.utc) - posted).total_seconds() / 86400
    print(f"root: @{author} posted {posted:%Y-%m-%d %H:%M} UTC ({age_days:.1f} days ago)")
    print(f"      {root['text'][:140]!r}")
    print(f"      metrics: {m}")
    est_reads = m.get("reply_count", 0) + m.get("quote_count", 0)
    est_usd = est_reads * args.price_per_read
    print(f"estimated: >= {est_reads} reads (direct replies + quotes; nested replies add more) "
          f"≈ ${est_usd:.2f} at ${args.price_per_read}/read; budget ${args.budget_usd:.2f}")
    if age_days > 7 and not args.full_archive:
        print("WARNING: post is older than 7 days; /search/recent will miss early replies. "
              "Re-run with --full-archive.", file=sys.stderr)
    if not args.yes:
        ans = input("proceed with paid passes? [y/N] ").strip().lower()
        if ans != "y":
            print("aborted after root fetch")
            return

    # pass 2: replies via conversation_id search -------------------------------
    if not args.skip_replies:
        search_path = "/tweets/search/all" if args.full_archive else "/tweets/search/recent"
        paginate(
            client, search_path,
            {"query": args.query or f"conversation_id:{args.tweet_id}", "max_results": 100,
             "tweet.fields": TWEET_FIELDS, "user.fields": USER_FIELDS, "expansions": EXPANSIONS,
             "sort_order": "recency"},
            out=out / "replies.jsonl", users_out=out / "users.jsonl", source="reply",
            state_key="replies", state=state, state_path=state_path,
            budget_usd=args.budget_usd, token_param="next_token",
        )

    # pass 3: quote tweets ----------------------------------------------------
    if not args.skip_quotes:
        paginate(
            client, f"/tweets/{args.tweet_id}/quote_tweets",
            {"max_results": 100, "tweet.fields": TWEET_FIELDS,
             "user.fields": USER_FIELDS, "expansions": EXPANSIONS,
             **({"exclude": "retweets"} if args.exclude_retweets else {})},
            out=out / "quotes.jsonl", users_out=out / "users.jsonl", source="quote",
            state_key="quotes", state=state, state_path=state_path,
            budget_usd=args.budget_usd, token_param="pagination_token",
        )

    n_r = len(load_ids(out / "replies.jsonl"))
    n_q = len(load_ids(out / "quotes.jsonl"))
    n_u = len(load_ids(out / "users.jsonl"))
    print(f"done: {n_r} replies, {n_q} quotes, {n_u} users | reads={state['reads']} "
          f"spent≈${client.usd():.2f} | files in {out}")


if __name__ == "__main__":
    main()
