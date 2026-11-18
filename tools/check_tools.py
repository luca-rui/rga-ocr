#!/usr/bin/env python3
"""CI check: the installed tools extract text, not merely exist on PATH.

Builds the test fixtures and runs pdftotext, rga's poppler adapter and
rga's pandoc adapter on them. Run it from the same shell as the tests, so
both resolve the same binaries: under Git Bash on Windows, PATH puts the
pdftotext that Git ships ahead of poppler's.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NEEDLE = "Wartungsvertrag"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def main():
    failed = []
    for tool in ("rg", "rga", "rga-preproc", "pandoc", "pdftotext"):
        path = shutil.which(tool)
        print(f"{tool}: {path or 'NOT FOUND'}")
        if not path:
            failed.append(f"{tool} is not on PATH")
    if failed:
        print("\n".join(failed), file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="rga-ocr-tools-") as tmp:
        fx = os.path.join(tmp, "fx")
        cache = os.path.join(tmp, "cache")
        code, _, err = run([sys.executable, os.path.join(HERE, os.pardir, "tests", "make_fixtures.py"), fx])
        if code:
            print(err, file=sys.stderr)
            return 1
        pdf = os.path.join(fx, "textlayer.pdf")
        docx = os.path.join(fx, "vertrag.docx")
        checks = [
            ("pdftotext", ["pdftotext", pdf, "-"]),
            ("rga poppler adapter", ["rga", "--rga-cache-path=" + cache, "--rga-adapters=poppler", NEEDLE, pdf]),
            ("rga pandoc adapter", ["rga", "--rga-cache-path=" + cache, "--rga-adapters=pandoc", NEEDLE, docx]),
        ]
        for label, cmd in checks:
            code, out, err = run(cmd)
            ok = code == 0 and NEEDLE in out
            print(f"{label}: {'ok' if ok else 'FAILED'}")
            if not ok:
                failed.append(f"{label}: exit {code}, needle {'found' if NEEDLE in out else 'missing'}\n{err.strip()}")
    if failed:
        print("\n".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
