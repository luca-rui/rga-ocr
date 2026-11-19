#!/usr/bin/env python3
"""rga-ocr: search file names and contents (PDF and image OCR included) beneath a path.

Two passes per query:
  names     walk the tree, match the last path segment of files and directories
  contents  one ripgrep-all run with the rga-ocr adapters (OCR for PDFs and images)

Settings come from built-in defaults, then the profile file
(~/.config/rga-ocr/config; %APPDATA%/rga-ocr/config on Windows), then
RGA_OCR_<KEY> environment variables, then command-line flags; the later
source wins.
"""

import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from rga_ocr import ENV_PREFIX, PROG, VERSION, engines, paths

DEFAULT_EXCLUDE = ".git, node_modules, .venv, __pycache__"
DEFAULTS = {
    "engine": "auto",
    "lang": "",
    "exclude": DEFAULT_EXCLUDE,
    "case": "insensitive",
    "name_blank": "nonletter",
    "name_blank_optional": "false",
    "snippet": "80",
    "cache_dir": paths.cache_dir(),
    "adapters_extra": "",
    "progress": "true",
}
NAME_BLANK_MODES = ("nonletter", "separators", "strict")
BASE_ADAPTERS = ["pandoc", "postprocpagebreaks", "zip", "decompress", "tar", "sqlite"]
OCR_ADAPTERS = ["ocrpdf", "ocrimg", "officexml"]
# --no-ocr: ocrpdf runs with RGA_OCR_NO_OCR=1 (text layer only), no image adapter
NO_OCR_ADAPTERS = ["ocrpdf", "officexml"]

# rg output-format options: the content pass reads rg's JSON events, and
# these flags replace or silence that stream, so they are refused up front
NO_JSON_OPTS = {"-c", "--count", "--count-matches", "-l", "--files-with-matches", "--generate",
                "--files-without-match", "--files", "-q", "--quiet", "--no-json"}
# rg formatting options that change nothing here: rg's JSON events carry no
# formatting, and the text output is rga-ocr's own. Accepted with a warning.
NO_EFFECT_OPTS = {"-o", "--only-matching", "--vimgrep", "--column", "--heading", "--no-heading",
                  "-N", "--no-line-number", "-p", "--pretty", "--trim", "-b", "--byte-offset",
                  "-H", "--with-filename", "-I", "--no-filename", "--null", "-0", "--colors",
                  "--context-separator", "--field-context-separator", "--field-match-separator",
                  "--path-separator", "--hyperlink-format", "-M", "--max-columns",
                  "--max-columns-preview"}
COLOR_MODES = ("auto", "always", "ansi", "never")
# flags of the setup command; before the word "setup" they make it a query
SETUP_FLAGS = ("--apply", "--remove", "--engine", "--lang", "--config")
# rga-ocr's own flags that take a value, as `--flag VALUE` or `--flag=VALUE`:
# the profile setting each one overrides (None: --config, not a setting)
VALUE_FLAGS = {"--snippet": "snippet", "--name-blank": "name_blank", "--engine": "engine",
               "--lang": "lang", "--exclude": "exclude", "--config": None}
# rg / rga options that take a separate value argument (for pass-through)
VALOPTS = set("""
-e -g -t -T -C -A -B -j -M -E -m -d -f --regexp --glob --iglob --type --type-not
--type-add --type-clear --context --after-context --before-context --threads
--max-columns --encoding --max-count --max-depth --maxdepth --max-filesize --file
--ignore-file --pre --pre-glob --replace --color --colors --sort --sortr
--path-separator --context-separator --field-context-separator
--field-match-separator --hostname-bin --hyperlink-format
--dfa-size-limit --regex-size-limit --rga-cache-path
--rga-config-file --rga-adapters --rga-cache-max-blob-len
--rga-cache-compression-level --rga-max-archive-recursion
""".split())

PREFIX_RE = re.compile(r"^(?:Page \d+: )?(?:[^\s:/]+\.[A-Za-z0-9]{1,8}: )*")

TEMPLATE = f"""\
# {PROG} profile.  key = value, one per line. '#' starts a comment at the
# start of a line or after a blank; inside a value it is kept (dir#1).
# Every key can also be set as {ENV_PREFIX}<KEY> in the environment, most as a
# flag. Precedence: built-in default < this file < environment < flag.

# OCR engine: auto | vision | winocr | rapidocr | tesseract (flag --engine).
# auto takes the first one that works here: vision on macOS, winocr on
# Windows, otherwise rapidocr, then tesseract. --engines lists them.
engine = auto

# OCR languages, BCP 47 tags separated by commas or blanks (de-DE,en-US).
# Empty: the
# engine's default; vision and winocr detect the language themselves.
lang =

# Directory names skipped in both passes. This list replaces the default.
# --no-exclude skips nothing.
exclude = .git, node_modules, .venv, __pycache__

# insensitive | sensitive   (flags -i / -s)
case = insensitive

# What a blank in the query may match in file and directory names:
#   nonletter    a run of non-letter characters: blank _ - . digits ...
#   separators   a run of blanks, _ or -
#   strict       blanks only
name_blank = nonletter

# true: the run may also be empty, so "Kessel anlage" finds "Kesselanlage"
name_blank_optional = false

# Characters shown on each side of a content match. 0 prints whole lines
# (flag --full). --json always carries whole lines.
snippet = 80

# Where OCR results are cached, one sub-directory per engine and language.
# The line below shows the default; remove the '#' to set another directory.
# cache_dir = {DEFAULTS['cache_dir']}

# Extra ripgrep-all adapters appended to the list, e.g. mail,ffmpeg
adapters_extra =

# true: show a live status line (elapsed time, hits, files read, current
# file) on stderr while the content pass runs, and a one-line summary after
# it. Only when stdout and stderr are a terminal and --json is not given.
# Flags --progress / --no-progress.
progress = true
"""

