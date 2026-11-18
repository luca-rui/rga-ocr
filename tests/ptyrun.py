#!/usr/bin/env python3
"""Run a command with stdout and stderr on a pseudo-terminal and write what
it printed, raw, to OUTFILE. Exit status is the command's. Lets the tests
exercise terminal-only output (colors, status line) without a real tty.

usage: ptyrun.py OUTFILE COMMAND [ARG...]
"""
import os
import pty
import sys


def main():
    out, cmd = sys.argv[1], sys.argv[2:]
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.setdefault("COLUMNS", "120")
        os.execvp(cmd[0], cmd)
    chunks = []
    while True:
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    _, st = os.waitpid(pid, 0)
    with open(out, "wb") as f:
        f.write(b"".join(chunks))
    return os.waitstatus_to_exitcode(st)


if __name__ == "__main__":
    sys.exit(main())
