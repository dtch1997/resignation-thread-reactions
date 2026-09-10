#!/usr/bin/env python3
"""Ten category bars grouped by move, with the share printed. figures/taxonomy_bars.svg/.png"""
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT_ID = "2097476196791709843"
DATA = Path(__file__).parent / "data" / ROOT_ID
FIG = Path(__file__).parent / "figures"
GROUPS = [
    ("Expresses a reaction to the post", "#C2571A", ["existential_reaction", "cultural_framing"]),
    ("Comments on the author", "#3B8F5E", ["endorse_amplify", "author_attacks"]),
    ("Engages with substance", "#2F6DB5", ["risk_substance", "risk_denial", "race_logic", "policy_power", "exit_critique"]),
    ("Other", "#8A93A1", ["meta_and_noise"]),
]
SHORT = {
    "risk_substance": "Substantive risk debate", "risk_denial": "Risk denial or deflation", "race_logic": "Race logic and geopolitics",
    "policy_power": "Policy and power", "exit_critique": "Critique of resigning as a tactic", "existential_reaction": "Affective and existential reaction",
    "cultural_framing": "Cultural and historical framing", "endorse_amplify": "Endorsement and amplification", "author_attacks": "Attacks on the author's credibility",
    "meta_and_noise": "Emoji, off-topic, meta and bots",
}


def main() -> None:
    rs = [json.loads(l) for l in (DATA / "taxonomy_results.jsonl").read_text().split("\n") if l.strip()]
    n = len(rs)
    cat_n = Counter(r["cat"] for r in rs)
    W = 900
    left, right = 300, 70
    bar_h, gap, group_gap = 26, 8, 26
    y = 20
    rows = []
    max_pct = max(cat_n.values()) / n * 100
    scale = (W - left - right) / (max_pct * 1.05)
    for gname, color, cids in GROUPS:
        gpct = 100 * sum(cat_n[c] for c in cids) / n
        rows.append(f'<text x="{left}" y="{y+12}" class="group" fill="{color}">{gname}</text>'
                    f'<text x="{W-right+60}" y="{y+12}" text-anchor="end" class="group-pct">{gpct:.0f}%</text>')
        y += 22
        for cid in sorted(cids, key=lambda c: -cat_n[c]):
            pct = 100 * cat_n[cid] / n
            w = pct * scale
            rows.append(f'<text x="{left-12}" y="{y+bar_h/2+5}" text-anchor="end" class="label">{SHORT[cid]}</text>'
                        f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="3" fill="{color}"/>'
                        f'<text x="{left+w+8:.1f}" y="{y+bar_h/2+5}" class="val">{pct:.0f}%</text>')
            y += bar_h + gap
        y += group_gap - gap
    H = y + 10
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Helvetica, Arial, sans-serif">
<style>
.group {{ font-size: 15px; font-weight: 700; }}
.group-pct {{ font-size: 15px; font-weight: 700; fill: #555; }}
.label {{ font-size: 14px; fill: #222; }}
.val {{ font-size: 14px; fill: #444; font-weight: 700; }}
</style>
<rect width="{W}" height="{H}" fill="#FFFFFF"/>
{"".join(rows)}
</svg>'''
    FIG.mkdir(exist_ok=True)
    (FIG / "taxonomy_bars.svg").write_text(svg)
    subprocess.run(["cairosvg", str(FIG / "taxonomy_bars.svg"), "-o", str(FIG / "taxonomy_bars.png"), "-s", "2"], check=True)
    print(f"wrote taxonomy_bars.svg/.png ({W}x{H})")


if __name__ == "__main__":
    main()
