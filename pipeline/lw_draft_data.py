#!/usr/bin/env python3
"""Numbers, example candidates and theme-aware SVG figures for the LW narrative draft.

    ./lw_draft_data.py   # → blogpost/stats.json, blogpost/examples.json, blogpost/fig_*.svg
"""
import json, collections, statistics, random
from pathlib import Path

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
OUT = Path(__file__).parent.parent / "blogpost"
OUT.mkdir(exist_ok=True)
NORMIE = 1000

def rows(f):
    out = []
    for l in (DATA / f).read_text().split("\n"):
        if l.strip():
            try: out.append(json.loads(l))
            except json.JSONDecodeError: pass
    return out

P = {r["id"]: r for r in rows("all_posts.jsonl")}
L = {r["id"]: r for r in rows("labels.jsonl")}
T = rows("taxonomy_results.jsonl")
TR = json.loads((DATA / "translations.json").read_text())
ROOT = json.loads((DATA / "root.json").read_text()); ROOT = ROOT.get("data", ROOT)
for t in T:
    t["likes"] = int(t["likes"]); t["confidence"] = float(t["confidence"])
    p = P[t["id"]]; t["followers"] = p.get("followers"); t["lang"] = p.get("lang")
    t["stance"] = L[t["id"]]["stance_claim"]; t["full"] = p.get("full_text") or p.get("text")
ids = [t["id"] for t in T]

def stance_split(sub):
    c = collections.Counter(t["stance"] for t in sub)
    n = sum(c.values()); ad = c["agree"] + c["disagree"]
    return {"n": n, "agree": c["agree"], "mixed": c["mixed"], "disagree": c["disagree"], "not_addressed": c["not_addressed"],
            "agree_pct_of_ad": round(100 * c["agree"] / ad, 1) if ad else None,
            "pct": {k: round(100 * c[k] / n, 1) for k in ("agree", "mixed", "disagree", "not_addressed")}}

normie = lambda t: isinstance(t["followers"], (int, float)) and t["followers"] < NORMIE
slices = collections.OrderedDict([
    ("All posts", T),
    ("Quote tweets", [t for t in T if t["kind"] == "quote"]),
    ("Replies", [t for t in T if t["kind"] == "reply"]),
    (f"Quote tweets, accounts under {NORMIE:,} followers", [t for t in T if t["kind"] == "quote" and normie(t)]),
    (f"Replies, accounts under {NORMIE:,} followers", [t for t in T if t["kind"] == "reply" and normie(t)]),
])
stance = {k: stance_split(v) for k, v in slices.items()}

MOVES = [("Expresses a reaction", ["existential_reaction", "cultural_framing"]),
         ("Comments on the author", ["endorse_amplify", "author_attacks"]),
         ("Engages with substance", ["risk_substance", "risk_denial", "race_logic", "policy_power", "exit_critique"]),
         ("Noise and meta", ["meta_and_noise"])]
cat_n = collections.Counter(t["cat"] for t in T); cat_l = collections.Counter()
for t in T: cat_l[t["cat"]] += t["likes"]
N = len(T); LT = sum(cat_l.values())
cat_names = {t["cat"]: t["cat_name"] for t in T}
sub_n = collections.Counter(t["sub"] for t in T); sub_names = {t["sub"]: t["sub_name"] for t in T}
fol = [t["followers"] for t in T if isinstance(t["followers"], (int, float))]
langs = collections.Counter(t["lang"] for t in T)

OBJ_CATS = {"author_attacks": "Attacks the messenger", "risk_denial": "Denies the risk", "race_logic": "Race logic", "exit_critique": "Other"}
OBJ_EXTRA = {"capitalism_incentive_critique": "Other", "conspiracy_psyop": "Other"}
obj = []
for s, n in sub_n.most_common():
    cat = next(t["cat"] for t in T if t["sub"] == s)
    if cat in OBJ_CATS or s in OBJ_EXTRA:
        obj.append({"sub": s, "name": sub_names[s], "group": OBJ_CATS.get(cat, "Other"), "n": n, "pct": round(100 * n / N, 1)})
obj = [o for o in obj if o["sub"] != "rejects_race_framing"]  # a rebuttal, not an objection

