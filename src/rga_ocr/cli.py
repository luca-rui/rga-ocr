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
import subprocess
import sys
import tempfile
import threading
import time

from rga_ocr import ENV_PREFIX, LEGACY_ENV_PREFIX, LEGACY_PROG, PROG, VERSION, engines, paths

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
NO_OCR_ADAPTERS = ["poppler", "officexml"]

# rg output-format options: the content pass reads rg's JSON events, and
# these flags replace or silence that stream, so they are refused up front
NO_JSON_OPTS = {"-c", "--count", "--count-matches", "-l", "--files-with-matches",
                "--files-without-match", "--files", "-q", "--quiet", "--no-json"}
# rg / rga options that take a separate value argument (for pass-through)
VALOPTS = set("""
-g -t -T -C -A -B -j -M -E -m -d -f --glob --iglob --type --type-not --context
--after-context --before-context --threads --max-columns --encoding --max-count
--max-depth --max-filesize --file --pre --pre-glob --color --colors --sort --sortr
--path-separator --dfa-size-limit --regex-size-limit --rga-cache-path
--rga-config-file --rga-adapters --rga-cache-max-blob-len
--rga-cache-compression-level --rga-max-archive-recursion
""".split())

PREFIX_RE = re.compile(r"^(?:Page \d+: )?(?:[^\s:/]+\.[A-Za-z0-9]{1,8}: )*")

TEMPLATE = f"""\
# {PROG} profile.  key = value, one per line, '#' starts a comment.
# Every key can also be set as {ENV_PREFIX}<KEY> in the environment, most as a
# flag. Precedence: built-in default < this file < environment < flag.

# OCR engine: auto | vision | winocr | rapidocr | tesseract (flag --engine).
# auto takes the first one that works here: vision on macOS, winocr on
# Windows, otherwise rapidocr, then tesseract. --engines lists them.
engine = auto

# OCR languages, comma separated BCP 47 tags (de-DE,en-US). Empty: the
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
cache_dir = {DEFAULTS['cache_dir']}

# Extra ripgrep-all adapters appended to the list, e.g. mail,ffmpeg
adapters_extra =

# true: show a live status line (elapsed time, hits, files OCR'd, current
# file) on stderr while the content pass runs, and a one-line summary after
# it. Only when stdout and stderr are a terminal and --json is not given.
# Flags --progress / --no-progress.
progress = true
"""

USAGE = f"""\
usage: {PROG} [options] QUERY [PATH]        PATH defaults to .
       {PROG} [--rga-config-file=F] setup [--apply] [--engine NAME] [--lang L] [--config PATH]

  -s / -i                case-sensitive / case-insensitive (default -i)
  -r                     QUERY is a regex (default literal)
  --snippet N            characters shown around a content match (default 80)
  --full                 whole lines, same as --snippet 0
  --name-blank MODE      nonletter | separators | strict (what a blank may match in names)
  --name-blank-optional  the run a blank matches may be empty
  --engine NAME          OCR engine: auto, vision, winocr, rapidocr, tesseract (default auto)
  --engines              list the engines, whether each works here, and what auto picks; exit
  --lang L               OCR languages, e.g. de-DE,en-US (default: the engine decides)
  --no-ocr               PDFs via poppler text layer only, images skipped
  --force-ocr            OCR every PDF page even if it has a text layer
  --mail                 also search .eml/.mbox
  --accurate             sniff mime types instead of trusting extensions
  --exclude LIST         directory names to skip (replaces the default list)
  --no-exclude           skip nothing
  --names-only / --no-names
  --json                 rg JSON events; name hits first as {{"type":"name","path":...}}
  --no-cache             do not read or write the OCR cache
  --progress / --no-progress   status line while searching and a summary after (default on)
  --init-config          write a commented profile to {{config path}} and exit
  --cache-info           list the caches (cache-id, entries, size, last added, folders) and exit
  --clear-cache CACHE-ID|DIR ...|all   delete the named caches, or every cache, and exit
  --dry-run              with --clear-cache: show what would be removed, delete nothing
  --config PATH          use this profile file (env {ENV_PREFIX}CONFIG)
  --version, -h, --help

Anything else is passed to rga/rg (-g, -t, -C, -U, -j, -M, --rga-config-file ...),
except rg's output-format flags (-l, -c, --files, -q ...), which are refused.

profile: {{config path}}   keys: {", ".join(DEFAULTS)}
exit status: 0 at least one hit, 1 no hit, 2 failure
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


def load_profile(path):
    vals = {}
    if not os.path.isfile(path):
        return vals
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
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
    return s


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
    start-up. An existing database is only opened, never changed: rga
    owns its schema. The caller closes the connection after the run."""
    import sqlite3
    os.makedirs(d, exist_ok=True)
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
    """One row per engine: name, usable here, note (reason or 'auto')."""
    rows = [list(r) for r in engines.table(engines.parse_langs(st["lang"]))]
    print_table(["ENGINE", "AVAILABLE", "NOTE"], rows)
    chosen = st["engine"]
    if chosen != "auto":
        ok = any(r[0] == chosen and r[1] == "yes" for r in rows)
        print(f"\nconfigured: {chosen} ({'available' if ok else 'NOT available'})")
    return 0


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

