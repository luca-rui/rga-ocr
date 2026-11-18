"""CI helper: download a file and check its SHA-256.

    python tools/fetch_verified.py SHA256 OUT URL

A file already at OUT (from a cache) is checked the same way; one with the
wrong sum is deleted and fetched again. A download that fails or stops
short is tried again, three attempts in all. Exit 1, with OUT removed,
when the download cannot be completed or does not have the expected sum.
"""
import hashlib
import http.client
import os
import sys
import time
import urllib.error
import urllib.request

ATTEMPTS = 3
PAUSE = 5        # seconds before the second attempt, doubled before the third


class Incomplete(Exception):
    pass


def download(url, part):
    """Write the body to `part`. A connection that closes early gives a
    short read without an exception, so compare with Content-Length."""
    with urllib.request.urlopen(url, timeout=120) as r, open(part, "wb") as f:
        length = r.headers.get("Content-Length")
        written = 0
        for block in iter(lambda: r.read(1 << 20), b""):
            f.write(block)
            written += len(block)
    if length is not None and length.isdigit() and written != int(length):
        raise Incomplete(f"incomplete download ({written} of {length} bytes)")


def retryable(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    return True


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    want, out, url = argv[0].lower(), argv[1], argv[2]
    if os.path.exists(out):
        if sha256(out) == want:
            print(f"{out}: present, sha256 ok")
            return 0
        print(f"{out}: present with another sha256, fetching again")
        os.remove(out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    part = out + ".part"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            download(url, part)
            break
        except (Incomplete, OSError, http.client.HTTPException) as e:
            if os.path.exists(part):
                os.remove(part)
            last = attempt == ATTEMPTS or not retryable(e)
            sys.stderr.write(f"{url}\n  attempt {attempt}: {e}" + ("\n" if last else "; trying again\n"))
            if last:
                return 1
            time.sleep(PAUSE * 2 ** (attempt - 1))
    got = sha256(part)
    if got != want:
        os.remove(part)
        sys.stderr.write(f"{url}\n  sha256 {got}\n  wanted {want}\n")
        return 1
    os.replace(part, out)
    print(f"{out}: fetched, sha256 ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
