"""tools/release_check.py: the checks ci.yml and release.yml run around a
release. No network, no git: the parts that decide are plain functions."""
import importlib.util
import os

import pytest

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "release_check.py")
if not os.path.isfile(PATH):
    pytest.skip("tools/release_check.py is not in this tree", allow_module_level=True)
spec = importlib.util.spec_from_file_location("release_check", PATH)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

LOG = """# Changelog

## [Unreleased]

### Added

- something new

## [0.3.0] - 2026-12-01

### Fixed

- a fix
  over two lines

## [0.2.9] - 2026-11-20

### Added

- older

[Unreleased]: https://github.com/o/r/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/o/r/compare/v0.2.9...v0.3.0
[0.2.9]: https://github.com/o/r/releases/tag/v0.2.9
"""


def test_this_tree_is_consistent():
    """The repository itself: VERSION and CHANGELOG.md agree."""
    assert rc.consistency(rc.package_version(), rc.read("CHANGELOG.md")) == []
    assert rc.notes(rc.read("CHANGELOG.md"), rc.package_version())


def test_notes_are_the_section_without_heading_and_links():
    assert rc.notes(LOG, "0.3.0") == "### Fixed\n\n- a fix\n  over two lines"
    assert rc.notes(LOG, "0.2.9") == "### Added\n\n- older"         # the link definitions are not part of it
    assert rc.notes(LOG, "0.4.0") is None


def test_consistency_names_what_a_release_pull_request_forgot():
    assert rc.consistency("0.3.0", LOG) == []
    # VERSION raised, changelog not
    assert rc.consistency("0.3.1", LOG) == ["VERSION is 0.3.1, the newest release in CHANGELOG.md is 0.3.0"]
    # a pre-release version is for the TestPyPI dry run only
    assert "not a release version" in rc.consistency("0.3.0rc1", LOG)[0]
    no_date = LOG.replace("## [0.3.0] - 2026-12-01", "## [0.3.0]")
    assert rc.consistency("0.3.0", no_date) == ["the heading of 0.3.0 in CHANGELOG.md carries no date (YYYY-MM-DD)"]
    empty = LOG.replace("### Fixed\n\n- a fix\n  over two lines\n", "")
    assert rc.consistency("0.3.0", empty) == ["the section of 0.3.0 in CHANGELOG.md has no entry"]
    no_link = LOG.replace("[0.3.0]: https://github.com/o/r/compare/v0.2.9...v0.3.0\n", "")
    assert rc.consistency("0.3.0", no_link) == ["CHANGELOG.md has no link definition [0.3.0]: ...v0.3.0"]
    old_compare = LOG.replace("compare/v0.3.0...HEAD", "compare/v0.2.9...HEAD")
    assert rc.consistency("0.3.0", old_compare) == ["the [Unreleased] link in CHANGELOG.md does not compare from v0.3.0"]


def run(status, conclusion=None, started="2026-12-01T10:00:00Z", id=1):
    return {"id": id, "status": status, "conclusion": conclusion, "run_started_at": started,
            "html_url": f"https://github.com/o/r/actions/runs/{id}"}


def test_ci_verdict():
    assert rc.ci_verdict([])[0] == "wait"
    assert rc.ci_verdict([run("in_progress")])[0] == "wait"
    assert rc.ci_verdict([run("queued")])[0] == "wait"
    assert rc.ci_verdict([run("completed", "success")]) == ("ok", "ci succeeded: https://github.com/o/r/actions/runs/1")
    for bad in ("failure", "cancelled", "timed_out", "skipped", None):
        assert rc.ci_verdict([run("completed", bad)])[0] == "fail", bad
    # the newest run counts: a green re-run after a red attempt, and the other way round
    red = run("completed", "failure", started="2026-12-01T10:00:00Z", id=1)
    green = run("completed", "success", started="2026-12-01T11:00:00Z", id=2)
    assert rc.ci_verdict([red, green])[0] == "ok"
    assert rc.ci_verdict([run("completed", "success"), run("completed", "failure", started="2026-12-01T12:00:00Z", id=3)])[0] == "fail"


def test_wait_for_ci_waits_for_a_run_that_is_still_going():
    answers = [[], [run("in_progress")], [run("completed", "success")]]
    slept = []
    state, _ = rc.wait_for_ci("o/r", "abc", wait=600, runs=lambda repo, sha: answers.pop(0), sleep=slept.append)
    assert state == "ok" and slept == [30, 30]
    # ... and gives up after the time it was given
    slept = []
    state, reason = rc.wait_for_ci("o/r", "abc", wait=60, runs=lambda repo, sha: [run("in_progress")], sleep=slept.append)
    assert state == "wait" and slept == [30, 30] and "in_progress" in reason
    # a red run ends the wait at once
    state, _ = rc.wait_for_ci("o/r", "abc", wait=600, runs=lambda repo, sha: [run("completed", "failure")], sleep=slept.append)
    assert state == "fail"


def test_tag_check_refuses_a_tag_that_is_not_the_version(monkeypatch, capsys):
    monkeypatch.setattr(rc, "on_main", lambda sha: True)
    monkeypatch.setattr(rc, "ci_runs", lambda repo, sha: pytest.fail("no need to ask for CI"))
    assert rc.main(["tag", "v9.9.9", "--sha", "abc", "--repo", "o/r"]) == 1
    assert f"tag v9.9.9 does not match VERSION {rc.package_version()}" in capsys.readouterr().err


def test_tag_check_needs_the_commit_on_main_and_a_green_run(monkeypatch, capsys):
    tag = "v" + rc.package_version()
    monkeypatch.setattr(rc, "on_main", lambda sha: False)
    assert rc.main(["tag", tag, "--sha", "abc", "--repo", "o/r"]) == 1
    assert "which is not on main" in capsys.readouterr().err

    monkeypatch.setattr(rc, "on_main", lambda sha: True)
    monkeypatch.setattr(rc, "ci_runs", lambda repo, sha: [run("completed", "failure")])
    assert rc.main(["tag", tag, "--sha", "abc", "--repo", "o/r"]) == 1
    assert "no green ci run on abc" in capsys.readouterr().err

    monkeypatch.setattr(rc, "ci_runs", lambda repo, sha: [run("completed", "success")])
    assert rc.main(["tag", tag, "--sha", "abc", "--repo", "o/r"]) == 0