def parse_args(argv):
    o = {
        "flags": {}, "pass": [], "regex": False, "ocr": True, "force": False, "mail": False,
        "accurate": False, "no_exclude": False, "names": True, "contents": True, "json": False,
        "no_cache": False, "init": False, "clear_cache": False, "cache_info": False, "engines": False,
        "dry_run": False, "config": None, "query": None, "root": ".",
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
        if "=" in a and a.startswith("--"):
            name, _, val = a.partition("=")
            if name in ("--engine", "--lang", "--snippet", "--name-blank", "--exclude", "--config"):
                args.insert(0, val)
                a = name
        if a == "-s":
            o["flags"]["case"] = "sensitive"
        elif a == "-i":
            o["flags"]["case"] = "insensitive"
        elif a == "-r":
            o["regex"] = True
        elif a == "--snippet":
            o["flags"]["snippet"] = take(a)
        elif a == "--full":
            o["flags"]["snippet"] = "0"
        elif a == "--name-blank":
            o["flags"]["name_blank"] = take(a)
        elif a == "--name-blank-optional":
            o["flags"]["name_blank_optional"] = "true"
        elif a == "--engine":
            o["flags"]["engine"] = take(a)
        elif a == "--engines":
            o["engines"] = True
        elif a == "--lang":
            o["flags"]["lang"] = take(a)
        elif a == "--exclude":
            o["flags"]["exclude"] = take(a)
        elif a == "--no-exclude":
            o["no_exclude"] = True
        elif a == "--no-ocr":
            o["ocr"] = False
        elif a == "--force-ocr":
            o["force"] = True
        elif a == "--mail":
            o["mail"] = True
        elif a == "--accurate":
            o["accurate"] = True
        elif a == "--names-only":
            o["contents"] = False
        elif a == "--no-names":
            o["names"] = False
        elif a == "--json":
            o["json"] = True
        elif a == "--no-cache":
            o["no_cache"] = True
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
        elif a == "--config":
            o["config"] = take(a)
        elif a.startswith("-") and len(a) > 1:
            if a in NO_JSON_OPTS:
                warn(f"{a} is not supported: the content pass reads rg's JSON output, which {a} replaces")
                raise SystemExit(2)
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
    o["query"] = pos[0]
    if len(pos) > 1:
        o["root"] = pos[1]
    if len(pos) > 2:
        warn(f"too many arguments: {' '.join(pos[2:])}")
        raise SystemExit(2)
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
        warn(f"bad regex for the name pass: {e}")
        raise SystemExit(2)


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
            parts = raw.decode("utf-8", "replace").split("\t", 3)
            if len(parts) == 4:
                out.append(parts)
        return out


def display_path(path, root):
    """rga reports absolute virtual paths with a '/./' from the search root;
    show them the way the hits are shown, relative to the root. rga echoes
    the root as given (or canonical, for a relative one), so compare the
    normalised path against both spellings of the root."""
    if os.path.isabs(path):
        path = os.path.normpath(path)
    for base in (os.path.abspath(root), os.path.realpath(root)):
        prefix = base.rstrip(os.sep) + os.sep
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
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

    def __init__(self, report, root):
        self.report = report
        self.root = root
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
                f"{self.done} file" + ("" if self.done == 1 else "s") + " OCR'd"]

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
    def __init__(self, tty):
        self.tty = tty
        self.color = tty and not os.environ.get("NO_COLOR")
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
            out.append(text[last:s]); out.append(self.c("1;31", text[s:e])); last = e
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
    """The rga adapters for this run: OCR or poppler for PDFs, the base set,
    `mail` with --mail, and whatever `adapters_extra` names (ffmpeg is never
    added on its own; it costs a process per media file)."""
    adapters = list(OCR_ADAPTERS if o["ocr"] else NO_OCR_ADAPTERS) + BASE_ADAPTERS
    if o["mail"]:
        adapters.append("mail")
    for a in as_list(st["adapters_extra"]):
        if a not in adapters:
            adapters.append(a)
    return adapters


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
        cmd += o["pass"] + ["-e", query, "--", root]

        env = dict(os.environ)
        env.pop(ENV_PREFIX + "LANG", None)
        env.pop(ENV_PREFIX + "ENGINE", None)
        if langs:
            env[ENV_PREFIX + "LANG"] = ",".join(langs)
        if engine:
            env[ENV_PREFIX + "ENGINE"] = engine.name
        if o["force"]:
            env[ENV_PREFIX + "FORCE_OCR"] = "1"
        else:
            env.pop(ENV_PREFIX + "FORCE_OCR", None)
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
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        except OSError as e:
            warn(f"cannot run rga: {e}")
            return False, 2
        reader = threading.Thread(target=read_stderr, args=(proc.stderr,), daemon=True)
        reader.start()
        if live:
            live.start()
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
            sys.stdout.flush()
            status = proc.wait()
            reader.join()
        finally:
            if live:
                live.finish()
            printer.status = None
        err = b"".join(errbuf)
        if err:
            sys.stderr.buffer.write(err)
            sys.stderr.flush()
        for ev, mode, path, detail in Report(report_path).events():
            if ev == "error":
                warn(f"adapter {mode} failed on {display_path(path, root)}: {detail}")
        # rga reports its own failures (config, cache, adapter spawn) with exit 1, like "no match"
        if status == 1 and re.search(rb"(?im)^error", err):
            status = 2
        return hits, status
    finally:
        if held is not None:
            held.close()
        shutil.rmtree(run_dir, ignore_errors=True)


