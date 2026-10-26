#!/usr/bin/env python3
"""Read the current tranche from the CHIRPdb roadmap and write tiers/index.html.

The CHIRPdb repository keeps its roadmap as .claude/roadmaps.json, the source
its markdown roadmaps are rendered from. This script reads the live tranche
there and injects each milestone's tasks into the tiers page, between sentinel
comments, so the page states what the roadmap states and nothing is typed by
hand. Task notes are internal working notes and are never written out; only
ids, descriptions, statuses and milestone goals reach the page.

Usage:
  python3 scripts/gen_tiers.py                       # ../CHIRPdb beside this repo
  python3 scripts/gen_tiers.py /path/to/CHIRPdb      # any other checkout

Repo convention: plain hyphens, not em dashes. Standard library only.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tiers", "index.html")
DEFAULT_CHIRPDB = os.path.join(os.path.dirname(ROOT), "CHIRPdb")

BEGIN = "      // --- BEGIN gen_tiers ---"
END = "      // --- END gen_tiers ---"

# Milestone names carry their tier as a suffix; anything without one is core.
TIER_SUFFIX = re.compile(r"\s*\((Secondary|Tertiary)\)\s*$")


def main():
    chirpdb = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CHIRPDB
    source = os.path.join(chirpdb, ".claude", "roadmaps.json")
    try:
        roadmaps = json.load(open(source))
    except OSError as e:
        sys.exit("Cannot read %s: %s" % (source, e))

    live = [r for r in roadmaps if not r.get("archived")]
    if len(live) != 1:
        sys.exit("Expected one live tranche in %s, found %d"
                 % (source, len(live)))
    tranche = live[0]

    # The commit pins which state of the roadmap the page describes.
    commit = subprocess.run(
        ["git", "-C", chirpdb, "log", "-1", "--format=%h",
         "--", ".claude/roadmaps.json"],
        capture_output=True, text=True).stdout.strip() or None

    milestones = []
    for m in tranche["milestones"]:
        tier = TIER_SUFFIX.search(m["name"])
        milestones.append({
            "id": m["id"],
            "name": TIER_SUFFIX.sub("", m["name"]),
            "tier": tier.group(1).lower() if tier else "core",
            "goal": m.get("goal", ""),
            "tasks": [{"id": t["id"], "description": t["description"],
                       "status": t["status"]} for t in m["tasks"]],
        })

    data = {
        "tranche": tranche["name"],
        "commit": commit,
        "updated": datetime.now(timezone.utc).strftime("%-d %b %Y"),
        "milestones": milestones,
    }
    block = "\n".join([
        BEGIN,
        "      // Generated from CHIRPdb .claude/roadmaps.json by"
        " scripts/gen_tiers.py.",
        "      // Do not edit by hand - re-run the script instead.",
        "      const ROADMAP = " + json.dumps(data, ensure_ascii=False) + ";",
        END,
    ])

    html = open(OUT).read()
    start, stop = html.find(BEGIN), html.find(END)
    if start == -1 or stop == -1:
        sys.exit("Sentinel comments not found in %s" % OUT)
    with open(OUT, "w") as f:
        f.write(html[:start] + block + html[stop + len(END):])

    for tier in ("core", "secondary", "tertiary"):
        tasks = [t for m in milestones if m["tier"] == tier
                 for t in m["tasks"] if t["status"] != "out_of_scope"]
        done = sum(t["status"] == "done" for t in tasks)
        print("%-9s %d / %d done" % (tier, done, len(tasks)))
    print("updated " + OUT)


if __name__ == "__main__":
    main()
