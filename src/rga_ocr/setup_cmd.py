"""`rga-ocr setup`: check the machine and wire the adapters into ripgrep-all.

Dry run by default: every section prints what is missing and the command
that fixes it. With --apply the tool does what it can itself (fetch
Tesseract language files, warm the RapidOCR models, merge the adapter
entries into rga's config) and prints the rest for the user to run.

Sections: tools on PATH, the OCR engine, the ripgrep-all config, a
verification, and hints for leftovers from the rga-vision days.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys

from rga_ocr import ENV_PREFIX, LEGACY_ENV_PREFIX, LEGACY_PROG, PROG, engines, paths

REPO_URL = "https://github.com/luca-rui/rga-ocr"
RGA_RELEASES = "https://github.com/phiresky/ripgrep-all/releases/download"

ADAPTER_MODULE = "rga_ocr.adapter"
ADAPTER_ARGS = ["-I", "-X", "utf8", "-m", ADAPTER_MODULE]
ADAPTER_NAMES = ("ocrpdf", "ocrimg", "officexml")
LEGACY_ADAPTER_NAMES = ("visionpdf", "visionimg")

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

Checks the tools on PATH, the OCR engine, and ripgrep-all's config, and
prints what is missing with the command that installs it. --apply fetches
Tesseract language files, warms the RapidOCR models and merges the three
{PROG} adapters into rga's config; the first run keeps a .bak copy, later
runs a timestamped one, and comments in the file are not preserved.
Package installs stay commands for you to run. --engine, --lang and
--config override the profile; --rga-config-file=F targets another rga
config. Exit status: 0 ready, 1 something to do, 2 usage error.
"""

REQUIRED_TOOLS = ("rga", "rg", "pandoc")
OPTIONAL_TOOLS = {"pdftotext": "--no-ocr (PDF text layer through poppler)",
                  "ffmpeg": "the ffmpeg adapter (adapters_extra = ffmpeg)"}


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
    others = missing - {"rga"}
    pkg = {
        "brew": {"rg": "ripgrep", "pandoc": "pandoc", "pdftotext": "poppler", "ffmpeg": "ffmpeg", "rga": "ripgrep-all"},
        "apt-get": {"rg": "ripgrep", "pandoc": "pandoc", "pdftotext": "poppler-utils", "ffmpeg": "ffmpeg"},
        "dnf": {"rg": "ripgrep", "pandoc": "pandoc", "pdftotext": "poppler-utils", "ffmpeg": "ffmpeg"},
        "zypper": {"rg": "ripgrep", "pandoc": "pandoc", "pdftotext": "poppler-tools", "ffmpeg": "ffmpeg"},
        "pacman": {"rg": "ripgrep", "pandoc": "pandoc-cli", "pdftotext": "poppler", "ffmpeg": "ffmpeg", "rga": "ripgrep-all"},
        "choco": {"rg": "ripgrep", "pandoc": "pandoc", "pdftotext": "poppler", "ffmpeg": "ffmpeg", "rga": "ripgrep-all"},
        "winget": {"rg": "BurntSushi.ripgrep.MSVC", "pandoc": "JohnMacFarlane.Pandoc", "ffmpeg": "Gyan.FFmpeg"},
    }
    cmds = []
    if pm == "scoop":
        # the rga manifest depends on ripgrep, pandoc, poppler and ffmpeg
        names = ["rga"] if want_rga else sorted({"rg": "ripgrep", "pandoc": "pandoc", "pdftotext": "poppler",
                                                 "ffmpeg": "ffmpeg"}[t] for t in others)
        if names:
            cmds.append("scoop install " + " ".join(names))
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
    return cmds


def check_tools(out):
    out.section("tools")
    missing = []
    for t in REQUIRED_TOOLS:
        p = shutil.which(t)
        out.line(f"{t:10} {p or 'MISSING'}")
        if not p:
            missing.append(t)
    for t, why in OPTIONAL_TOOLS.items():
        p = shutil.which(t)
        out.line(f"{t:10} {p or 'missing (optional: ' + why + ')'}")
    if missing:
        pm = package_manager()
        if pm:
            for c in install_commands(missing, pm):
                out.todo(c)
        else:
            url = rga_download_url()
            out.todo(f"install {', '.join(missing)} (no package manager found"
                     + (f"; rga: {url}" if "rga" in missing and url else "") + ")")
    return not missing


# --- engine ----------------------------------------------------------------

def under_pipx():
    return "pipx" in os.path.normcase(sys.prefix).split(os.sep)


