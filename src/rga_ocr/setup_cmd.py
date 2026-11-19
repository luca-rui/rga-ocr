"""`rga-ocr setup`: check the machine and wire the adapters into ripgrep-all.

Dry run by default: every section prints what is missing and the command
that fixes it. With --apply the tool does what it can itself (fetch
Tesseract language files, warm the RapidOCR models, merge the adapter
entries into rga's config) and prints the rest for the user to run.
--remove is the way back and no dry run: it takes the entries out of
rga's config at once and prints commands for everything else.

Sections: tools on PATH, the OCR engine, the ripgrep-all config and a
verification.
"""

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys

from rga_ocr import PROG, engines, paths

RGA_RELEASES = "https://github.com/phiresky/ripgrep-all/releases/download"

ADAPTER_MODULE = "rga_ocr.adapter"
ADAPTER_ARGS = ["-I", "-X", "utf8", "-m", ADAPTER_MODULE]
ADAPTER_NAMES = ("ocrpdf", "ocrimg", "officexml")

IMAGE_EXT = ["jpg", "jpeg", "png", "heic", "heif", "tif", "tiff", "webp", "gif", "bmp"]
IMAGE_MIME = ["image/jpeg", "image/png", "image/heic", "image/heif", "image/tiff",
              "image/webp", "image/gif", "image/bmp"]
OFFICE_EXT = ["xlsx", "pptx", "ods", "odp"]
OFFICE_MIME = ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "application/vnd.oasis.opendocument.spreadsheet",
               "application/vnd.oasis.opendocument.presentation"]

USAGE = f"""\
usage: {PROG} [--rga-config-file=F] setup [--apply] [--engine NAME] [--lang L] [--config PATH]
       {PROG} [--rga-config-file=F] setup --remove [--config PATH]

Checks the tools on PATH, the OCR engine, and ripgrep-all's config, and
prints what is missing with the command that installs it. A search needs
no entries in rga's config: where they are missing or out of date, {PROG}
passes its own to rga for that run. Writing them is for plain rga and for
searches that name a config with --rga-config-file. --apply fetches
Tesseract language files, warms the RapidOCR models and merges the three
{PROG} adapters into rga's config; the first run keeps a .bak copy, later
runs a timestamped one, and comments in the file are not preserved.
Package installs stay commands for you to run. --engine, --lang and
--config override the profile; --rga-config-file=F targets another rga
config. Exit status: 0 ready, 1 something to do, 2 usage error.

--remove takes the three adapters out of rga's config again, with the same
backup copy, and prints the commands that delete the cache, the profile,
the fetched language files and the package. It deletes none of them itself.
"""

REQUIRED_TOOLS = ("rga", "rga-preproc", "rg", "pandoc")
# the ripgrep-all releases the test suite runs against; older ones get a warning
RGA_TESTED = (0, 10, 9) if sys.platform == "win32" else (0, 10, 10)
OPTIONAL_TOOLS = {"ffmpeg": "the ffmpeg adapter (adapters_extra = ffmpeg)"}


# --- tools -----------------------------------------------------------------

def rga_download_url():
    """The release archive for this machine, or None when rga has no build for it."""
    m = platform.machine().lower()
    if sys.platform == "linux":
        if m in ("x86_64", "amd64"):
            return f"{RGA_RELEASES}/v0.10.10/ripgrep_all-v0.10.10-x86_64-unknown-linux-musl.tar.gz"
        if m in ("aarch64", "arm64"):
            return f"{RGA_RELEASES}/v0.10.10/ripgrep_all-v0.10.10-aarch64-unknown-linux-gnu.tar.gz"
        if m.startswith("arm"):
            return f"{RGA_RELEASES}/v0.10.10/ripgrep_all-v0.10.10-arm-unknown-linux-gnueabihf.tar.gz"
    if sys.platform == "win32":
        return f"{RGA_RELEASES}/v0.10.9/ripgrep_all-v0.10.9-x86_64-pc-windows-msvc.zip"
    if sys.platform == "darwin":
        arch = "aarch64" if m == "arm64" else "x86_64"
        return f"{RGA_RELEASES}/v0.10.10/ripgrep_all-v0.10.10-{arch}-apple-darwin.tar.gz"
    return None


