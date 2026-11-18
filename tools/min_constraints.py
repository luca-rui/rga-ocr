"""Print a pip constraints file that pins every dependency in
pyproject.toml, extras included, to its floor: `name>=X` becomes
`name==X`. The minimum-version CI leg installs with it, so a floor that
no longer works fails there instead of on a user's machine.

    python tools/min_constraints.py > constraints-min.txt
"""
import os
import re
import sys
import tomllib

REQ = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*>=\s*([0-9][0-9A-Za-z.]*)\s*(;.*)?$")


def constraints(pyproject):
    with open(pyproject, "rb") as f:
        project = tomllib.load(f)["project"]
    reqs = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        reqs += extra
    out = []
    for r in reqs:
        m = REQ.match(r)
        if not m:
            raise SystemExit(f"min_constraints: no '>=' floor in {r!r}")
        name, floor, marker = m.group(1), m.group(2), (m.group(3) or "").strip()
        out.append(f"{name}=={floor}" + (f" {marker}" if marker else ""))
    return sorted(set(out), key=str.lower)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, os.pardir, "pyproject.toml")
    print("\n".join(constraints(path)))