USAGE = f"""\
usage: {PROG} [options] QUERY [PATH ...]    PATH defaults to .
       {PROG} [--rga-config-file=F] setup [--apply] [--engine NAME] [--lang L] [--config PATH]
       {PROG} [--rga-config-file=F] setup --remove [--config PATH]

  -s / -i                case-sensitive / case-insensitive (default -i)
  -r                     QUERY is a regex (default literal)
  --snippet N            characters shown around a content match (default 80)
  --full                 whole lines, same as --snippet 0
  --name-blank MODE      nonletter | separators | strict (what a blank may match in names)
  --name-blank-optional  the run a blank matches may be empty
  --engine NAME          OCR engine: auto, vision, winocr, rapidocr, tesseract (default auto)
  --engines              list the engines, whether each works here, and what auto picks; exit
                         (exit code 1 when the configured engine, or with auto every
                         engine, does not work here)
  --lang L               OCR languages, e.g. de-DE,en-US or "de-DE en-US" (default: the engine decides)
  --no-ocr               PDF text layer only, images skipped
  --force-ocr            OCR every PDF page even if it has a text layer
  --mail                 also search .eml/.mbox
  --accurate             sniff mime types instead of trusting extensions
  --exclude LIST         directory names to skip (replaces the default list)
  --no-exclude           skip nothing
  --names-only / --no-names
  --json                 rg JSON events; name hits first as {{"type":"name","path":...}}
  --color WHEN           auto | always | never (default auto: colour on a terminal)
  --no-cache             do not read or write the OCR cache
  --progress / --no-progress   status line while searching and a summary after (default on)
  --init-config          write a commented profile to {{config path}} and exit
  --cache-info           list the caches (cache-id, entries, size, last added, folders) and exit
  --clear-cache CACHE-ID|DIR ...|all   delete the named caches, or every cache, and exit
  --dry-run              with --clear-cache: show what would be removed, delete nothing
  --config PATH          use this profile file (env {ENV_PREFIX}CONFIG)
  --version, -h, --help

Value flags take --flag VALUE or --flag=VALUE; write short flags one by one (-i -r).
Anything else is passed to rga/rg (-g, -t, -C, -U, -j, -e, --rga-config-file ...),
except rg's output-format flags (-l, -c, --files, -q ...), which are refused; rg's
formatting flags (-o, --heading, -M ...) are accepted and change nothing.
--rga-accurate and --rga-no-cache mean --accurate and --no-cache;
--rga-cache-path DIR takes the place of cache_dir for this run.
--rga-adapters=LIST replaces the adapters of this run, +LIST adds to them, -LIST removes.
--replace works together with --json only.

profile: {{config path}}   keys: {", ".join(DEFAULTS)}
exit status: 0 at least one hit, 1 no hit, 2 failure (also: no hit while the
OCR engine failed on a file)
"""


# ------------------------------------------------------------- settings

def warn(msg):
    sys.stderr.write(f"{PROG}: {msg}\n")


def config_path(explicit=None):
    if explicit:
        return os.path.expanduser(explicit)
    env = os.environ.get(ENV_PREFIX + "CONFIG")
    if env:
        return os.path.expanduser(env)
    return paths.profile_path()


# "#" opens a comment at the start of a line or after whitespace only, so a
# value such as "scans#2024" survives
COMMENT_RE = re.compile(r"(?:^|\s)#")