def package_manager():
    candidates = {"darwin": ["brew"], "win32": ["scoop", "choco", "winget"]}
    for pm in candidates.get(sys.platform, ["apt-get", "dnf", "pacman", "zypper", "brew"]):
        if shutil.which(pm):
            return pm
    return None


def install_commands(missing, pm):
    """Shell commands that install the missing tools with this package
    manager; rga comes from its release archive where no package exists."""
    missing = set(missing)
    want_rga = "rga" in missing
    others = missing - {"rga", "rga-preproc"}
    pkg = {
        "brew": {"rg": "ripgrep", "pandoc": "pandoc", "ffmpeg": "ffmpeg", "rga": "ripgrep-all"},
        "apt-get": {"rg": "ripgrep", "pandoc": "pandoc", "ffmpeg": "ffmpeg"},
        "dnf": {"rg": "ripgrep", "pandoc": "pandoc", "ffmpeg": "ffmpeg"},
        "zypper": {"rg": "ripgrep", "pandoc": "pandoc", "ffmpeg": "ffmpeg"},
        "pacman": {"rg": "ripgrep", "pandoc": "pandoc-cli", "ffmpeg": "ffmpeg", "rga": "ripgrep-all"},
        "choco": {"rg": "ripgrep", "pandoc": "pandoc", "ffmpeg": "ffmpeg", "rga": "ripgrep-all"},
        "winget": {"rg": "BurntSushi.ripgrep.MSVC", "pandoc": "JohnMacFarlane.Pandoc", "ffmpeg": "Gyan.FFmpeg"},
    }
    cmds = []
    if pm == "scoop":
        # the rga manifest depends on ripgrep, pandoc, poppler and ffmpeg
        names = ["rga"] if want_rga else sorted({"rg": "ripgrep", "pandoc": "pandoc", "ffmpeg": "ffmpeg"}[t]
                                                for t in others)
        if names:
            cmds.append("scoop install " + " ".join(names))
        if "rga-preproc" in missing and not want_rga:
            cmds.append(PREPROC_HINT)
        return cmds
    table = pkg.get(pm, {})
    names = sorted({table[t] for t in (others | ({"rga"} if want_rga else set())) if t in table})
    if names:
        prefix = {"apt-get": "sudo apt-get install ", "dnf": "sudo dnf install ", "zypper": "sudo zypper install ",
                  "pacman": "sudo pacman -S ", "brew": "brew install ", "choco": "choco install ",
                  "winget": "winget install "}[pm]
        cmds.append(prefix + " ".join(names))
    if want_rga and "rga" not in table:
        url = rga_download_url()
        cmds.append(f"download {url} and put rga (and rga-preproc) on PATH" if url
                    else "build rga from source: cargo install ripgrep_all")
    if "rga-preproc" in missing and not want_rga:
        cmds.append(PREPROC_HINT)
    return cmds


PREPROC_HINT = ("put rga-preproc on PATH next to rga: it ships in the same package or archive, "
                "and rga starts it for every file")


