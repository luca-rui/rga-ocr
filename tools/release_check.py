#!/usr/bin/env python3
"""Checks around a release, shared by ci.yml and release.yml.

  release_check.py consistency
      Every pull request: VERSION in src/rga_ocr/__init__.py is the newest
      release CHANGELOG.md names, that section has entries and a date, and
      the link definitions at the foot name it. A release pull request that
      forgets one of them fails here, before a tag exists.

  release_check.py notes [VERSION]
      The changelog section of VERSION (default: the package version), as
      the text of the GitHub release.

  release_check.py tag TAG [--sha SHA] [--repo OWNER/NAME] [--wait SECONDS]
      A pushed tag: TAG is v + VERSION, the consistency checks hold, the
      commit is on main, and the ci workflow went green on that commit as
      a push to main. A run that is still going is waited for.

Exit 0 when everything holds, 1 with one line per problem otherwise.
Needs only the standard library; `tag` calls git and gh.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADING = re.compile(r"^## \[([^\]]+)\](?: - (\S+))?[ \t]*$", re.M)
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def package_version(text=None):
    text = read("src", "rga_ocr", "__init__.py") if text is None else text
    m = re.search(r'^VERSION = "([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("no VERSION in src/rga_ocr/__init__.py")
    return m.group(1)


def sections(changelog):
    """[(name, date or None, body)] in the order of the file."""
    marks = list(HEADING.finditer(changelog))
    foot = re.search(r"^\[[^\]]+\]: ", changelog, re.M)
    end = foot.start() if foot else len(changelog)
    out = []
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else end
        out.append((m.group(1), m.group(2), changelog[m.end():stop].strip()))
    return out


def notes(changelog, version):
    """The body of one release's section, or None."""
    for name, _date, body in sections(changelog):
        if name == version:
            return body
    return None


def consistency(version, changelog):
    """Problems that stand between this tree and a release of `version`."""
    problems = []
    releases = [s for s in sections(changelog) if s[0] != "Unreleased"]
    if not VERSION_RE.fullmatch(version):
        problems.append(f"VERSION {version} is not a release version (X.Y.Z)")
    if not releases:
        return problems + ["CHANGELOG.md names no release"]
    name, date, body = releases[0]
    if name != version:
        problems.append(f"VERSION is {version}, the newest release in CHANGELOG.md is {name}")
        return problems
    try:
        datetime.date.fromisoformat(date or "")
    except ValueError:
        problems.append(f"the heading of {version} in CHANGELOG.md carries no date (YYYY-MM-DD)")
    if not re.search(r"^- ", body, re.M):
        problems.append(f"the section of {version} in CHANGELOG.md has no entry")
    if not re.search(r"^\[%s\]: \S+v%s$" % (re.escape(version), re.escape(version)), changelog, re.M):
        problems.append(f"CHANGELOG.md has no link definition [{version}]: ...v{version}")
    if not re.search(r"^\[Unreleased\]: \S+/v%s\.\.\.HEAD$" % re.escape(version), changelog, re.M):
        problems.append(f"the [Unreleased] link in CHANGELOG.md does not compare from v{version}")
    return problems


def ci_verdict(runs):
    """("ok" | "wait" | "fail", reason) for the ci runs of one commit, as
    the Actions API lists them (workflow_runs). The newest run counts: a
    re-run takes the place of the attempt before it."""
    if not runs:
        return "wait", "no ci run for this commit as a push to main yet"
    run = max(runs, key=lambda r: (r.get("run_started_at") or r.get("created_at") or "", r.get("id", 0)))
    where = run.get("html_url", "")
    if run.get("status") != "completed":
        return "wait", f"ci is {run.get('status')}: {where}"
    if run.get("conclusion") == "success":
        return "ok", f"ci succeeded: {where}"
    return "fail", f"ci ended as {run.get('conclusion')}: {where}"


def ci_runs(repo, sha):
    p = subprocess.run(
        ["gh", "api", "-X", "GET", f"repos/{repo}/actions/workflows/ci.yml/runs",
         "-f", f"head_sha={sha}", "-f", "event=push", "-f", "branch=main"],
        capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise SystemExit("gh api failed: " + p.stderr.strip())
    return json.loads(p.stdout).get("workflow_runs", [])


def wait_for_ci(repo, sha, wait, runs=None, sleep=time.sleep, pause=30):
    """The verdict once it is ok or fail, or after `wait` seconds."""
    waited = 0
    while True:
        state, reason = ci_verdict((runs or ci_runs)(repo, sha))
        if state != "wait" or waited >= wait:
            return state, reason
        print(f"waiting: {reason}", flush=True)
        sleep(pause)
        waited += pause


def on_main(sha):
    subprocess.run(["git", "fetch", "--no-tags", "--quiet", "origin", "main"], cwd=ROOT, check=True)
    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=ROOT).returncode == 0


def check_tag(tag, sha, repo, wait):
    version = package_version()
    problems = []
    if tag != "v" + version:
        problems.append(f"tag {tag} does not match VERSION {version}")
    problems += consistency(version, read("CHANGELOG.md"))
    if not on_main(sha):
        problems.append(f"{tag} points at {sha}, which is not on main")
    elif not problems:                  # no waiting for CI when the tag is wrong anyway
        state, reason = wait_for_ci(repo, sha, wait)
        print(reason)
        if state != "ok":
            problems.append(f"no green ci run on {sha}: {reason}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("consistency")
    n = sub.add_parser("notes")
    n.add_argument("version", nargs="?")
    t = sub.add_parser("tag")
    t.add_argument("tag")
    t.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    t.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    t.add_argument("--wait", type=int, default=2400)
    a = ap.parse_args(argv)

    if a.cmd == "notes":
        version = a.version or package_version()
        body = notes(read("CHANGELOG.md"), version)
        if not body:
            print(f"CHANGELOG.md has no section for {version}", file=sys.stderr)
            return 1
        print(body)
        return 0
    if a.cmd == "consistency":
        problems = consistency(package_version(), read("CHANGELOG.md"))
    else:
        if not a.sha or not a.repo:
            ap.error("tag needs --sha and --repo (or GITHUB_SHA and GITHUB_REPOSITORY)")
        problems = check_tag(a.tag, a.sha, a.repo, a.wait)
    for p in problems:
        print(p, file=sys.stderr)
    if not problems:
        print("release checks passed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