def load_profile(path):
    vals = {}
    if not os.path.isfile(path):
        return vals
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = COMMENT_RE.split(raw, maxsplit=1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                warn(f"{path}:{n}: expected key = value")
                continue
            k, v = line.split("=", 1)
            k = k.strip().lower().replace("-", "_")
            if k not in DEFAULTS:
                warn(f"{path}:{n}: unknown key {k!r} (known: {', '.join(DEFAULTS)})")
                continue
            vals[k] = v.strip()
    return vals


def settings_from(profile_path):
    s = dict(DEFAULTS)
    s.update(load_profile(profile_path))
    for k in DEFAULTS:
        v = os.environ.get(ENV_PREFIX + k.upper())
        if v is not None:
            s[k] = v
    s["engine"] = s["engine"].strip()
    return s


# {ENV_PREFIX}<NAME> variables that are not profile keys: the profile path
# and what the CLI hands to the adapter or the adapter reads on its own.
# tests/test_cli.py checks this list against the source.
INTERNAL_ENV = ("CONFIG", "FORCE_OCR", "NO_OCR", "REPORT",
                "MIN_TEXT_CHARS", "RENDER_DPI", "MAX_PIXELS", "PARAGRAPH_GAP",
                "MAX_FRAMES", "MAX_OFFICE_MB")


def unknown_env(environ=None):
    """Names in the environment that start with ENV_PREFIX and mean nothing."""
    known = {ENV_PREFIX + k.upper() for k in DEFAULTS} | {ENV_PREFIX + k for k in INTERNAL_ENV}
    environ = os.environ if environ is None else environ
    return sorted(k for k in environ if k.startswith(ENV_PREFIX) and k not in known)


def environment_hints():
    """One warning each for misspelt variables and for engine plugins whose
    name cannot be used. Printed by the CLI only; the adapter runs per file."""
    odd = unknown_env()
    if odd:
        warn(f"{', '.join(odd)} ignored: no such setting "
             f"(settings: {', '.join(ENV_PREFIX + k.upper() for k in DEFAULTS)})")
    bad = engines.rejected_plugins()
    if bad:
        warn(f"engine plugin {', '.join(repr(n) for n in bad)} ignored: "
             "an engine name may contain a-z, 0-9 and _ only")


def as_list(value):
    return [x.strip() for x in value.split(",") if x.strip()]


def as_bool(value, key):
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return False
    warn(f"{key}: expected true or false, got {value!r}; using false")
    return False


def cache_rows(base):
    """One table row per cache directory under base."""
    import sqlite3
    from datetime import datetime
    rows = []
    for name in cache_names(base):
        d = os.path.join(base, name)
        db = os.path.join(d, "cache.sqlite3")
        size = dir_size(d)
        engine, lang, force = engines.parse_cache_tag(name)
        entries, last, folders = "?", "?", ""
        try:
            recs = read_cache_rows(db)
            entries = str(len(recs))
            if recs:
                last = datetime.fromtimestamp(max(r[1] for r in recs) / 1000).strftime("%Y-%m-%d %H:%M")
                folders = cache_roots([r[0] for r in recs])
        except sqlite3.Error as e:
            folders = f"(unreadable: {e})"
        rows.append([cache_id(name), engine, lang or "-", "yes" if force else "no", entries,
                     f"{size / 1e6:.1f} MB", last, folders])
    return rows


def print_cache_table(base, rows):
    print(f"cache_dir: {base}")
    if not rows:
        print("(empty)")
        return
    print()
    print_table(["CACHE-ID", "ENGINE", "LANG", "FORCE", "ENTRIES", "SIZE", "LAST ADDED", "FOLDERS"], rows, right={4, 5})


def cache_info(cache_dir):
    base = os.path.abspath(os.path.expanduser(cache_dir))
    if not os.path.isdir(base):
        print(f"no cache at {base}")
        return 0
    print_cache_table(base, cache_rows(base))
    return 0


def read_cache_rows(db):
    """(file_path, created_unix_ms) rows. mode=ro sees an uncheckpointed -wal;
    immutable=1 does not, so it is only the fallback for unwritable locations."""
    import sqlite3
    q = "select file_path, created_unix_ms from preproc_cache"
    for uri in (f"file:{db}?mode=ro", f"file:{db}?immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True)
            try:
                return con.execute(q).fetchall()
            finally:
                con.close()
        except sqlite3.Error as e:
            err = e
    raise err


def cache_id(name):
    """Stable short handle for a cache directory: sha1 of its name."""
    import hashlib
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:7]


def cache_names(base):
    return sorted(n for n in os.listdir(base) if os.path.isfile(os.path.join(base, n, "cache.sqlite3")))


# ripgrep-all 0.10.10's cache schema (src/preproc_cache.rs: SCHEMA_VERSION,
# connect_pragmas); rga drops and recreates the table when user_version differs
RGA_CACHE_SCHEMA = """
pragma journal_mode = wal;
pragma user_version = 3;
pragma application_id = 924716026;
create table if not exists preproc_cache (
    config_hash text not null,
    adapter text not null,
    adapter_version integer not null,
    created_unix_ms integer not null default (unixepoch() * 1000),
    active_adapters text not null,
    file_path text not null,
    file_mtime_unix_ms integer not null,
    text_content_zstd blob not null
) strict;
create unique index if not exists preproc_cache_idx
    on preproc_cache (config_hash, adapter, adapter_version, file_path, active_adapters);
"""


def private_makedirs(d):
    """Create d and every missing directory above it for this user only
    (0700). The cache holds the text of the documents searched. A directory
    that exists keeps its mode: it may be shared on purpose. Windows takes
    no mode; a new directory there inherits the access list of its parent."""
    missing = []
    d = os.path.abspath(d)
    while not os.path.isdir(d):
        missing.append(d)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for p in reversed(missing):
        try:
            os.mkdir(p, 0o700)
        except FileExistsError:         # another search made it meanwhile
            pass


def prepare_cache(d):
    """Create rga's cache database in d if it does not exist, and return an
    open connection to it (None if this SQLite cannot run rga's statements
    or cannot open an existing database; rga then handles the file itself).

    Every rga-preproc process (one per file) opens cache.sqlite3 itself,
    without a busy timeout, creates the schema when the file is new and
    rebuilds the WAL index when it is the first to open the file. With
    many files starting at once, one of them can hit "The database file
    is locked" and its file goes unsearched. Writing the schema up front
    and keeping one connection open while rga runs leaves plain reads at
    start-up. The schema of an existing database is never changed: rga
    owns it (forget_failed deletes rows after the run, nothing else). The
    caller closes the connection after the run."""
    import sqlite3
    private_makedirs(d)
    db = os.path.join(d, "cache.sqlite3")
    fresh = not os.path.exists(db)
    try:
        con = sqlite3.connect(db)
        try:
            if fresh:
                con.executescript(RGA_CACHE_SCHEMA)
            con.execute("pragma user_version").fetchone()   # attach to the WAL index
            return con
        except sqlite3.Error:
            con.close()
            raise
    except sqlite3.Error:
        if fresh:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(db + suffix)
                except OSError:
                    pass
        return None


def dir_size(path):
    size = 0
    for d, _dirs, files in os.walk(path):
        for f in files:
            try:
                size += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return size


def print_table(header, rows, right=()):
    """Aligned columns, two spaces apart; the last column is not padded."""
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    for r in [header] + rows:
        cells = []
        for i, cell in enumerate(r):
            cell = str(cell)
            if i == len(header) - 1:
                cells.append(cell)
            elif i in right:
                cells.append(cell.rjust(widths[i]))
            else:
                cells.append(cell.ljust(widths[i]))
        print("  ".join(cells).rstrip())


VIRTUAL_MARKERS = ("/./",) if os.sep == "/" else ("/./", os.sep + "." + os.sep)


def root_of_virtual(path):
    """The search root in an rga virtual path (root + '/./' + relative), or
    the parent directory when the marker is absent."""
    for m in VIRTUAL_MARKERS:
        if m in path:
            return path.split(m)[0]
    return os.path.dirname(path)


def cache_roots(paths):
    """The folders the cached files live in: the common parent and, when it
    has several children with entries, the three busiest of them."""
    # rga stores the search root as given (canonical for a relative one,
    # verbatim for an absolute one), so resolve symlinks before comparing
    resolved = {}
    dirs = []
    for p in paths:
        d = root_of_virtual(p)
        if d not in resolved:
            resolved[d] = os.path.realpath(d)
        dirs.append(resolved[d])
    try:
        common = os.path.commonpath(dirs)
    except ValueError:
        return ""
    counts = {}
    for d in dirs:
        rest = os.path.relpath(d, common)
        child = rest.split(os.sep)[0] if rest != "." else ""
        counts[child] = counts.get(child, 0) + 1
    if len(counts) <= 1:
        return common
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    parts = [f"{c or '.'} ({n})" for c, n in top]
    more = len(counts) - len(top)
    return os.path.join(common, "{" + ", ".join(parts) + (f", +{more} more" if more > 0 else "") + "}")


def clear_cache(cache_dir, targets=(), dry_run=False):
    """Delete the named caches (by cache-id or directory name), or every
    cache when the target is `all`. No target lists the caches and exits 2.
    dry_run prints what would go and deletes nothing."""
    base = os.path.abspath(os.path.expanduser(cache_dir))
    if os.path.dirname(base) == base or base == os.path.abspath(os.path.expanduser("~")):
        warn(f"refusing to delete {base}")
        return 2
    if not os.path.isdir(base):
        print(f"no cache at {base}")
        return 0
    verb = "would remove" if dry_run else "removed"
    if not targets:
        print_cache_table(base, cache_rows(base))
        print()
        sys.stdout.flush()
        warn("nothing removed; give cache-ids, directory names, or 'all'")
        return 2
    if "all" in targets:
        # only the cache directories go; anything else under cache_dir stays,
        # and cache_dir itself is removed only when nothing is left in it
        names = cache_names(base)
        print_cache_table(base, cache_rows(base))
        print()
        size = 0
        for name in names:
            d = os.path.join(base, name)
            size += dir_size(d)
            if not dry_run:
                shutil.rmtree(d)
        others = sorted(n for n in os.listdir(base) if n not in names)
        if others:
            print(f"{verb} {len(names)} cache(s) under {base} ({size / 1e6:.1f} MB); "
                  f"left alone: {', '.join(others[:5])}" + (", ..." if len(others) > 5 else ""))
        else:
            if not dry_run:
                os.rmdir(base)
            print(f"{verb} {base} ({size / 1e6:.1f} MB)")
        return 0
    names = cache_names(base)
    by_id = {cache_id(n): n for n in names}
    chosen, status = [], 0
    for t in targets:
        name = by_id.get(t) or (t if t in names else None)
        if name is None:
            warn(f"no cache with cache-id or directory {t!r}; see --cache-info")
            status = 2
        elif name not in chosen:
            chosen.append(name)
    for name in chosen:
        d = os.path.join(base, name)
        size = dir_size(d)
        if not dry_run:
            shutil.rmtree(d)
        print(f"{verb} {name} ({size / 1e6:.1f} MB)")
    return status


def print_engines(st):
    """One row per engine: name, usable here, note (reason or 'auto').
    Returns 1 when the configured engine, or for auto every engine, is unusable."""
    rows = [list(r) for r in engines.table(engines.parse_langs(st["lang"]))]
    print_table(["ENGINE", "AVAILABLE", "NOTE"], rows)
    chosen = st["engine"].strip() or "auto"       # --engine " x " comes in unstripped
    if chosen == "auto":
        ok = any(r[2] == "auto" for r in rows)
        if not ok:
            print("\nconfigured: auto (no engine available)")
    else:
        ok = any(r[0] == chosen and r[1] == "yes" for r in rows)
        print(f"\nconfigured: {chosen} ({'available' if ok else 'NOT available'})")
    return 0 if ok else 1


def init_config(path):
    if os.path.exists(path):
        print(f"profile exists, left untouched: {path}")
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)
    print(f"wrote {path}")
    return 0


