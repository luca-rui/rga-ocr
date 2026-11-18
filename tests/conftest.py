"""Shared fixtures for the end-to-end suite.

The suite runs the CLI as a subprocess against its own fixture tree, rga
config, cache directory and profile, so the user's setup stays untouched.
Everything tied to the program name lives in NAMES; a rename changes that
dict and nothing else.

The end-to-end tests (fixture `tool`) need rga, rg and pandoc on PATH and
an OCR engine that works on this machine (Apple Vision needs a GUI
session); the unit tests and the `cli` fixture run without them.
"""
import functools
import os
import re
import shutil
import subprocess
import sys
from collections import namedtuple

import pytest

from rga_ocr import engines

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

NAMES = {
    "prog": "rga-ocr",
    "env_prefix": "RGA_OCR_",
    # the CLI as a subprocess argv prefix (the installed package, not the checkout)
    "cli": [sys.executable, "-X", "utf8", "-m", "rga_ocr.cli"],
    # what the rga config's custom adapters run: binary plus leading args
    "adapter_binary": sys.executable,
    "adapter_args": ["-I", "-X", "utf8", "-m", "rga_ocr.adapter"],
    "adapters": {"pdf": "ocrpdf", "image": "ocrimg", "office": "officexml"},
    "pdf_hint": ".txt.asciipagebreaks",
}

NEEDLE = "Wartungsvertrag Kesselanlage"
REQUIRED_TOOLS = ("rga", "rg", "pandoc")
IS_WINDOWS = sys.platform == "win32"

# The engine under test: RGA_OCR_ENGINE in the environment (CI sets it per
# leg) or what auto picks on this machine.
ENGINE = os.environ.get(NAMES["env_prefix"] + "ENGINE", "").strip() or "auto"
TESSDATA_LANGS = ("eng", "deu")


@functools.lru_cache(maxsize=None)
def engine_cls():
    """The Engine class under test; resolved on first use so that collecting
    the unit tests never needs a working engine."""
    return engines.load(ENGINE) if ENGINE != "auto" else engines.resolve("auto", [])


def engine_name():
    return engine_cls().name


def cache_tag(lang=None, force=False):
    """Name of the cache directory the CLI uses for a language setting."""
    return engines.cache_tag(engine_cls(), engines.parse_langs(lang), force)


def rel(*parts):
    """Regex for a hit path as the CLI prints it, relative to the search root."""
    return re.escape("." + os.sep + os.sep.join(parts))


def grep(text, pattern):
    return re.search(pattern, text, re.M) is not None


Result = namedtuple("Result", "code out err")


def clean_err(r):
    """True when stderr holds nothing the program itself complained about:
    no line of its own (`rga-ocr: ...`), no traceback, no error line from
    rga or rg. Anything else on stderr (a library's notice, a download
    progress line) is not this suite's business."""
    return not re.search(r"(?im)^(?:%s:|Traceback \(most recent call last\)|error\b)"
                         % re.escape(NAMES["prog"]), r.err)


def spy_config():
    """The suite's rga config with every adapter behind tests/spy_adapter.py,
    which logs each call to a file in the directory named by ADAPTER_SPY_LOG."""
    cfg = rga_config()
    spy = os.path.join(HERE, "spy_adapter.py")
    for a in cfg["custom_adapters"]:
        a["args"] = ["-I", "-X", "utf8", spy] + a["args"][-2:]
    return cfg


IMAGE_EXT = ["jpg", "jpeg", "png", "heic", "heif", "tif", "tiff", "webp", "gif", "bmp"]
IMAGE_MIME = ["image/jpeg", "image/png", "image/heic", "image/heif", "image/tiff",
              "image/webp", "image/gif", "image/bmp"]
OFFICE_EXT = ["xlsx", "pptx", "ods", "odp"]
OFFICE_MIME = ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "application/vnd.oasis.opendocument.spreadsheet",
               "application/vnd.oasis.opendocument.presentation"]


def rga_config():
    """The custom adapter entries the suite installs into its own rga config."""
    def entry(name, mode, ext, mime, hint):
        return {"name": name, "description": f"{NAMES['prog']} {mode} adapter (test)",
                "version": 1, "extensions": ext, "mimetypes": mime,
                "binary": NAMES["adapter_binary"],
                "args": NAMES["adapter_args"] + [mode, "${input_virtual_path}"],
                "disabled_by_default": False, "match_only_by_mime": False,
                "output_path_hint": "${input_virtual_path}" + hint}
    a = NAMES["adapters"]
    return {"custom_adapters": [
        entry(a["pdf"], "pdf", ["pdf"], ["application/pdf"], NAMES["pdf_hint"]),
        entry(a["image"], "image", IMAGE_EXT, IMAGE_MIME, ".txt"),
        entry(a["office"], "office", OFFICE_EXT, OFFICE_MIME, ".txt.asciipagebreaks"),
    ]}


