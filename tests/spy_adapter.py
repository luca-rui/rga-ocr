#!/usr/bin/env python3
"""The adapter behind a spy, for tests that need to know which files rga
handed to it: writes `MODE\\tPATH` to a file of its own in the directory
named by ADAPTER_SPY_LOG, then runs rga_ocr.adapter as the program.

One file per call, not one shared log: rga starts the adapters in
parallel, and an append from two processes is not atomic on Windows
(the C runtime seeks to the end, then writes), so lines got lost.

The CLI's own report file is no use for that: it lives in a per-run
directory that the CLI removes. The variable carries no RGA_ prefix on
purpose, the CLI warns about RGA_OCR_ names it does not know.
"""
import os
import runpy
import sys
import uuid

log = os.environ.get("ADAPTER_SPY_LOG")
if log:
    name = os.path.join(log, "%d-%s" % (os.getpid(), uuid.uuid4().hex))
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, ("\t".join(sys.argv[1:3]) + "\n").encode("utf-8", "replace"))
    finally:
        os.close(fd)
runpy.run_module("rga_ocr.adapter", run_name="__main__", alter_sys=True)