# ------------------------------------------------------------ arguments

def check_cluster(a):
    """Refuses a bundle of short options (-il, -rX) that would hand rg a flag
    rga-ocr keeps away from it. Letters after a value-taking one are its value."""
    for ch in a[1:]:
        flag = "-" + ch
        if flag in VALOPTS:
            return
        if flag in NO_JSON_OPTS:
            warn(f"{flag} (in {a}) is not supported: the content pass reads rg's JSON output, which {flag} replaces")
            raise SystemExit(2)
        if ch == "r":
            warn(f"{a}: write -r on its own for a regex query; rg's replacement is --replace TEXT with --json")
            raise SystemExit(2)


def parse_args(argv):
    o = {
        "flags": {}, "pass": [], "regex": False, "ocr": True, "force": False, "mail": False,
        "accurate": False, "no_exclude": False, "names": True, "contents": True, "json": False,
        "no_cache": False, "init": False, "clear_cache": False, "cache_info": False, "engines": False,
        "dry_run": False, "config": None, "query": None, "root": ".", "roots": ["."], "replace": False,
        "color": "auto", "adapters": None,
    }
    args = list(argv)
    pos = []

    def take(flag):
        if not args:
            warn(f"{flag} needs a value")
            raise SystemExit(2)
        return args.pop(0)

    while args:
        a = args.pop(0)
        if a == "--":
            pos.extend(args)
            break
        if a in ("-h", "--help"):
            print(USAGE.replace("{config path}", config_path(o["config"])), end="")
            raise SystemExit(0)
        if a == "--version":
            print(f"{PROG} {VERSION}")
            raise SystemExit(0)
        # the name of a long option, without an attached =VALUE
        name, eq, val = a.partition("=") if a.startswith("--") else (a, "", "")
        if name in VALUE_FLAGS:
            val = val if eq else take(name)
            if VALUE_FLAGS[name] is None:
                o["config"] = val
            else:
                o["flags"][VALUE_FLAGS[name]] = val
        elif a == "-s":
            o["flags"]["case"] = "sensitive"
        elif a == "-i":
            o["flags"]["case"] = "insensitive"
        elif a == "-r":
            o["regex"] = True
        elif a == "--full":
            o["flags"]["snippet"] = "0"
        elif a == "--name-blank-optional":
            o["flags"]["name_blank_optional"] = "true"
        elif a == "--engines":
            o["engines"] = True
        elif a == "--no-exclude":
            o["no_exclude"] = True
        elif a == "--no-ocr":
            o["ocr"] = False
        elif a == "--force-ocr":
            o["force"] = True
        elif a == "--mail":
            o["mail"] = True
        elif a in ("--accurate", "--rga-accurate"):
            o["accurate"] = True
        elif a == "--names-only":
            o["contents"] = False
        elif a == "--no-names":
            o["names"] = False
        elif a == "--json":
            o["json"] = True
        elif a in ("--no-cache", "--rga-no-cache"):
            # rga's own flag makes every custom adapter fail (rga 0.10.10)
            o["no_cache"] = True
        elif name == "--rga-cache-path":
            # the search sets this flag itself, and rga takes it only once:
            # the directory stands in for cache_dir, with a directory per
            # engine and language below it as usual
            o["flags"]["cache_dir"] = val if eq else take(name)
        elif name == "--rga-adapters":
            # set by the search as well: the caller's list is worked into it
            o["adapters"] = val if eq else take(name)
        elif name == "--color":
            o["color"] = val if eq else take(name)
            if o["color"] not in COLOR_MODES:
                warn(f"--color: expected auto, always or never, got {o['color']!r}")
                raise SystemExit(2)
        elif a == "--progress":
            o["flags"]["progress"] = "true"
        elif a == "--no-progress":
            o["flags"]["progress"] = "false"
        elif a == "--init-config":
            o["init"] = True
        elif a == "--clear-cache":
            o["clear_cache"] = True
        elif a == "--cache-info":
            o["cache_info"] = True
        elif a == "--dry-run":
            o["dry_run"] = True
        elif a.startswith("-") and len(a) > 1:
            if name in NO_JSON_OPTS:
                warn(f"{name} is not supported: the content pass reads rg's JSON output, which {name} replaces")
                raise SystemExit(2)
            if name == "--replace":
                o["replace"] = True
            if name in NO_EFFECT_OPTS:
                warn(f"{name} has no effect: the output format is rga-ocr's own (see --json, --snippet, --full)")
            if not a.startswith("--") and len(a) > 2:
                check_cluster(a)
            if a.startswith("--rga-") and a in VALOPTS and args:
                # rga itself takes these values only after "="
                o["pass"].append(a + "=" + args.pop(0))
                continue
            o["pass"].append(a)
            if a in VALOPTS and args:
                o["pass"].append(args.pop(0))
        else:
            pos.append(a)
    if o["init"] or o["clear_cache"] or o["cache_info"] or o["engines"]:
        o["targets"] = pos
        return o
    if not pos:
        sys.stderr.write(USAGE.replace("{config path}", config_path(o["config"])))
        raise SystemExit(2)
    if o["replace"] and not o["json"]:
        # rg --json reports the replacement next to the unchanged line, and
        # the text output prints the line
        warn("--replace needs --json: the text output shows the matched lines as they are")
        raise SystemExit(2)
    o["query"] = pos[0]
    if len(pos) > 1:
        o["roots"] = pos[1:]
        o["root"] = pos[1]
    return o