def extra_install_command(extra):
    spec = f"{PROG}[{extra}] @ git+{REPO_URL}"
    if under_pipx():
        return f'pipx install --force "{spec}"'
    return f'"{sys.executable}" -m pip install "{spec}"'


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
                out.todo(extra_install_command(cls.extra))
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
        out.todo(extra_install_command("rapidocr") + "   # the portable engine")
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
            out.append(c)
            i += 1
    stripped = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(stripped) if stripped.strip() else {}


def adapter_entries(binary=None, args=None):
    """The three custom adapter entries, pointing at this interpreter."""
    binary = binary or sys.executable
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
    """existing (parsed config or {}) with our entries first, legacy
    rga-vision entries dropped, every other custom adapter kept."""
    cfg = dict(existing)
    drop = {e["name"] for e in entries} | set(LEGACY_ADAPTER_NAMES)
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
    return f"{cfg_path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"


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
    legacy = [n for n in before if n in LEGACY_ADAPTER_NAMES]
    out.line(f"adapters now: {', '.join(before) or '(none)'}")
    out.line(f"adapters after: {', '.join(a['name'] for a in merged['custom_adapters'])}")
    out.line(f"adapter command: {sys.executable} {' '.join(ADAPTER_ARGS)} <mode> <file>")
    if legacy:
        out.line(f"legacy entries dropped: {', '.join(legacy)}")
    unchanged = existing.get("custom_adapters") == merged["custom_adapters"]
    if unchanged:
        out.line("up to date")
        return True
    if not apply:
        out.todo(f"{PROG} setup --apply   # writes the entries above; a .bak copy is kept, comments are not")
        return False
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


def verify(out, apply, rga_config=None):
    out.section("verify")
    if not shutil.which("rga"):
        out.line("rga not on PATH; skipped")
        return False
    cmd = ["rga"] + ([f"--rga-config-file={rga_config}"] if rga_config else []) + ["--rga-list-adapters"]
    if not apply:
        out.line(" ".join(cmd) + "   # the three adapters should be listed first")
        return True
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    listed = re.findall(r"^ - \*\*(\S+)\*\*", p.stdout, re.M)
    missing = [n for n in ADAPTER_NAMES if n not in listed]
    if missing:
        out.line(f"rga does not list {', '.join(missing)}; inspect {rga_config or paths.rga_config_path()}")
        return False
    out.line("rga lists " + ", ".join(ADAPTER_NAMES))
    return True


# --- migration -------------------------------------------------------------

def migration_hints(out, profile):
    hints = []
    old_env = sorted(k for k in os.environ if k.startswith(LEGACY_ENV_PREFIX))
    if old_env:
        hints.append(f"{', '.join(old_env)} set; the variables are called {ENV_PREFIX}<KEY> now")
    old_profile = os.path.join(os.path.dirname(os.path.dirname(profile)), LEGACY_PROG, "config")
    if os.path.isfile(old_profile) and not os.path.exists(profile):
        if sys.platform == "win32":
            mv = f'New-Item -ItemType Directory -Force "{os.path.dirname(profile)}"; Move-Item "{old_profile}" "{profile}"'
        else:
            mv = f'mkdir -p "{os.path.dirname(profile)}" && mv "{old_profile}" "{profile}"'
        hints.append(f"move the profile: {mv}")
    old_cache = legacy_cache_dir()
    if old_cache and os.path.isdir(old_cache):
        rm = "Remove-Item -Recurse" if sys.platform == "win32" else "rm -rf"
        hints.append(f"the old cache is no longer read: {rm} \"{old_cache}\"")
    if hints:
        out.section("leftovers from rga-vision")
        for h in hints:
            out.todo(h)


def legacy_cache_dir():
    from platformdirs import PlatformDirs
    return PlatformDirs(LEGACY_PROG, appauthor=False, roaming=True).user_cache_dir


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
    o = {"apply": False, "engine": None, "lang": None, "config": None}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--apply":
            o["apply"] = True
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
    return o


def main(argv, config_path, settings_from, rga_config=None):
    """rga_config: the PATH of a --rga-config-file=PATH given before `setup`;
    the entries are then written there and the verification reads it."""
    o = parse(argv)
    profile = config_path(o["config"])
    st = settings_from(profile)
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
    migration_hints(out, profile)
    print()
    if ok_tools and ok_engine and ok_cfg and (ok_verify or not o["apply"]):
        print("ready" if o["apply"] else "nothing missing; run with --apply to write the rga config")
        return 0
    print(f"{len(out.todos)} item(s) to do" if out.todos else "not ready; see above")
    return 1
