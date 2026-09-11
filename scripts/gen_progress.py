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
import re
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

# The funded ceiling for the whole engagement. The project's own
# estimated_time in Solidtime does not match the contract (it reads 162.5
# days), so this one figure is set here and emitted with the rest.
TOTAL_BUDGET_DAYS = 120

# Which Solidtime tasks roll up into which row on the progress page. Task names
# are matched case-insensitively - run --list to see the real names. Every
# tracked day in the project belongs to exactly one row: the page presents a
# single 120-day bucket, so time matching no row would go missing rather than
# merely uncounted. The unmatched warning below guards that and should stay
# silent.
#
# Allocations are not listed here. Solidtime carries them as each task's
# estimated_time, which is what its own percentages are measured against, so
# the page reads them from there and cannot drift out of step with the
# instance. A task with no estimate renders as tracked-only.
#
# A row added here needs matching markup in progress/index.html, keyed
# <KEY>_ELAPSED, <KEY>_ALLOC and <KEY>_DONE.
PHASES = [
    {
        "key": "dsg",
        "label": "DSG",
        "tasks": ["CHIRPdb - DSG"],
    },
    {
        "key": "mvp",
        "label": "MVP",
        "tasks": ["CHIRPdb - MVP"],
    },
    {
        "key": "p1",
        "label": "Phase 1",
        "tasks": ["CHIRPdb - Phase 1"],
    },
    {
        "key": "p15",
        "label": "Phase 1.5",
        "tasks": ["CHIRPdb - Phase 1.5"],
    },
    {
        "key": "p2",
        "label": "Phase 2",
        "tasks": ["CHIRPdb - Phase 2"],
    },
    {
        "key": "p3",
        "label": "Phase 3",
        "tasks": ["CHIRPdb - Phase 3"],
    },
    {
        "key": "p5",
        "label": "Phase 5",
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
    tasks = api("/v1/organizations/%s/tasks" % org, {"done": "all"})
    print("\ntasks:")
    for t in tasks:
        print("  %-38s  %-40s  project=%s" % (
            t["id"], t["name"], projects.get(t.get("project_id"), "-")))


def build():
    org = organization_id()
    project = find_project(org, PROJECT_NAME)
    # done=all matters: Solidtime hides completed tasks by default, so a phase
    # marked done in Solidtime would drop out of the lookup and fail the run.
    tasks = api("/v1/organizations/%s/tasks" % org, {"done": "all"})
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
        # Completion is Solidtime's to state, not the page's to infer: a phase
        # can sit over its allocation and still be running, or land under it
        # and be finished. Ticking the task done in Solidtime flips the page.
        phase_tasks = [t for t in tasks
                       if t["name"].strip().lower() in wanted
                       and (not project or t.get("project_id") == project["id"])]
        done = bool(phase_tasks) and all(t.get("is_done") for t in phase_tasks)
        # Solidtime measures its own percentages against estimated_time, so
        # reading the allocation from there keeps the page and the instance
        # telling the same story. No estimate means no allocation to show.
        estimates = [t["estimated_time"] for t in phase_tasks
                     if t.get("estimated_time")]
        alloc = (sum(estimates) / 3600.0 / HOURS_PER_DAY) if estimates else None
        days = seconds / 3600.0 / HOURS_PER_DAY
        phases.append({
            "key": phase["key"],
            "label": phase["label"],
            "alloc_days": alloc,
            "elapsed_days": round(days, 2),
            "done": done,
        })

    # Name the tasks, not just the total - an unattributed figure invites a
    # wrong guess about where the time went.
    unmatched = sorted(((tid, sec) for tid, sec in seconds_by_task.items()
                        if tid not in matched and sec),
                       key=lambda pair: -pair[1])
    if unmatched:
        total = sum(sec for _, sec in unmatched) / 3600.0 / HOURS_PER_DAY
        print("warning: %.2f days tracked outside the configured phases:"
              % total, file=sys.stderr)
        for tid, sec in unmatched:
            task = by_id.get(tid)
            label = task["name"] if task else (
                "(no task)" if tid is None else "unknown task %s" % tid)
            print("  %-28s %6.2f days" % (label, sec / 3600.0 / HOURS_PER_DAY),
                  file=sys.stderr)

    # Only these numbers are written out. Nothing from the API response is
    # passed through wholesale, so cost and rate fields cannot reach the page.
    now = datetime.now(timezone.utc)
    block = [BEGIN,
             "      // Generated from Solidtime by scripts/gen_progress.py.",
             "      // Do not edit by hand - re-run the script instead.",
             '      const LAST_UPDATED = "%s";' % now.strftime("%-d %b %Y")]
    block.append("      const TOTAL_BUDGET = %s;" % fmt_days(TOTAL_BUDGET_DAYS))
    for phase in phases:
        key = phase["key"].upper()
        block.append("      const %s_ELAPSED = %s;" % (
            key, fmt_days(phase["elapsed_days"])))
        block.append("      const %s_ALLOC = %s;" % (
            key, "null" if phase["alloc_days"] is None
            else fmt_days(phase["alloc_days"])))
        block.append("      const %s_DONE = %s;" % (
            key, "true" if phase["done"] else "false"))
    block.append(END)

    html = open(OUT).read()
    start = html.find(BEGIN)
    stop = html.find(END)
    if start == -1 or stop == -1:
        sys.exit("Sentinel comments not found in %s" % OUT)
    html = html[:start] + "\n".join(block) + html[stop + len(END):]

    # The budget also appears as fallback text in the body copy, which the page
    # overwrites on load. Rewrite it here too so view-source and the no-JS
    # render cannot show a figure the script has already moved on from.
    html = re.sub(r"(<span data-budget-days>)[^<]*(</span>)",
                  r"\g<1>%s\g<2>" % fmt_days(TOTAL_BUDGET_DAYS), html)
    with open(OUT, "w") as f:
        f.write(html)

    allocated = 0.0
    for phase in phases:
        note = "  [done]" if phase["done"] else ""
        if phase["alloc_days"] is None:
            print("%s  %.2f days tracked, no estimate in Solidtime%s"
                  % (phase["label"], phase["elapsed_days"], note))
            continue
        allocated += phase["alloc_days"]
        over = phase["elapsed_days"] - phase["alloc_days"]
        if over > 0:
            note = "  (%.2f over)" % over + note
        print("%s  %.2f / %s days%s" % (phase["label"], phase["elapsed_days"],
                                        fmt_days(phase["alloc_days"]), note))
    tracked = sum(p["elapsed_days"] for p in phases)
    print("tracked %s / %s days" % (fmt_days(tracked),
                                    fmt_days(TOTAL_BUDGET_DAYS)))
    if abs(allocated - TOTAL_BUDGET_DAYS) > 0.001:
        print("note: Solidtime estimates total %s days against a %s day budget"
              % (fmt_days(allocated), fmt_days(TOTAL_BUDGET_DAYS)))
    print("updated " + OUT)


if __name__ == "__main__":
    if "--list" in sys.argv:
        list_mode()
    else:
        build()
