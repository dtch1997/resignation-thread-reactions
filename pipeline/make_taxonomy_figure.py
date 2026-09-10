#!/usr/bin/env python3
"""Two-ring donut of the response taxonomy: categories inside, response types outside,
colored by four super-groups. Writes figures/taxonomy_sunburst.svg (+ .png via cairosvg).
"""
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
FIG = Path(__file__).parent / "figures"

GROUPS = {  # super-group -> (label, hue color, category ids)
    "argue": ("Engages with substance", "#2F6DB5", ["risk_substance", "risk_denial", "race_logic", "policy_power", "exit_critique"]),
    "react": ("Expresses a reaction to the post", "#C2571A", ["existential_reaction", "cultural_framing"]),
    "author": ("Comments on the author", "#3B8F5E", ["endorse_amplify", "author_attacks"]),
    "noise": ("Other", "#8A93A1", ["meta_and_noise"]),
}
SHORT = {  # shorter category labels for the ring
    "risk_substance": "Substantive risk debate", "risk_denial": "Risk denial", "race_logic": "Race and geopolitics",
    "policy_power": "Policy and power", "exit_critique": "Critique of resigning", "existential_reaction": "Affective reaction",
    "cultural_framing": "Cultural framing", "endorse_amplify": "Endorsement", "author_attacks": "Attacks on the author",
    "meta_and_noise": "Meta and content-free",
}


def hexmix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def arc(cx, cy, r0, r1, a0, a1):
    """Annular sector path; angles in radians, clockwise from 12 o'clock."""
    def pt(r, a):
        return cx + r * math.sin(a), cy - r * math.cos(a)
    large = 1 if (a1 - a0) > math.pi else 0
    x0, y0 = pt(r1, a0); x1, y1 = pt(r1, a1); x2, y2 = pt(r0, a1); x3, y3 = pt(r0, a0)
    return (f"M{x0:.2f},{y0:.2f} A{r1},{r1} 0 {large} 1 {x1:.2f},{y1:.2f} "
            f"L{x2:.2f},{y2:.2f} A{r0},{r0} 0 {large} 0 {x3:.2f},{y3:.2f} Z")