# ------------------------------------------------------------ name pass

def name_pattern(query, regex, mode, optional, insensitive):
    if regex:
        pat = query
    else:
        parts = [p for p in re.split(r"\s+", query.strip()) if p]
        quant = "*" if optional else "+"
        sep = {"nonletter": r"[\W\d_]", "separators": r"[ _\-]", "strict": r" "}[mode] + quant
        pat = sep.join(re.escape(p) for p in parts)
    try:
        return re.compile(pat, re.IGNORECASE if insensitive else 0)
    except re.error as e:
        # rg reads more regex syntax than Python (\p{Lu}, say): the pattern
        # may be fine for the contents
        warn(f"file names are not searched: Python cannot read this regex ({e})")
        return None


def walk_names(root, exclude, pattern):
    if os.path.isfile(root):
        if pattern.search(os.path.basename(root)):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)
        for n in dirnames + sorted(filenames):
            if pattern.search(n):
                yield os.path.join(dirpath, n)


def name_event(path):
    """The --json line of a name hit. A name that is not valid UTF-8 (Linux)
    is given with U+FFFD in "path" and exactly in "path_bytes" (base64), so
    the line is valid JSON in any case."""
    ev = {"type": "name", "path": path}
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        raw = os.fsencode(path)
        ev["path"] = raw.decode("utf-8", "replace")
        ev["path_bytes"] = base64.b64encode(raw).decode("ascii")
    return json.dumps(ev, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------- content pass

def rg_text(obj):
    """rg JSON strings are {"text": ...} or {"bytes": base64}."""
    if obj is None:
        return ""
    if "text" in obj:
        return obj["text"]
    return base64.b64decode(obj.get("bytes", "")).decode("utf-8", "replace")


def byte_to_char(line_bytes, off):
    return len(line_bytes[:off].decode("utf-8", "replace"))


def render_match(line, submatches, width):
    """Snippet of `line` around the first submatch; returns (text, [(start, end)] highlights)."""
    line = line.rstrip("\r\n")
    b = line.encode("utf-8", "surrogateescape")
    spans = []
    for sm in submatches:
        s, e = sm.get("start", 0), sm.get("end", 0)
        if 0 <= s <= e <= len(b):
            spans.append((byte_to_char(b, s), byte_to_char(b, e)))
    if not spans:
        return line, []
    n = len(line)
    if width <= 0:
        return line, spans
    cs, ce = spans[0]
    ws, we = max(0, cs - width), min(n, ce + width)
    m = PREFIX_RE.match(line)
    plen = m.end() if m else 0
    if ws <= plen:
        ws, lead = 0, ""
    else:
        lead = line[:plen] + "…"
    tail = "…" if we < n else ""
    out = lead + line[ws:we] + tail
    shift = len(lead) - ws
    hl = [(s + shift, e + shift) for s, e in spans if s >= ws and e <= we]
    return out, hl


class Report:
    """Tails the adapter report file (<ENV_PREFIX>REPORT): lines of the form
    EVENT\\tMODE\\tPATH\\tDETAIL, EVENT one of start, done, error."""

    def __init__(self, path):
        self.path = path
        self.pos = 0
        self.rest = b""

    def events(self):
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read()
        except OSError:
            return []
        self.pos += len(data)
        data = self.rest + data
        lines = data.split(b"\n")
        self.rest = lines.pop()
        out = []
        for raw in lines:
            parts = raw.rstrip(b"\r").decode("utf-8", "replace").split("\t", 3)
            if len(parts) == 4:
                out.append(parts)
        return out


def as_roots(root):
    """The search roots as a list: one PATH or several."""
    return [root] if isinstance(root, (str, bytes)) else list(root)


def display_path(path, root):
    """rga reports absolute virtual paths with a '/./' from the search root;
    show them the way the hits are shown, relative to the root. rga echoes
    the root as given (or canonical, for a relative one), so compare the
    normalised path against both spellings of the root. With several roots
    the relative path alone would not say where the file is: the root goes
    in front the way it was given."""
    roots = as_roots(root)
    if os.path.isabs(path):
        path = os.path.normpath(path)
    # the longest root first: of dir and dir/sub the nearer one names the file
    for given in sorted(roots, key=lambda r: -len(os.path.abspath(r))):
        for base in (os.path.abspath(given), os.path.realpath(given)):
            prefix = base.rstrip(os.sep) + os.sep
            if path.startswith(prefix):
                path = path[len(prefix):]
                while path[:2] in ("./", "." + os.sep):
                    path = path[2:]
                return path if len(roots) == 1 else os.path.join(given, path)
    while path[:2] in ("./", "." + os.sep):
        path = path[2:]
    return path


def enable_vt(stream):
    """Let the Windows console interpret the escape sequences the status line
    uses (\\r, erase to end of line). A no-op elsewhere and on failure."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import msvcrt
        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:  # noqa: BLE001 - cosmetic; never fail the search over it
        pass


class Status:
    """Live status line on stderr while rga runs: spinner, elapsed time, hit
    count, files the adapters have finished, the file they are on now."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    ASCII_FRAMES = "|/-\\"

    def __init__(self, report, root, verb="read"):
        self.report = report
        self.root = root
        self.verb = verb            # what the adapters did to a finished file
        self.utf8 = (getattr(sys.stderr, "encoding", "") or "").lower().replace("-", "") == "utf8"
        self.frames = self.FRAMES if self.utf8 else self.ASCII_FRAMES
        enable_vt(sys.stderr)
        self.lock = threading.Lock()
        self.hits = 0
        self.done = 0
        self.current = ""
        self.t0 = time.monotonic()
        self.frame = 0
        self.shown = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=1)
        with self.lock:
            self._poll()
            self._clear()
            t = time.monotonic() - self.t0
            sep = " · " if self.utf8 else " - "
            sys.stderr.write(f"searched {t:.1f} s" + sep + sep.join(self._counts()) + "\n")
            sys.stderr.flush()

    def _poll(self):
        for ev, _mode, path, _detail in self.report.events():
            if ev == "start":
                self.current = display_path(path, self.root)
            elif ev == "done":
                self.done += 1

    def hit(self):
        with self.lock:
            self.hits += 1

    def clear(self):
        with self.lock:
            self._clear()

    def _clear(self):
        if self.shown:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()
            self.shown = False

    def _counts(self):
        return [f"{self.hits} hit" + ("" if self.hits == 1 else "s"),
                f"{self.done} file" + ("" if self.done == 1 else "s") + " " + self.verb]

    def _draw(self):
        cols = shutil.get_terminal_size((80, 24)).columns
        t = time.monotonic() - self.t0
        parts = [f"searching {t:.0f} s"] + self._counts()
        sep = " · " if self.utf8 else " - "
        line = f"{self.frames[self.frame % len(self.frames)]} " + sep.join(parts)
        if self.current:
            line += sep + self.current
        if len(line) > cols - 1:
            line = line[:max(0, cols - 2)] + ("…" if self.utf8 else "~")
        sys.stderr.write("\r\x1b[K" + line)
        sys.stderr.flush()
        self.shown = True
        self.frame += 1

    def _loop(self):
        while not self.stop.wait(0.1):
            with self.lock:
                self._poll()
                self._draw()