stats = {
    "root_metrics": ROOT.get("public_metrics"), "fetched_at": next(iter(P.values())).get("_fetched_at"),
    "n_posts": N, "n_reply": sum(t["kind"] == "reply" for t in T), "n_quote": sum(t["kind"] == "quote" for t in T),
    "followers": {"median": statistics.median(fol), "share_under_100": round(100 * sum(f < 100 for f in fol) / len(fol), 1),
                  "share_under_1k": round(100 * sum(f < 1000 for f in fol) / len(fol), 1), "share_under_10k": round(100 * sum(f < 10000 for f in fol) / len(fol), 1)},
    "langs": [(k, round(100 * v / N, 1)) for k, v in langs.most_common(8)],
    "stance": stance,
    "moves": [{"move": m, "pct": round(100 * sum(cat_n[c] for c in cs) / N, 1), "likes_pct": round(100 * sum(cat_l[c] for c in cs) / LT, 1),
               "cats": [{"cat": c, "name": cat_names[c], "n": cat_n[c], "pct": round(100 * cat_n[c] / N, 1), "likes_pct": round(100 * cat_l[c] / LT, 1)} for c in cs]} for m, cs in MOVES],
    "top_subtypes": [{"sub": s, "name": sub_names[s], "n": n, "pct": round(100 * n / N, 1)} for s, n in sub_n.most_common(8)],
    "objections": obj, "objections_total": sum(o["n"] for o in obj),
    "addressed_to": collections.Counter(t["addressed_to"] for t in T).most_common(),
    "substance_share": round(100 * sum(cat_n[c] for c in MOVES[2][1]) / N, 1),
}
(OUT / "stats.json").write_text(json.dumps(stats, indent=1))

# ---- example candidates -------------------------------------------------------
random.seed(7)
def cands(sub, k=4, kind=None, only_normie=False, stance_=None):
    pool = [t for t in T if t["sub"] == sub and t["confidence"] >= 0.8 and (kind is None or t["kind"] == kind)
            and (not only_normie or normie(t)) and (stance_ is None or t["stance"] == stance_)]
    pool = [t for t in pool if t["lang"] == "en" or t["id"] in TR]
    top = sorted(pool, key=lambda t: -t["likes"])[:k]
    rest = [t for t in pool if t not in top and 40 < len(t["full"]) < 400]
    rnd = random.sample(rest, min(2, len(rest)))
    return [{"id": t["id"], "user": t["username"], "kind": t["kind"], "likes": t["likes"], "followers": t["followers"], "lang": t["lang"],
             "text": t["full"], "translation": TR.get(t["id"]), "url": t["url"]} for t in top + rnd]
WANT = ["generic_alarm_exclamation", "fatalist_doom_humor", "scifi_pop_culture", "must_read_relay", "substantive_agreement", "praise_support_author",
        "personal_fear_anxiety", "regulation_ban_calls", "asks_for_mechanism", "supplies_scenario", "prepper_practical", "virality_metrics",
        "marketing_ipo_stunt", "doomer_cult_label", "bot_fake_clout", "personal_insult", "not_real_intelligence", "capitalism_incentive_critique",
        "china_must_win", "rejects_race_framing", "hypocrisy_profit", "inevitability_genie", "conspiracy_psyop", "accelerationist_upside",
        "just_unplug_it", "demand_falsifiable_evidence", "should_have_stayed", "demand_bolder_action", "prior_tech_panic_analogy"]
ex = {s: cands(s) for s in WANT}
ex["_normie_agree_replies"] = cands("substantive_agreement", k=4, kind="reply", only_normie=True) + cands("praise_support_author", k=3, kind="reply", only_normie=True)
(OUT / "examples.json").write_text(json.dumps(ex, indent=1, ensure_ascii=False))

# ---- figures (inline-SVG, colors via CSS custom properties of the host page) ----
def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;")
def svg_stance():
    rows_ = list(stance.items()); W, H = 760, 44 * len(rows_) + 60; LW_ = 300; BW = W - LW_ - 20
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="fig" role="img" aria-label="Stance toward the claim by venue and account size">']
    o.append('<style>.fig text{font-family:var(--font-ui);font-size:13px;fill:var(--ink-2)} .fig .lbl{fill:var(--ink)} .fig .in{fill:#fff;font-weight:600}</style>')
    for i, (name, s) in enumerate(rows_):
        y = 20 + i * 44; x = LW_
        o.append(f'<text x="{LW_-12}" y="{y+16}" text-anchor="end" class="lbl">{esc(name)}</text>')
        for key, var in (("agree", "--c-agree"), ("mixed", "--c-mixed"), ("disagree", "--c-disagree"), ("not_addressed", "--c-none")):
            w = BW * s["pct"][key] / 100
            o.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w-2,0):.1f}" height="22" fill="var({var})"/>')
            if w > 34: o.append(f'<text x="{x+w/2:.1f}" y="{y+16}" text-anchor="middle" class="in">{s["pct"][key]:.0f}%</text>')
            x += w
        o.append(f'<text x="{LW_}" y="{y+36}" font-size="11">n = {s["n"]:,}</text>')
    ly = H - 14; lx = LW_
    for key, var, lab in (("agree", "--c-agree", "Agrees with the claim"), ("mixed", "--c-mixed", "Mixed"), ("disagree", "--c-disagree", "Disagrees"), ("not_addressed", "--c-none", "Takes no position")):
        o.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" fill="var({var})"/><text x="{lx+16}" y="{ly}">{lab}</text>'); lx += 16 + 7.2 * len(lab) + 22
    o.append("</svg>"); return "\n".join(o)