# ----------------------------------------------------------------- main

def legacy_hints(o, cfg):
    """One warning each for leftovers from the time the tool was called rga-vision."""
    old_env = sorted(k for k in os.environ if k.startswith(LEGACY_ENV_PREFIX))
    if old_env:
        warn(f"{', '.join(old_env)} ignored; the variables are called {ENV_PREFIX}<KEY> now")
    if o["config"] is None and not os.environ.get(ENV_PREFIX + "CONFIG") and not os.path.exists(cfg):
        old = os.path.join(os.path.dirname(os.path.dirname(cfg)), LEGACY_PROG, "config")
        if os.path.isfile(old):
            warn(f"profile {old} is no longer read; move it to {cfg}")


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
            return setup_cmd.main(argv[i + 1:], config_path, settings_from,
                                  rga_config=rga_config_flag(argv[:i]))
    o = parse_args(argv)
    cfg = config_path(o["config"])
    legacy_hints(o, cfg)
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

    root, query = o["root"], o["query"]
    if not os.path.exists(root):
        warn(f"no such path: {root}")
        return 2
    tty = sys.stdout.isatty() and not o["json"]
    printer = Printer(tty)
    hits = False

    if o["names"]:
        pat = name_pattern(query, o["regex"], st["name_blank"], optional, st["case"] == "insensitive")
        found = list(walk_names(root, set(st["exclude_list"]), pat))
        if found:
            hits = True
            if o["json"]:
                for p in found:
                    print(json.dumps({"type": "name", "path": p}, separators=(",", ":"), ensure_ascii=False))
            else:
                printer.heading("# names")
                for p in found:
                    printer.name(p)
                if o["contents"]:
                    printer.heading("\n# contents")

    status = 1
    if o["contents"]:
        chits, status = run_contents(o, st, printer, root, query)
        hits = hits or chits
        if status >= 2 and not chits:
            return status
    return 0 if hits else 1


def run():
    """Console-script entry point: exit codes for a broken pipe and Ctrl-C."""
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    run()