class Printer:
    def __init__(self, tty, color="auto"):
        self.tty = tty
        self.color = {"always": True, "ansi": True, "never": False}.get(
            color, tty and not os.environ.get("NO_COLOR"))
        self.current = None
        self.status = None

    def _begin(self):
        if self.status:
            self.status.clear()

    def c(self, code, s):
        return f"\x1b[{code}m{s}\x1b[0m" if self.color else s

    def heading(self, text):
        if self.tty:
            print(self.c("1;35", text))

    def name(self, path):
        self._begin()
        print(path)

    def _highlight(self, text, spans):
        if not self.color or not spans:
            return text
        out, last = [], 0
        for s, e in spans:
            out.append(text[last:s])
            out.append(self.c("1;31", text[s:e]))
            last = e
        out.append(text[last:])
        return "".join(out)

    def match(self, path, lineno, text, spans, sep=":"):
        ln = "" if lineno is None else f"{lineno}{sep}"
        body = self._highlight(text, spans)
        self._begin()
        if self.tty:
            if path != self.current:
                if self.current is not None:
                    print()
                print(self.c("35", path))
                self.current = path
            print(f"{self.c('32', ln)}{body}")
        else:
            print(f"{path}{sep}{ln}{body}")
        if self.status:
            sys.stdout.flush()


def adapter_list(o, st):
    """The rga adapters for this run: the PDF and office adapters, plus the
    image adapter unless --no-ocr, the base set,
    `mail` with --mail, and whatever `adapters_extra` names (ffmpeg is never
    added on its own; it costs a process per media file)."""
    adapters = list(OCR_ADAPTERS if o["ocr"] else NO_OCR_ADAPTERS) + BASE_ADAPTERS
    if o["mail"]:
        adapters.append("mail")
    for a in as_list(st["adapters_extra"]):
        if a not in adapters:
            adapters.append(a)
    spec = (o.get("adapters") or "").strip()
    named = [n for n in spec.lstrip("+-").split(",") if n.strip()]
    if spec.startswith("-"):
        adapters = [a for a in adapters if a not in named]
    elif spec.startswith("+"):
        adapters += [n for n in named if n not in adapters]
    elif named:
        adapters = named
    return adapters


def run_config(passed, run_dir):
    """Path of an rga config written for this run, or None when rga's own
    config will do.

    rga finds the adapters through its config file, which `setup --apply`
    writes. So that a search works without that step, and keeps working
    after the installation moved or an upgrade changed an adapter, the run
    gets its own config whenever rga's does not hold the three entries this
    installation would write: a copy of rga's config with the entries put
    in. rga's own file is never written here. None as well when the caller
    passed --rga-config-file, or when rga's config cannot be read here; the
    search then depends on what that file holds, so say why."""
    if rga_config_flag(passed) is not None:
        return None
    from rga_ocr import setup_cmd
    existing = {}
    try:
        with open(paths.rga_config_path(), encoding="utf-8") as f:
            existing = setup_cmd.load_jsonc(f.read())
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        return _config_unread(e)
    problem = setup_cmd.shape_problem(existing)
    if problem:
        return _config_unread(problem)
    entries = setup_cmd.adapter_entries()
    names = {e["name"] for e in entries}
    custom = existing.get("custom_adapters") or []
    if [a for a in custom if a.get("name") in names] == entries:
        return None
    path = os.path.join(run_dir, "rga-config.jsonc")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(setup_cmd.merge_config(existing, entries), f, ensure_ascii=False)
    return path


def _config_unread(why):
    warn(f"cannot read {paths.rga_config_path()} ({why}); searching with it as it is, "
         f"without this installation's adapter entries")
    return None


ARCHIVE_ADAPTERS = ("zip", "tar", "decompress")       # rga's own; a row holds all members