def main() -> None:
    tax = json.loads((DATA / "taxonomy.json").read_text())
    rs = [json.loads(l) for l in (DATA / "taxonomy_results.jsonl").read_text().split("\n") if l.strip()]
    n = len(rs)
    sub_n = Counter(r["sub"] for r in rs)
    cat_n = Counter(r["cat"] for r in rs)
    cats = {c["id"]: c for c in tax["categories"]}

    W, H = 1760, 900
    cx, cy = 780, 470
    r_in, r_mid, r_out = 120, 225, 310
    gap = 0.004  # radians of surface gap between sectors
    paths, labels, legend, pending = [], [], [], []
    a = 0.0
    order = [(g, cid) for g, (_, _, ids) in GROUPS.items() for cid in sorted(ids, key=lambda c: -cat_n[c])]
    for g, cid in order:
        gname, hue, _ = GROUPS[g]
        frac = cat_n[cid] / n
        a1 = a + 2 * math.pi * frac
        paths.append(f'<path d="{arc(cx, cy, r_in, r_mid, a + gap, a1 - gap)}" fill="{hue}"><title>{cats[cid]["name"]}: {100*frac:.1f}%</title></path>')
        # category label inside ring if wide enough, else outside with a leader
        mid = (a + a1) / 2
        pct = f"{100*frac:.0f}%"
        if frac > 0.045:
            lx, ly = cx + (r_in + r_mid) / 2 * math.sin(mid), cy - (r_in + r_mid) / 2 * math.cos(mid)
            labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" class="in">{pct}</text>')
        # subcategory ring, shaded within hue by rank
        subs = sorted(cats[cid]["subcategories"], key=lambda s: -sub_n[s["id"]])
        b = a
        for j, s in enumerate(subs):
            sf = sub_n[s["id"]] / n
            if sf == 0:
                continue
            b1 = b + 2 * math.pi * sf
            shade = hexmix(hue, "#FFFFFF", 0.15 + 0.5 * j / max(1, len(subs) - 1))
            paths.append(f'<path d="{arc(cx, cy, r_mid + 4, r_out, b + gap, b1 - gap)}" fill="{shade}"><title>{s["name"]}: {100*sf:.1f}%</title></path>')
            if sf > 0.009:
                m = (b + b1) / 2
                pending.append((m, f"{s['name']}  {100*sf:.1f}%"))
            b = b1
        a = a1

    # leader-line labels: stack per side with a minimum vertical gap
    slot = 16
    for side in (1, -1):
        side_labels = sorted([(m, t) for m, t in pending if (math.sin(m) >= 0) == (side == 1)],
                             key=lambda x: cy - (r_out + 30) * math.cos(x[0]))
        ys = [cy - (r_out + 30) * math.cos(m) for m, _ in side_labels]
        # push apart from the top down, then pull back up if we overflowed the bottom
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + slot)
        overflow = ys[-1] - (H - 60) if ys else 0
        if overflow > 0:
            ys = [y - overflow for y in ys]
            for i in range(len(ys) - 2, -1, -1):
                ys[i] = min(ys[i], ys[i + 1] - slot)
        lx = cx + side * (r_out + 70)
        for (m, t), y in zip(side_labels, ys):
            x0, y0 = cx + (r_out + 3) * math.sin(m), cy - (r_out + 3) * math.cos(m)
            x1 = cx + side * (r_out + 40)
            labels.append(f'<polyline points="{x0:.1f},{y0:.1f} {x1:.1f},{y:.1f} {lx - side*6:.1f},{y:.1f}" fill="none" stroke="#B8BEC7" stroke-width="1"/>')
            labels.append(f'<text x="{lx:.1f}" y="{y+4:.1f}" text-anchor="{"start" if side == 1 else "end"}" class="out">{t}</text>')

    # legend: group -> categories with %
    ly = 40
    for g, (gname, hue, ids) in GROUPS.items():
        gpct = 100 * sum(cat_n[c] for c in ids) / n
        legend.append(f'<rect x="1470" y="{ly-11}" width="12" height="12" fill="{hue}"/><text x="1490" y="{ly}" class="lg-head">{gname}  {gpct:.0f}%</text>')
        ly += 20
        for cid in sorted(ids, key=lambda c: -cat_n[c]):
            legend.append(f'<text x="1490" y="{ly}" class="lg">{SHORT[cid]}  {100*cat_n[cid]/n:.0f}%</text>')
            ly += 18
        ly += 10

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Helvetica, Arial, sans-serif">
<style>
.in {{ font-size: 13px; fill: #fff; font-weight: 700; }}
.out {{ font-size: 12px; fill: #333; }}
.pct {{ fill: #777; }}
.lg-head {{ font-size: 13px; font-weight: 700; fill: #1A2130; }}
.lg {{ font-size: 12px; fill: #333; }}
.title {{ font-size: 18px; font-weight: 700; fill: #1A2130; }}
.sub {{ font-size: 12px; fill: #666; }}
.center {{ font-size: 26px; font-weight: 700; fill: #1A2130; }}
.center2 {{ font-size: 11px; fill: #666; }}
</style>
<rect width="{W}" height="{H}" fill="#FFFFFF"/>
<text x="30" y="34" class="title">What people said to the "I resigned from Anthropic" post</text>
<text x="30" y="56" class="sub">Share of {n:,} visible replies and quote tweets, spam excluded. Inner ring: ten categories. Outer ring: 48 response types.</text>
{"".join(paths)}
{"".join(labels)}
<text x="{cx}" y="{cy-4}" text-anchor="middle" class="center">{n:,}</text>
<text x="{cx}" y="{cy+14}" text-anchor="middle" class="center2">posts</text>
{"".join(legend)}
<text x="30" y="{H-16}" class="sub">Source: X API v2, 2026-09-09; labels by Claude Opus 5 with a bottom-up taxonomy. Hidden replies not included.</text>
</svg>'''
    FIG.mkdir(exist_ok=True)
    (FIG / "taxonomy_sunburst.svg").write_text(svg)
    try:
        subprocess.run(["cairosvg", str(FIG / "taxonomy_sunburst.svg"), "-o", str(FIG / "taxonomy_sunburst.png"), "-s", "2"], check=True)
        print("wrote svg + png")
    except Exception as e:  # noqa: BLE001
        print("wrote svg; png failed:", e)


if __name__ == "__main__":
    main()
