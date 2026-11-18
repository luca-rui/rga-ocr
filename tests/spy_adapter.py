#!/usr/bin/env python3
"""The adapter behind a spy, for tests that need to know which files rga
handed to it: appends `MODE\\tPATH` to the file named by ADAPTER_SPY_LOG,
then runs rga_ocr.adapter as the program.

The CLI's own report file is no use for that: it lives in a per-run
directory that the CLI removes. The variable carries no RGA_ prefix on
purpose, the CLI warns about RGA_OCR_ names it does not know.
"""
import os
import runpy
import sys

log = os.environ.get("ADAPTER_SPY_LOG")
if log:
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, ("\t".join(sys.argv[1:3]) + "\n").encode("utf-8", "replace"))
    finally:
        os.close(fd)
runpy.run_module("rga_ocr.adapter", run_name="__main__", alter_sys=True)
