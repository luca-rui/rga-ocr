#!/usr/bin/env python3
"""Fail when an installed distribution is not permissively licensed.

Reads the CSV that `pip-licenses --format=csv` prints on stdin, that is
the licence each distribution declares in its metadata. A licence string
is split as an expression: with `OR` one alternative has to pass, with
`AND`, `,` or `;` every part has to. A part passes when it is, as a whole,
one of the names in ALLOWED. GPL and AGPL are not on the list. LGPL is: it
reaches rga-ocr only as a library inside a wheel (libheif and libde265 in
pi-heif).
"""
import csv
import re
import sys

ALLOWED = re.compile(
    r"""
      MIT(\ License)? | MIT-CMU | MIT-0
    | BSD(\ License)? | BSD-[23]-Clause | 0BSD | [23]-Clause\ BSD\ License
    | Apache-2\.0 | Apache\ Software\ License | Apache\ License(,?\ Version)?\ 2\.0
    | LGPL-3\.0(-only|-or-later)?
    | GNU\ Lesser\ General\ Public\ License\ v3(\ or\ later)?\ \(LGPLv3\+?\)
    | MPL-2\.0 | Mozilla\ Public\ License\ 2\.0\ \(MPL\ 2\.0\)
    | PSF-2\.0 | Python\ Software\ Foundation\ License
    | ISC | ISC\ License(\ \(ISCL\))?
    | Zlib | CC0-1\.0 | HPND | Unlicense | The\ Unlicense(\ \(Unlicense\))?
    """,
    re.I | re.X,
)

# Whole licence strings that are not expressions, accepted after a look at
# the licence files the wheel ships.
REVIEWED = {
    # pypdfium2 5.15.2: its own code is BSD-3-Clause or Apache-2.0. The
    # licence files for the bundled PDFium build name the GPL in two places
    # only, both with an exception: ICU's autoconf helper scripts (Autoconf
    # exception) and libgcc/libstdc++ in the musl wheels (GCC Runtime
    # Library Exception). Look again when this string changes.
    "BSD-3-Clause, Apache-2.0, dependency licenses",
}


def part_ok(part):
    part = part.strip()
    return bool(ALLOWED.fullmatch(part) or (part[:1] == "(" and part[-1:] == ")" and ALLOWED.fullmatch(part[1:-1].strip())))


def problem(licence):
    licence = licence.strip()
    if licence in REVIEWED:
        return None
    for alternative in re.split(r"\s+OR\s+", licence):
        parts = [p for p in re.split(r"\s+AND\s+|[,;]", alternative) if p.strip()]
        if parts and all(part_ok(p) for p in parts):
            return None
    return "not on the allow-list"


def main():
    bad = []
    rows = list(csv.DictReader(sys.stdin))
    for row in rows:
        why = problem(row["License"])
        if why:
            bad.append(f'{row["Name"]} {row["Version"]}: {row["License"]!r} ({why})')
    for line in bad:
        print(line, file=sys.stderr)
    print(f"{len(rows)} distributions checked, {len(bad)} rejected")
    return 1 if bad or not rows else 0


if __name__ == "__main__":
    sys.exit(main())