def forget_failed(con, failed, root):
    """Remove the cache rows of files the OCR engine failed on.

    The adapter must exit 0 even when it fails (rg aborts the whole search
    otherwise), so rga stores the empty output as that file's text and never
    asks again: one failed model download or one run without the language
    data would hide the file from every later search. Only engine failures
    are forgotten; a file that cannot be opened stays cached as empty until
    it changes, like any other file.

    rga keys a row on the absolute path of the file on disk. The member of
    an archive is reported by its path inside the archive only, and its text
    sits in the archive's row: after such a failure the archive rows below
    the search root go. Called after rga has exited. A failure here only
    costs the retry, so it is not reported."""
    import sqlite3
    if con is None or not failed:
        return
    try:
        for path in failed:
            if os.path.isabs(path):
                con.execute("delete from preproc_cache where file_path = ?", (os.path.normpath(path),))
                continue
            for base in {f(r) for r in as_roots(root) for f in (os.path.abspath, os.path.realpath)}:
                prefix = base.rstrip(os.sep) + os.sep
                con.execute(
                    "delete from preproc_cache where adapter in (%s)"
                    " and (substr(file_path, 1, ?) = ? or file_path = ?)"
                    % ",".join("?" * len(ARCHIVE_ADAPTERS)), (*ARCHIVE_ADAPTERS, len(prefix), prefix, base))
        con.commit()
    except sqlite3.Error:
        pass


# rga starts rg, and rg starts an adapter per file: a group of their own,
# so that all of them can be stopped together (POSIX; taskkill on Windows)
OWN_GROUP = {"process_group": 0} if hasattr(os, "killpg") else {}


def stop_tree(proc):
    """Stop rga and everything it started, if rga still runs. After rga has
    exited its process group is not touched: the id may belong to another
    program by then."""
    if proc.poll() is not None:
        return
    try:
        if OWN_GROUP:
            os.killpg(proc.pid, signal.SIGTERM)
        elif sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if OWN_GROUP:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait(timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def watch_reader(proc, gone):
    """Stop rga when the reader of our output goes away (`| head -1`).
    Without this the search runs on until the next hit is printed into the
    closed pipe, and with no further hit until every file is OCR'd. Only
    for a pipe, and only where poll() exists."""
    import select
    import stat
    try:
        fd = sys.stdout.fileno()
        if not hasattr(select, "poll") or not stat.S_ISFIFO(os.fstat(fd).st_mode):
            return
        poller = select.poll()
        # an event a pipe never has: what arrives is the error (Linux) or
        # hang-up (macOS) of a closed read end; asking for no event at all
        # reports nothing on macOS
        poller.register(fd, select.POLLPRI)
    except (OSError, ValueError, AttributeError):
        return

    def loop():
        while proc.poll() is None:
            try:
                if any(ev & (select.POLLERR | select.POLLHUP | select.POLLNVAL) for _fd, ev in poller.poll(200)):
                    gone.set()
                    stop_tree(proc)
                    return
            except OSError:
                return

    threading.Thread(target=loop, daemon=True).start()


def run_contents(o, st, printer, root, query):
    rga = shutil.which("rga")
    if not rga:
        warn("rga not found on PATH; install ripgrep-all")
        return False, 2
    adapters = adapter_list(o, st)
    cmd = [rga, "--json", "-n", "-s" if st["case"] == "sensitive" else "-i", "--hidden", "--no-ignore",
           "--rga-adapters=" + ",".join(adapters)]
    # per-run scratch dir: the adapter report file and, for --no-cache, a
    # throwaway cache (rga 0.10.10's --rga-no-cache makes every custom
    # adapter fail with "No cache?")
    run_dir = tempfile.mkdtemp(prefix=PROG + "-")
    held = None
    try:
        langs = engines.parse_langs(st["lang"])
        engine = None
        if o["ocr"]:
            try:
                engine = engines.resolve(st["engine"], langs)
            except engines.EngineError as e:
                warn(f"{e}; see --engines, or use --no-ocr")
                return False, 2
        if o["no_cache"]:
            cache = os.path.join(run_dir, "cache")
        else:
            key = engines.cache_tag(engine, langs, o["force"]) if engine else "none"
            cache = os.path.join(os.path.expanduser(st["cache_dir"]), key)
        held = prepare_cache(cache)
        cmd.append("--rga-cache-path=" + cache)
        if not o["regex"]:
            cmd.append("-F")
        if o["accurate"]:
            cmd.append("--rga-accurate")
        for d in st["exclude_list"]:
            cmd += ["-g", "!" + d]
        own_config = run_config(o["pass"], run_dir)
        if own_config:
            cmd.append("--rga-config-file=" + own_config)
        cmd += o["pass"] + ["-e", query, "--", *as_roots(root)]

        env = dict(os.environ)
        env.pop(ENV_PREFIX + "LANG", None)
        env.pop(ENV_PREFIX + "ENGINE", None)
        if langs:
            env[ENV_PREFIX + "LANG"] = ",".join(langs)
        if engine:
            env[ENV_PREFIX + "ENGINE"] = engine.name
        # set or removed on every run: a value inherited from the caller's
        # environment would fill this run's cache with the other mode's text
        for name, on in (("FORCE_OCR", o["ocr"] and o["force"]), ("NO_OCR", not o["ocr"])):
            if on:
                env[ENV_PREFIX + name] = "1"
            else:
                env.pop(ENV_PREFIX + name, None)
        # rg discards a preprocessor's stderr when it exits 0, so the adapters
        # report progress and errors through a file instead
        report_path = os.path.join(run_dir, "report")
        env[ENV_PREFIX + "REPORT"] = report_path
        status_line = st["progress_on"] and printer.tty and sys.stderr.isatty()

        hits = False
        width = st["snippet_int"]
        live = Status(Report(report_path), root) if status_line else None
        printer.status = live
        errbuf = []

        def read_stderr(pipe):
            # rga's own stderr is kept and forwarded after the run, so it never
            # mixes with the hits or the status line
            for raw in pipe:
                errbuf.append(raw)

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **OWN_GROUP)
        except OSError as e:
            warn(f"cannot run rga: {e}")
            return False, 2
        reader = threading.Thread(target=read_stderr, args=(proc.stderr,), daemon=True)
        reader.start()
        if live:
            live.start()
        gone = threading.Event()
        watch_reader(proc, gone)
        try:
            for raw in proc.stdout:
                if o["json"]:
                    sys.stdout.buffer.write(raw)
                    if b'"type":"match"' in raw:
                        hits = True
                    continue
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                t = ev.get("type")
                if t not in ("match", "context"):
                    continue
                d = ev["data"]
                path = rg_text(d.get("path"))
                if t == "match":
                    hits = True
                    if live:
                        live.hit()
                    text, hl = render_match(rg_text(d.get("lines")), d.get("submatches") or [], width)
                    printer.match(path, d.get("line_number"), text, hl)
                else:
                    printer.match(path, d.get("line_number"), rg_text(d.get("lines")).rstrip("\r\n"), [], sep="-")
            if gone.is_set():
                raise BrokenPipeError
            sys.stdout.flush()
            status = proc.wait()
            reader.join()
        finally:
            # left early (the reader of the output went away, a signal, an
            # error): rga, rg and the adapters must not go on with the OCR
            stop_tree(proc)
            if live:
                live.finish()
            printer.status = None
        err = b"".join(errbuf)
        if err:
            sys.stderr.buffer.write(err)
            sys.stderr.flush()
        failed = []
        for ev, mode, path, detail in Report(report_path).events():
            if ev == "error":
                warn(f"adapter {mode} failed on {display_path(path, root)}: {detail}")
            elif ev == "retry":
                warn(f"adapter {mode} failed on {display_path(path, root)}: {detail}"
                     f" (not cached, the next search reads the file again)")
                failed.append(path)
            elif ev == "partial":
                warn(f"adapter {mode}, {display_path(path, root)}: {detail}")
        forget_failed(held, failed, root)
        # rga reports its own failures (config, cache, adapter spawn) with exit 1, like "no match"
        if status == 1 and re.search(rb"(?im)^error", err):
            status = 2
        if status < 0:
            warn(f"rga was stopped by signal {-status}; the search is incomplete")
            status = 2
        # files the engine failed on were not searched and will be read
        # again: "no hit" would be wrong for this run
        if failed and status in (0, 1):
            status = 2
        return hits, status
    finally:
        if held is not None:
            held.close()
        shutil.rmtree(run_dir, ignore_errors=True)