def rga_version(binary="rga"):
    """(0, 10, 10) from `rga --version`, or None when it cannot be read."""
    try:
        p = subprocess.run([binary, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    # the line that names the program, not the first number anywhere
    m = re.search(r"^(?:ripgrep-all|rga)\s+v?(\d+)\.(\d+)\.(\d+)", p.stdout, re.M)
    return tuple(int(x) for x in m.groups()) if m else None


def check_tools(out):
    out.section("tools")
    missing = []
    for t in REQUIRED_TOOLS:
        p = shutil.which(t)
        out.line(f"{t:11} {p or 'MISSING'}")
        if not p:
            missing.append(t)
    for t, why in OPTIONAL_TOOLS.items():
        p = shutil.which(t)
        out.line(f"{t:11} {p or 'missing (optional: ' + why + ')'}")
    if "rga" not in missing:
        v = rga_version()
        dotted = ".".join(map(str, RGA_TESTED))
        if v is None:
            out.line(f"rga --version gave no version number; {PROG} is tested with ripgrep-all {dotted}")
        elif v < RGA_TESTED:
            # a warning, not a TODO: an older rga may well work
            out.line(f"ripgrep-all {'.'.join(map(str, v))} is older than {dotted}, "
                     f"the release {PROG} is tested with; upgrade it if searches misbehave")
        else:
            out.line(f"ripgrep-all {'.'.join(map(str, v))}")
    if missing:
        pm = package_manager()
        if pm:
            for c in install_commands(missing, pm):
                out.todo(c)
        elif missing == ["rga-preproc"]:
            out.todo(PREPROC_HINT)
        else:
            url = rga_download_url()
            out.todo(f"install {', '.join(missing)} (no package manager found"
                     + (f"; rga: {url}" if "rga" in missing and url else "") + ")")
    return not missing


# --- engine ----------------------------------------------------------------

def under_pipx():
    return "pipx" in os.path.normcase(sys.prefix).split(os.sep)


def under_uv_tool():
    """True inside an environment `uv tool install` made: uv writes a
    uv-receipt.toml into it and keeps it under <data dir>/uv/tools/<name>
    (UV_TOOL_DIR moves that, the receipt stays)."""
    if os.path.isfile(os.path.join(sys.prefix, "uv-receipt.toml")):
        return True
    parts = os.path.normcase(sys.prefix).split(os.sep)
    return parts[-3:-1] == ["uv", "tools"]


def homebrew_prefix():
    """The environment's path through Homebrew's `opt` link, or None
    outside a Homebrew formula. A formula keeps its virtualenv in
    <prefix>/Cellar/<formula>/<version>/libexec, and that directory is
    gone after `brew upgrade`; <prefix>/opt/<formula> always points at
    the installed version."""
    parts = sys.prefix.split(os.sep)
    if len(parts) >= 5 and parts[-1] == "libexec" and parts[-4] == "Cellar":
        return os.sep.join(parts[:-4] + ["opt", parts[-3], "libexec"])
    if (len(parts) >= 4 and parts[-1] == "libexec" and parts[-3] == "opt"
            and os.path.isdir(os.sep.join(parts[:-3] + ["Cellar", parts[-2]]))):
        return sys.prefix
    return None


def under_homebrew():
    return homebrew_prefix() is not None


def homebrew_formula():
    """The formula this environment belongs to, as `brew` names it."""
    return os.path.basename(os.path.dirname(homebrew_prefix()))


def adapter_python():
    """The interpreter rga starts the adapters with: this one, by a path
    that outlives an upgrade of the package where there is one."""
    opt = homebrew_prefix()
    if opt:
        stable = os.path.join(opt, "bin", os.path.basename(sys.executable))
        if os.path.isfile(stable):
            return stable
    return sys.executable


def python_command():
    """This interpreter as the first word of a command line. On Windows a
    bare path runs in cmd and PowerShell alike; a path that needs quotes
    is no command in PowerShell without the call operator."""
    exe = sys.executable
    if sys.platform == "win32":
        return exe if re.fullmatch(r"[\w.:\\/-]+", exe) else "& " + quote_path(exe)
    return f'"{exe}"'


def quote_path(path):
    """A path as one literal shell word: nothing in it is expanded."""
    if sys.platform == "win32":
        return "'" + path.replace("'", "''") + "'"
    return shlex.quote(path)


def extra_install_command(extra):
    spec = f"{PROG}[{extra}]"
    if under_pipx():
        return f'pipx install --force "{spec}"'
    if under_uv_tool():
        return f'uv tool install --force "{spec}"'
    if under_homebrew():
        # one line that is safe to paste: no comment, since zsh on macOS
        # does not treat "#" as one at the prompt
        # The PyPI install comes first: if pipx is missing, the line stops
        # there and the formula stays.
        return f'pipx install "{spec}" && brew uninstall {homebrew_formula()} && {PROG} setup --apply'
    return f'{python_command()} -m pip install "{spec}"'


def todo_extra(out, extra, note=""):
    """The TODO line that installs an engine's extra."""
    if under_homebrew():
        out.line("the Homebrew formula carries the vision engine only; "
                 "another engine needs the PyPI install in its place")
        note = ""
    out.todo(extra_install_command(extra) + note)


def uninstall_command():
    if under_pipx():
        return f"pipx uninstall {PROG}"
    if under_uv_tool():
        return f"uv tool uninstall {PROG}"
    if under_homebrew():
        return f"brew uninstall {homebrew_formula()}"
    return f"{python_command()} -m pip uninstall {PROG}"


def check_engine(out, name, langs, apply):
    out.section("engine")
    for n, ok, note in engines.table(langs):
        out.line(f"{n:10} {'yes' if ok == 'yes' else 'no ':3}  {note}")
    try:
        cls = engines.resolve(name, langs)
    except engines.EngineError as e:
        out.line(f"configured: {name} -> {e}")
        if name != "auto":
            try:
                cls = engines.load(name)
            except engines.EngineError:
                return False
            if not cls.installed():
                todo_extra(out, cls.extra)
                return False
            return _engine_fixes(out, cls, langs, apply)
        # auto: the first engine of this platform's order whose Python side
        # is installed only lacks one-time work (language files, a model)
        for n in engines.auto_order():
            try:
                cls = engines.load(n)
            except engines.EngineError:
                continue
            if cls.installed():
                out.line(f"auto will pick {n} once it is ready: {cls.available(langs)[1]}")
                return _engine_fixes(out, cls, langs, apply)
        todo_extra(out, "rapidocr", "   # the portable engine")
        return False
    out.line(f"configured: {name} -> {cls.name} ({engines.cache_tag(cls, langs)})")
    return _engine_fixes(out, cls, langs, apply)


def _engine_fixes(out, cls, langs, apply):
    """Engine-specific one-time work: tessdata files, Windows language packs,
    the RapidOCR model download. Returns True when the engine is ready."""
    if cls is None:
        return False
    if cls.name == "tesseract":
        from rga_ocr.engines import tesseract as t
        try:
            codes = t.codes_for(langs)
        except ValueError as e:
            out.line(str(e))
            return False
        if t.find_tessdata(codes):
            return cls.available(langs)[0]
        target = paths.tessdata_dir()
        fetched = True
        for code in codes:
            url = t.DOWNLOAD_BASE + code + ".traineddata"
            dest = os.path.join(target, code + ".traineddata")
            if apply:
                fetched = fetch(url, dest, out) and fetched
            else:
                out.todo(f"fetch {url} -> {dest}")
        return fetched and cls.available(langs)[0]
    if cls.name == "winocr":
        ok, reason = cls.available(langs)
        if not ok:
            out.todo(reason)
        return ok
    if cls.name == "rapidocr":
        if not cls.available(langs)[0]:
            return False
        if apply:
            out.line("initialising RapidOCR once (downloads the models for non-Latin scripts)")
            try:
                cls(langs)
            except Exception as e:  # noqa: BLE001 - report, do not crash setup
                out.line(f"RapidOCR init failed: {e}")
                return False
        else:
            out.line("--apply initialises RapidOCR once so the first search does not download models")
        return True
    return cls.available(langs)[0]


def fetch(url, dest, out, timeout=60):
    """Download url to dest through a .part file. A network or HTTP failure
    is reported with the command to retry by hand; returns whether it worked."""
    import shutil as _shutil
    import urllib.error
    import urllib.request
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    out.line(f"fetching {url}")
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, open(tmp, "wb") as f:
            _shutil.copyfileobj(r, f)
        os.replace(tmp, dest)
    except (urllib.error.URLError, OSError) as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        out.line(f"fetch failed: {e}")
        out.todo(f'curl -sSL -o "{dest}" {url}')
        return False
    out.line(f"wrote {dest}")
    return True


# --- ripgrep-all config ----------------------------------------------------

def load_jsonc(text):
    """Parse rga's config.jsonc: JSON with // and /* */ comments and trailing commas."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
        else:
            if c in "}]":
                # a trailing comma: the last thing before the bracket, blanks
                # aside, with a value in front of it ("[,]" stays an error).
                # Strings are whole chunks, so a "," inside one is safe.
                k = len(out) - 1
                while k >= 0 and out[k].isspace():
                    k -= 1
                j = k - 1
                while j >= 0 and out[j].isspace():
                    j -= 1
                if k >= 0 and out[k] == "," and j >= 0 and out[j] not in ("[", "{", ","):
                    del out[k]
            out.append(c)
            i += 1
    stripped = "".join(out)
    return json.loads(stripped) if stripped.strip() else {}


def adapter_entries(binary=None, args=None):
    """The three custom adapter entries, pointing at this interpreter."""
    binary = binary or adapter_python()
    args = list(ADAPTER_ARGS if args is None else args)

    def entry(name, mode, desc, ext, mime, hint, version=1):
        return {"name": name, "description": f"{PROG}: {desc}", "version": version,
                "extensions": ext, "mimetypes": mime, "binary": binary,
                "args": args + [mode, "${input_virtual_path}"],
                "disabled_by_default": False, "match_only_by_mime": False,
                "output_path_hint": "${input_virtual_path}" + hint}
    return [
        entry("ocrpdf", "pdf", "PDF text layer via pypdfium2, OCR for pages without one",
              ["pdf"], ["application/pdf"], ".txt.asciipagebreaks", version=2),
        entry("ocrimg", "image", "OCR for photos and scans", IMAGE_EXT, IMAGE_MIME, ".txt", version=2),
        entry("officexml", "office", "xlsx, pptx, ods, odp text (docx and odt go to pandoc)",
              OFFICE_EXT, OFFICE_MIME, ".txt.asciipagebreaks"),
    ]


def merge_config(existing, entries):
    """existing (parsed config or {}) with our entries first, every other
    custom adapter kept."""
    cfg = dict(existing)
    drop = {e["name"] for e in entries}
    kept = [a for a in cfg.get("custom_adapters") or [] if a.get("name") not in drop]
    cfg["custom_adapters"] = list(entries) + kept
    return cfg


def backup_path(cfg_path):
    """`config.jsonc.bak` the first time; later runs never overwrite it and
    use a timestamped name instead."""
    first = cfg_path + ".bak"
    if not os.path.exists(first):
        return first
    import time
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path, n = f"{cfg_path}.{stamp}.bak", 1
    while os.path.exists(path):
        n += 1
        path = f"{cfg_path}.{stamp}-{n}.bak"
    return path


def check_rga_config(out, apply, rga_config=None):
    out.section("ripgrep-all config")
    cfg_path = rga_config or paths.rga_config_path()
    out.line(f"file: {cfg_path}")
    existing = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                existing = load_jsonc(f.read())
        except (OSError, ValueError) as e:
            out.line(f"cannot parse {cfg_path}: {e}; fix or remove it first")
            return False
    elif shutil.which("rga") and apply and not rga_config:
        # rga writes its default config on first run
        subprocess.run(["rga", "--rga-list-adapters"], capture_output=True)
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                existing = load_jsonc(f.read())
    entries = adapter_entries()
    merged = merge_config(existing, entries)
    before = [a.get("name") for a in existing.get("custom_adapters") or []]
    out.line(f"adapters now: {', '.join(before) or '(none)'}")
    out.line(f"adapters after: {', '.join(a['name'] for a in merged['custom_adapters'])}")
    out.line(f"adapter command: {adapter_python()} {' '.join(ADAPTER_ARGS)} <mode> <file>")
    unchanged = existing.get("custom_adapters") == merged["custom_adapters"]
    if unchanged:
        out.line("up to date")
        return True
    if not apply:
        cmd = f"{PROG} setup --apply   # writes the entries above; a .bak copy is kept, comments are not"
        if rga_config:
            # a search that names this file uses it as it is
            out.todo(cmd)
            return False
        out.line(f"not written, and not needed for {PROG}: every search brings the entries along")
        out.line(f"for plain rga: {cmd}")
        return True
    if os.path.exists(cfg_path):
        bak = backup_path(cfg_path)
        shutil.copy(cfg_path, bak)
        out.line(f"backup: {bak}")
    os.makedirs(os.path.dirname(cfg_path) or ".", exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")
    out.line(f"wrote {cfg_path} (comments from the previous file are not preserved)")
    return True


def remove_adapters(existing):
    """(config without our entries, names taken out). Every other
    custom adapter stays."""
    ours = set(ADAPTER_NAMES)
    cfg = dict(existing)
    adapters = cfg.get("custom_adapters") or []
    gone = [a.get("name") for a in adapters if a.get("name") in ours]
    if gone:
        cfg["custom_adapters"] = [a for a in adapters if a.get("name") not in ours]
    return cfg, gone


def remove_from_rga_config(out, rga_config=None):
    out.section("ripgrep-all config")
    cfg_path = rga_config or paths.rga_config_path()
    out.line(f"file: {cfg_path}")
    by_hand = f"take the {', '.join(ADAPTER_NAMES)} entries out by hand"
    if not os.path.exists(cfg_path):
        if rga_config:
            # a path somebody typed: a slip must not read as "done"
            out.line("no such file; check the path given with --rga-config-file=")
            return False
        out.line("absent; nothing to remove")
        return True
    try:
        with open(cfg_path, encoding="utf-8") as f:
            existing = load_jsonc(f.read())
    except (OSError, ValueError) as e:
        out.line(f"cannot parse {cfg_path}: {e}; {by_hand}")
        return False
    adapters = existing.get("custom_adapters") if isinstance(existing, dict) else None
    if not isinstance(existing, dict) or not (adapters is None or (
            isinstance(adapters, list) and all(isinstance(a, dict) for a in adapters))):
        out.line(f"{cfg_path} is not shaped like an rga config; {by_hand}")
        return False
    cfg, gone = remove_adapters(existing)
    if not gone:
        out.line(f"holds no {PROG} adapter; left untouched")
        return True
    try:
        bak = backup_path(cfg_path)
        shutil.copy(cfg_path, bak)
        out.line(f"backup: {bak}")
        text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        out.line(f"cannot write {cfg_path}: {e}; {by_hand}")
        return False
    out.line(f"removed {', '.join(gone)} (comments from the previous file are not preserved)")
    kept = [a.get("name") for a in cfg["custom_adapters"]]
    out.line(f"adapters left: {', '.join(kept) or '(none)'}")
    return True


def leftovers(out, profile, cache_dir, config_flag=None):
    """What --remove leaves in place, each with the command that deletes it.

    The cache goes through --clear-cache: cache_dir is whatever the profile
    says, the home directory included, and --clear-cache deletes only the
    cache directories in it. The other two paths are our own."""
    out.section("left in place (run what you want gone, in this order)")
    win = sys.platform == "win32"
    rm_dir, rm_file = (("Remove-Item -Recurse -LiteralPath", "Remove-Item -LiteralPath") if win
                       else ("rm -rf --", "rm --"))
    found = False
    cache = os.path.abspath(os.path.expanduser(cache_dir))
    if os.path.isdir(cache):
        found = True
        out.line(f"OCR cache in {cache}: {PROG} --clear-cache all"
                 + (f" --config {quote_path(config_flag)}" if config_flag else ""))
    for label, path, rm in (("profile", profile, rm_file),
                            ("Tesseract language files", paths.tessdata_dir(), rm_dir)):
        if os.path.exists(path):
            found = True
            out.line(f"{label}: {rm} {quote_path(os.path.abspath(path))}")
    if not found:
        out.line("no cache, profile or language files found")
    out.line(f"the package: {uninstall_command()}")


def verify(out, apply, rga_config=None):
    out.section("verify")
    if not shutil.which("rga"):
        out.line("rga not on PATH; skipped")
        return False
    cmd = ["rga"] + ([f"--rga-config-file={rga_config}"] if rga_config else []) + ["--rga-list-adapters"]
    if not apply:
        out.line(" ".join(cmd) + "   # lists the three adapters first once the config is written")
        return True
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    listed = re.findall(r"^ - \*\*(\S+)\*\*", p.stdout, re.M)
    missing = [n for n in ADAPTER_NAMES if n not in listed]
    if missing:
        out.line(f"rga does not list {', '.join(missing)}; inspect {rga_config or paths.rga_config_path()}")
        return False
    out.line("rga lists " + ", ".join(ADAPTER_NAMES))
    return True


# --- driver ----------------------------------------------------------------

class Out:
    def __init__(self):
        self.todos = []
        self.lines = []

    def section(self, title):
        print(f"\n== {title}")

    def line(self, text):
        self.lines.append(text)
        print("  " + text)

    def todo(self, cmd):
        self.todos.append(cmd)
        print("  TODO  " + cmd)


def parse(argv):
    o = {"apply": False, "remove": False, "engine": None, "lang": None, "config": None}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--apply":
            o["apply"] = True
        elif a == "--remove":
            o["remove"] = True
        elif a in ("-h", "--help"):
            print(USAGE, end="")
            raise SystemExit(0)
        elif a.startswith("--engine="):
            o["engine"] = a.split("=", 1)[1]
        elif a == "--engine" and args:
            o["engine"] = args.pop(0)
        elif a.startswith("--lang="):
            o["lang"] = a.split("=", 1)[1]
        elif a == "--lang" and args:
            o["lang"] = args.pop(0)
        elif a.startswith("--config="):
            o["config"] = a.split("=", 1)[1]
        elif a == "--config" and args:
            o["config"] = args.pop(0)
        else:
            sys.stderr.write(USAGE)
            raise SystemExit(2)
    if o["remove"] and (o["apply"] or o["engine"] is not None or o["lang"] is not None):
        sys.stderr.write(f"{PROG} setup: --remove goes with --config only\n")
        raise SystemExit(2)
    return o


def main(argv, config_path, settings_from, rga_config=None):
    """rga_config: the PATH of a --rga-config-file=PATH given before `setup`;
    the entries are then written there and the verification reads it."""
    o = parse(argv)
    if rga_config == "":
        # `--rga-config-file=$UNSET` must not fall through to the real config
        print(f"{PROG}: --rga-config-file= needs a path", file=sys.stderr)
        return 2
    profile = config_path(o["config"])
    st = settings_from(profile)
    if o["remove"]:
        out = Out()
        print(f"{PROG} setup --remove")
        ok = remove_from_rga_config(out, rga_config)
        leftovers(out, profile, st["cache_dir"], o["config"])
        print()
        print(f"{PROG} is out of rga's config" if ok else "not done; see above")
        return 0 if ok else 1
    name = o["engine"] or st["engine"] or "auto"
    langs = engines.parse_langs(o["lang"] if o["lang"] is not None else st["lang"])
    out = Out()
    print(f"{PROG} setup" + (" --apply" if o["apply"] else " (dry run; --apply makes the changes marked TODO where it can)"))
    print(f"  python:  {sys.executable}")
    print(f"  profile: {profile}" + ("" if os.path.exists(profile) else f"  (absent; {PROG} --init-config writes one)"))
    print(f"  cache:   {os.path.expanduser(st['cache_dir'])}")
    ok_tools = check_tools(out)
    ok_engine = check_engine(out, name, langs, o["apply"])
    ok_cfg = check_rga_config(out, o["apply"], rga_config)
    ok_verify = verify(out, o["apply"] and ok_cfg, rga_config)
    print()
    if ok_tools and ok_engine and ok_cfg and (ok_verify or not o["apply"]):
        print("ready" if o["apply"] else "nothing missing; --apply writes the rga config, which plain rga needs")
        return 0
    print(f"{len(out.todos)} item(s) to do" if out.todos else "not ready; see above")
    return 1