def svg_moves():
    W = 760; rowh = 26; items = []
    for m in stats["moves"]:
        items.append(("move", m["move"], m["pct"], m["likes_pct"]))
        for c in m["cats"]: items.append(("cat", c["name"], c["pct"], c["likes_pct"]))
    H = rowh * len(items) + 50; LW_ = 330; BW = W - LW_ - 90; mx = max(i[2] for i in items)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="fig" role="img" aria-label="Share of posts by category, grouped into four moves">',
         '<style>.fig text{font-family:var(--font-ui);font-size:13px;fill:var(--ink-2)} .fig .mv{fill:var(--ink);font-weight:600} .fig .v{fill:var(--ink);font-variant-numeric:tabular-nums}</style>',
         f'<text x="{LW_}" y="14" font-size="11">share of posts</text><text x="{W-4}" y="14" font-size="11" text-anchor="end">share of likes</text>']
    y = 24
    for kind, name, pct, lp in items:
        if kind == "move":
            y += 8; o.append(f'<text x="{LW_-12}" y="{y+16}" text-anchor="end" class="mv">{esc(name)}</text>')
            o.append(f'<rect x="{LW_}" y="{y+4}" width="{BW*pct/mx:.1f}" height="16" fill="var(--c-move)"/>')
            o.append(f'<text x="{LW_+BW*pct/mx+6:.1f}" y="{y+16}" class="v">{pct:.0f}%</text>')
        else:
            o.append(f'<text x="{LW_-12}" y="{y+16}" text-anchor="end">{esc(name)}</text>')
            o.append(f'<rect x="{LW_}" y="{y+6}" width="{BW*pct/mx:.1f}" height="12" fill="var(--c-cat)"/>')
            o.append(f'<text x="{LW_+BW*pct/mx+6:.1f}" y="{y+16}" class="v">{pct:.1f}%</text>')
        o.append(f'<text x="{W-4}" y="{y+16}" text-anchor="end" class="v">{lp:.1f}%</text>'); y += rowh
    o.append("</svg>"); return "\n".join(o)

def svg_objections():
    W = 760; rowh = 28; H = rowh * len(obj) + 60; LW_ = 330; BW = W - LW_ - 70; mx = max(o_["n"] for o_ in obj)
    groups = list(dict.fromkeys(o_["group"] for o_ in obj)); gvar = {g: f"--g{i+1}" for i, g in enumerate(groups)}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="fig" role="img" aria-label="Objections ranked by post count">',
         '<style>.fig text{font-family:var(--font-ui);font-size:13px;fill:var(--ink-2)} .fig .v{fill:var(--ink);font-variant-numeric:tabular-nums}</style>']
    for i, o_ in enumerate(obj):
        y = 10 + i * rowh; w = BW * o_["n"] / mx
        o.append(f'<text x="{LW_-12}" y="{y+15}" text-anchor="end">{esc(o_["name"])}</text>')
        o.append(f'<rect x="{LW_}" y="{y+3}" width="{w:.1f}" height="16" fill="var({gvar[o_["group"]]})"/>')
        o.append(f'<text x="{LW_+w+6:.1f}" y="{y+15}" class="v">{o_["n"]:,}</text>')
    ly = H - 14; lx = LW_
    for g in groups:
        o.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" fill="var({gvar[g]})"/><text x="{lx+16}" y="{ly}">{esc(g)}</text>'); lx += 16 + 7.2 * len(g) + 22
    o.append("</svg>"); return "\n".join(o)

(OUT / "fig_stance.svg").write_text(svg_stance()); (OUT / "fig_moves.svg").write_text(svg_moves()); (OUT / "fig_objections.svg").write_text(svg_objections())
print(json.dumps({k: v for k, v in stats.items() if k in ("root_metrics", "fetched_at", "n_posts", "n_reply", "n_quote", "followers", "langs", "substance_share", "objections_total")}, indent=1))
for k, v in stance.items(): print(f'{k:50s} agree {v["pct"]["agree"]:5.1f} mixed {v["pct"]["mixed"]:5.1f} disagree {v["pct"]["disagree"]:5.1f} none {v["pct"]["not_addressed"]:5.1f}  n={v["n"]}  agree/(a+d)={v["agree_pct_of_ad"]}')
for m in stats["moves"]: print(m["move"], m["pct"], "likes", m["likes_pct"], [(c["name"], c["pct"], c["likes_pct"]) for c in m["cats"]])