# ----------------------------------------------------------------- main

def rga_config_flag(args):
    """The PATH of a --rga-config-file=PATH among rga pass-through flags, or None."""
    for a in args:
        if a.startswith("--rga-config-file="):
            return a.split("=", 1)[1]
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "setup" in argv and not any(a in ("-h", "--help") for a in argv[:argv.index("setup")]):
        # `setup` is a subcommand: everything before it must be an rga option
        # (the test suite passes --rga-config-file first), everything after
        # it belongs to setup
        i = argv.index("setup")
        if all(a.startswith("--rga-") for a in argv[:i]):
            from rga_ocr import setup_cmd
            environment_hints()          # setup acts on the same settings
            return setup_cmd.main(argv[i + 1:], config_path, settings_from,
                                  rga_config=rga_config_flag(argv[:i]))
    o = parse_args(argv)
    cfg = config_path(o["config"])
    environment_hints()
    if o["init"]:
        return init_config(cfg)
    st = settings_from(cfg)
    st.update(o["flags"])
    if o["cache_info"]:
        return cache_info(st["cache_dir"])
    if o["engines"]:
        return print_engines(st)
    if o["clear_cache"]:
        return clear_cache(st["cache_dir"], o["targets"], o["dry_run"])

    if st["case"] not in ("insensitive", "sensitive"):
        warn(f"case: expected insensitive or sensitive, got {st['case']!r}; using insensitive")
        st["case"] = "insensitive"
    if st["name_blank"] not in NAME_BLANK_MODES:
        warn(f"name_blank: expected one of {', '.join(NAME_BLANK_MODES)}, got {st['name_blank']!r}; using nonletter")
        st["name_blank"] = "nonletter"
    try:
        st["snippet_int"] = max(0, int(st["snippet"]))
    except ValueError:
        warn(f"snippet: expected a number, got {st['snippet']!r}; using 80")
        st["snippet_int"] = 80
    st["exclude_list"] = [] if o["no_exclude"] else as_list(st["exclude"])
    optional = as_bool(st["name_blank_optional"], "name_blank_optional")
    st["progress_on"] = as_bool(st["progress"], "progress")

    roots, query = o["roots"], o["query"]
    root = roots[0] if len(roots) == 1 else roots
    if query == "setup" and any(a.partition("=")[0] in SETUP_FLAGS for a in argv[:argv.index("setup")]):
        warn('searching for the word "setup"; the setup command goes first: '
             f"{PROG} setup [--apply] [--engine NAME] ...")
    absent = [r for r in roots if not os.path.exists(r)]
    if absent:
        warn(f"no such path: {', '.join(absent)}"
             + ("; everything after QUERY is a PATH, so a query of several words needs quotes"
                if len(roots) > 1 else ""))
        return 2
    tty = sys.stdout.isatty() and not o["json"]
    printer = Printer(tty, "never" if o["json"] else o["color"])
    hits = False

    if o["names"]:
        pat = name_pattern(query, o["regex"], st["name_blank"], optional, st["case"] == "insensitive")
        if pat is None and not o["contents"]:
            return 2
        found = [p for r in roots for p in walk_names(r, set(st["exclude_list"]), pat)] if pat else []
        if found:
            hits = True
            if o["json"]:
                for p in found:
                    print(name_event(p))
            else:
                printer.heading("# names")
                for p in found:
                    printer.name(p)
                if o["contents"]:
                    printer.heading("\n# contents")

    # the content pass writes rg's bytes past this text layer: flush, or on
    # a pipe the name hits come out after them
    sys.stdout.flush()
    status = 1
    if o["contents"]:
        chits, status = run_contents(o, st, printer, root, query)
        hits = hits or chits
        if status >= 2 and not chits:
            return status
    return 0 if hits else 1


def prepare_streams():
    """Output must not fail on a character the stream cannot encode. With
    UTF-8, a file name that is not valid UTF-8 (Linux) goes out as the bytes
    it has on disk; any other encoding gets a backslash escape. On Windows a
    pipe or file gets UTF-8, which is what rg writes there and what --json
    passes through; the console is left alone."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if sys.platform == "win32":
                if not stream.isatty():
                    stream.reconfigure(encoding="utf-8", errors="backslashreplace")
                else:
                    stream.reconfigure(errors="backslashreplace")
            elif (stream.encoding or "").lower().replace("-", "").replace("_", "") == "utf8":
                stream.reconfigure(errors="surrogateescape")
            else:
                stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def _stopped(signum, _frame):
    raise SystemExit(128 + signum)


def run():
    """Console-script entry point: exit codes for a broken pipe and Ctrl-C.
    SIGTERM and SIGHUP end the run like Ctrl-C does, so rga is stopped and
    the scratch directory removed."""
    prepare_streams()
    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), _stopped)
            except (ValueError, OSError):
                pass
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    run()
