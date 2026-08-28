#!/usr/bin/env python3
"""Pull tracked time from Solidtime and write progress/data.json.

The progress page is a static file served to the client, so the API token can
never reach the browser - Solidtime tokens are unscoped (POST /v1/users/me/
api-tokens takes only a name) and carry full read/write on the account. This
script runs locally or in CI, holds the token in the environment, and emits a
page's day figures directly into progress/index.html, between sentinel
comments. Only those figures are written - cost and rate fields from the API
are never serialised anywhere.

Injecting rather than emitting a JSON file the page fetches keeps the page
working over file:// and removes the runtime failure mode where the fetch
fails and the client sees an empty tracker.

Usage:
  export SOLIDTIME_TOKEN=...            # never commit this
  python3 scripts/gen_progress.py --list      # discover orgs/projects/tasks
  python3 scripts/gen_progress.py             # update progress/index.html

Repo convention: plain hyphens, not em dashes. Standard library only.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_URL = os.environ.get("SOLIDTIME_URL", "https://solidtime.zestdev.uk")
TOKEN = os.environ.get("SOLIDTIME_TOKEN", "")
OUT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "progress", "index.html")

BEGIN = "      // --- BEGIN gen_progress ---"
END = "      // --- END gen_progress ---"

# ---- config ----------------------------------------------------------------
# A billed day is 7.5 tracked hours. Every day figure on the page divides by
# this, so changing it moves the whole page.
HOURS_PER_DAY = 7.5

# Solidtime project holding the CHIRPdb work. Matched by name, case-insensitive.
# Set to None to count every project in the organisation.
PROJECT_NAME = "CHIRPdb"

# Which Solidtime tasks roll up into which phase on the progress page. Task
# names are matched case-insensitively. Run --list to see the real names, then
# fill these in. Only Phase 1 is wired up for now; the MVP's 19.5 days predate
# the instance and stay hardcoded in the page.
PHASES = [
    {
        "key": "p1",
        "label": "Phase 1",
        "alloc_days": 35,
        "tasks": ["CHIRPdb - Phase 1"],
    },
    {
        "key": "p2",
        "label": "Phase 2",
        "alloc_days": 23,
        "tasks": ["CHIRPdb - Phase 2"],
    },
    {
        "key": "p3",
        "label": "Phase 3",
        "alloc_days": 10,
        "tasks": ["CHIRPdb - Phase 3"],
    },
    {
        "key": "p5",
        "label": "Phase 5",
        "alloc_days": 15,
        "tasks": ["CHIRPdb - Phase 5"],
    },
]

# Counted time: everyone's entries, billable and non-billable alike.
BILLABLE_ONLY = False


def fmt_days(value):
    """Trim trailing zeros so 50.50 reads as 50.5 and 35.00 as 35."""
    return ("%.2f" % value).rstrip("0").rstrip(".")


# ---- api -------------------------------------------------------------------
def api(path, params=None):
    """GET an API path and return the decoded `data` payload."""
    if not TOKEN:
        sys.exit("SOLIDTIME_TOKEN is not set. Export it, do not commit it.")
    url = BASE_URL.rstrip("/") + "/api" + path
    if params:
        pairs = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    pairs.append((key + "[]", item))
            else:
                pairs.append((key, value))
        url += "?" + urllib.parse.urlencode(pairs)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
        "User-Agent": "chirp-progress-page",
    })
    try:
        with urllib.request.urlopen(req, timeout=30,
                                    context=ssl.create_default_context()) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        sys.exit("HTTP %d on %s\n%s" % (e.code, path, detail))
    except urllib.error.URLError as e:
        sys.exit("Could not reach %s: %s" % (BASE_URL, e.reason))
    return body.get("data", body)


def organization_id():
    memberships = api("/v1/users/me/memberships")
    if not memberships:
        sys.exit("This token has no organization memberships.")
    if len(memberships) > 1 and not os.environ.get("SOLIDTIME_ORG"):
        names = ", ".join("%s (%s)" % (m["organization"]["name"],
                                       m["organization"]["id"])
                          for m in memberships)
        sys.exit("Several organizations found, set SOLIDTIME_ORG: " + names)
    forced = os.environ.get("SOLIDTIME_ORG")
    if forced:
        return forced
    return memberships[0]["organization"]["id"]


def find_project(org, name):
    if name is None:
        return None
    projects = api("/v1/organizations/%s/projects" % org)
    for project in projects:
        if project["name"].strip().lower() == name.strip().lower():
            return project
    available = ", ".join(p["name"] for p in projects) or "none"
    sys.exit("No project named %r. Available: %s" % (name, available))


# ---- modes -----------------------------------------------------------------
def list_mode():
    """Print orgs, projects and tasks so PHASES can be filled in."""
    memberships = api("/v1/users/me/memberships")
    for m in memberships:
        print("org  %s  %s" % (m["organization"]["id"],
                               m["organization"]["name"]))
    org = organization_id()
    projects = {p["id"]: p["name"]
                for p in api("/v1/organizations/%s/projects" % org)}
    for pid, pname in projects.items():
        print("\nproject  %s  %s" % (pid, pname))
    tasks = api("/v1/organizations/%s/tasks" % org)
    print("\ntasks:")
    for t in tasks:
        print("  %-38s  %-40s  project=%s" % (
            t["id"], t["name"], projects.get(t.get("project_id"), "-")))


def build():
    org = organization_id()
    project = find_project(org, PROJECT_NAME)
    tasks = api("/v1/organizations/%s/tasks" % org)
    by_id = {t["id"]: t for t in tasks}

    # A task renamed or deleted in Solidtime would otherwise leave its phase
    # silently reading zero on a client-facing page. Fail loudly instead.
    known = {t["name"].strip().lower() for t in tasks
             if not project or t.get("project_id") == project["id"]}
    missing = [name for phase in PHASES for name in phase["tasks"]
               if name.strip().lower() not in known]
    if missing:
        sys.exit("Configured tasks not found in Solidtime: %s\nRun --list to "
                 "see the current names." % ", ".join(repr(m) for m in missing))

    params = {"group": "task"}
    if project:
        params["project_ids"] = [project["id"]]
    if BILLABLE_ONLY:
        params["billable"] = "true"
    result = api("/v1/organizations/%s/time-entries/aggregate" % org, params)

    # grouped_data keys are task IDs; a null key is time logged with no task
    seconds_by_task = {}
    for row in (result.get("grouped_data") or []):
        seconds_by_task[row.get("key")] = row.get("seconds", 0)

    phases = []
    matched = set()
    for phase in PHASES:
        wanted = [t.strip().lower() for t in phase["tasks"]]
        seconds = 0
        for task_id, task_seconds in seconds_by_task.items():
            task = by_id.get(task_id)
            if task and task["name"].strip().lower() in wanted:
                seconds += task_seconds
                matched.add(task_id)
        days = seconds / 3600.0 / HOURS_PER_DAY
        phases.append({
            "key": phase["key"],
            "label": phase["label"],
            "alloc_days": phase["alloc_days"],
            "elapsed_days": round(days, 2),
        })

    unmatched = sum(s for tid, s in seconds_by_task.items()
                    if tid not in matched and s)
    if unmatched:
        print("warning: %.2f days tracked outside the configured phases"
              % (unmatched / 3600.0 / HOURS_PER_DAY), file=sys.stderr)

    # Only these numbers are written out. Nothing from the API response is
    # passed through wholesale, so cost and rate fields cannot reach the page.
    now = datetime.now(timezone.utc)
    block = [BEGIN,
             "      // Generated from Solidtime by scripts/gen_progress.py.",
             "      // Do not edit by hand - re-run the script instead.",
             '      const LAST_UPDATED = "%s";' % now.strftime("%-d %b %Y")]
    for phase in phases:
        block.append("      const %s_ELAPSED = %s;" % (
            phase["key"].upper(), fmt_days(phase["elapsed_days"])))
    block.append(END)

    html = open(OUT).read()
    start = html.find(BEGIN)
    stop = html.find(END)
    if start == -1 or stop == -1:
        sys.exit("Sentinel comments not found in %s" % OUT)
    html = html[:start] + "\n".join(block) + html[stop + len(END):]
    with open(OUT, "w") as f:
        f.write(html)

    for phase in phases:
        over = phase["elapsed_days"] - phase["alloc_days"]
        note = "  (%.2f over)" % over if over > 0 else ""
        print("%s  %.2f / %s days%s" % (phase["label"], phase["elapsed_days"],
                                        phase["alloc_days"], note))
    print("updated " + OUT)


if __name__ == "__main__":
    if "--list" in sys.argv:
        list_mode()
    else:
        build()