class Tool:
    """The CLI under test, bound to one temp root."""

    def __init__(self, root):
        self.root = root
        self.fx = os.path.join(root, "fixtures")
        self.cache = os.path.join(root, "cache")
        self.cfgdir = os.path.join(root, "config")
        self.profile = os.path.join(self.cfgdir, "config")
        self.rga_config = os.path.join(root, "rga-config.json")
        os.makedirs(self.cfgdir)
        import json
        with open(self.rga_config, "w", encoding="utf-8") as f:
            json.dump(rga_config(), f, indent=2)
        # drop every RGA_* variable: the tool's own and legacy ones it would warn about
        env = {k: v for k, v in os.environ.items() if not k.startswith("RGA_")}
        env[NAMES["env_prefix"] + "ENGINE"] = ENGINE
        env[NAMES["env_prefix"] + "CACHE_DIR"] = self.cache
        env[NAMES["env_prefix"] + "CONFIG"] = self.profile   # absent unless a test writes it
        env["NO_COLOR"] = "1"
        env["PYTHONUTF8"] = "1"
        self.env = env

    def env_with(self, extra=None):
        env = dict(self.env)
        for k, v in (extra or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    def argv(self, args):
        return NAMES["cli"] + ["--rga-config-file=" + self.rga_config] + list(args)

    def run(self, *args, env=None, cwd=None, timeout=600):
        p = subprocess.run(self.argv(args), cwd=cwd or self.fx, env=self.env_with(env),
                           capture_output=True, timeout=timeout)
        # Windows text-mode stdout writes \r\n; the assertions anchor on \n
        return Result(p.returncode, p.stdout.decode("utf-8", "replace").replace("\r\n", "\n"),
                      p.stderr.decode("utf-8", "replace").replace("\r\n", "\n"))

    def run_pty(self, *args, env=None, cwd=None, timeout=600):
        """Run with stdout and stderr on a pseudo-terminal; returns the raw bytes."""
        out = os.path.join(self.root, "pty.txt")
        cmd = [sys.executable, "-I", os.path.join(HERE, "ptyrun.py"), out] + self.argv(args)
        p = subprocess.run(cmd, cwd=cwd or self.fx, env=self.env_with(env), timeout=timeout)
        with open(out, "rb") as f:
            return p.returncode, f.read()

    def search(self, *args, **kw):
        return self.run(*args, NEEDLE, ".", **kw)


def ensure_tessdata(tmp_root):
    """The tesseract leg needs eng and deu traineddata. Use TESSDATA_PREFIX or
    the tool's data dir when they hold them, else fetch them into the temp
    root and point TESSDATA_PREFIX there for the whole session."""
    from rga_ocr.engines import tesseract as t
    if t.find_tessdata(TESSDATA_LANGS):
        return
    import urllib.request
    d = os.path.join(tmp_root, "tessdata")
    os.makedirs(d, exist_ok=True)
    for code in TESSDATA_LANGS:
        url = t.DOWNLOAD_BASE + code + ".traineddata"
        try:
            # URLError and timeouts are OSErrors; urlretrieve has no timeout
            with urllib.request.urlopen(url, timeout=60) as resp, \
                    open(os.path.join(d, code + ".traineddata"), "wb") as f:
                shutil.copyfileobj(resp, f)
        except OSError as e:
            reason = f"tesseract language file {code} not here and not fetched from {url}: {e}"
            if os.environ.get("CI"):
                # a CI leg that ran nothing must not be green
                pytest.fail(reason, pytrace=False)
            pytest.skip(reason + "; set TESSDATA_PREFIX to a directory that holds "
                        + ", ".join(c + ".traineddata" for c in TESSDATA_LANGS))
    os.environ["TESSDATA_PREFIX"] = d


@pytest.fixture(scope="session")
def cli(tmp_path_factory):
    """The CLI bound to a temp root, without fixtures, toolchain or engine:
    for argument parsing, help and setup's dry paths."""
    return Tool(str(tmp_path_factory.mktemp("cli")))


@pytest.fixture(scope="session")
def tool(tmp_path_factory):
    """Fixture tree, rga config, cache and profile dir in one temp root.
    Warms the OCR engine once with a throwaway cache so the real cold run
    sees a ready engine (no model download in its stderr)."""
    missing = [t for t in REQUIRED_TOOLS if not shutil.which(t)]
    if missing:
        pytest.fail(f"missing on PATH: {', '.join(missing)}", pytrace=False)
    root = str(tmp_path_factory.mktemp("e2e"))
    try:
        cls = engine_cls()
    except engines.EngineError as e:
        pytest.fail(str(e), pytrace=False)
    if cls.name == "tesseract":
        ensure_tessdata(root)
    ok, reason = cls.available([])
    assert ok, f"engine {cls.name} not usable here: {reason}"
    t = Tool(root)
    # a subprocess keeps pypdfium2 and Pillow out of the pytest process
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "make_fixtures.py"), t.fx], check=True)
    warm = os.path.join(root, "warm")
    os.makedirs(warm)
    shutil.copy(os.path.join(t.fx, "photo.png"), warm)
    r = t.run("--no-cache", NEEDLE, warm, cwd=root)
    assert r.code == 0, f"engine warm-up failed (exit {r.code}):\n{r.out}\n{r.err}"
    return t
