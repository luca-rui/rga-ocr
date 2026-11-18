"""OCR engine registry.

An engine turns a Pillow image into text lines with positions. Each engine
lives in its own module and declares what it needs; the registry answers
"which engines exist", "is this one usable here" and "which one does auto
pick" without importing anything heavy, so the CLI can decide the cache
directory before ripgrep-all starts.

Engine protocol (subclass Engine, module attribute ENGINE = the class):

  name                       "vision" | "winocr" | "rapidocr" | "tesseract" | ...
  modules                    top-level modules the extra installs; installed()
                             checks them with importlib.util.find_spec
  available(langs)           classmethod -> (ok, reason); cheap checks only:
                             platform, importlib.util.find_spec, language data
                             present. Never import the engine or load models.
  lang_tag(langs)            classmethod -> engine-specific language id used in
                             the cache directory name; a pure table lookup
  __init__(langs)            BCP 47 tags, [] = engine default; loads the engine
  recognize(img)             -> list of (top, x, height, text), all but text
                             normalised to 0..1 from the image's top-left

Third-party engines register under the entry-point group "rga_ocr.engines";
the entry point loads to the Engine subclass.
"""

import importlib
import importlib.util
import re
import sys
from importlib.metadata import entry_points

ENTRY_POINT_GROUP = "rga_ocr.engines"

BUILTIN = {
    "vision": "rga_ocr.engines.vision",
    "winocr": "rga_ocr.engines.winocr",
    "rapidocr": "rga_ocr.engines.rapidocr",
    "tesseract": "rga_ocr.engines.tesseract",
}

AUTO_ORDER = {
    "darwin": ["vision", "rapidocr", "tesseract"],
    "win32": ["winocr", "rapidocr", "tesseract"],
}
AUTO_ORDER_DEFAULT = ["rapidocr", "tesseract"]


class EngineError(Exception):
    """No usable engine; the message says what is missing."""


class Engine:
    name = ""
    #: pip extra that installs this engine's Python side (for messages)
    extra = ""
    #: top-level modules that extra provides; installed() checks for them
    modules = ()

    @classmethod
    def installed(cls):
        """True when the engine's Python packages are importable; cheaper
        and narrower than available(), which also checks language data."""
        return module_present(*cls.modules)

    @classmethod
    def available(cls, langs):
        return False, "not implemented"

    @classmethod
    def lang_tag(cls, langs):
        return sanitize(",".join(langs)) if langs else "auto"

    def __init__(self, langs):
        self.langs = list(langs)

    def recognize(self, img):
        raise NotImplementedError


def sanitize(tag):
    """Directory-safe form of a language tag or list."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", tag)


def parse_langs(value):
    """'de-DE, en-US' -> ['de-DE', 'en-US']; None or '' -> []."""
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def module_present(*names):
    """True if every module can be found without importing it."""
    for n in names:
        try:
            if importlib.util.find_spec(n) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def auto_order():
    return AUTO_ORDER.get(sys.platform, AUTO_ORDER_DEFAULT)


def _external():
    """Engines registered by other packages: {name: entry point}."""
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:                      # Python < 3.10 API shape
        eps = entry_points().get(ENTRY_POINT_GROUP, [])
    return {ep.name: ep for ep in eps}


def names():
    """All known engine names: built-in first, then registered ones."""
    out = list(BUILTIN)
    for n in sorted(_external()):
        if n not in out:
            out.append(n)
    return out


def load(name):
    """The Engine subclass for a name; imports its module (light) but not the engine."""
    if name in BUILTIN:
        mod = importlib.import_module(BUILTIN[name])
        return mod.ENGINE
    ep = _external().get(name)
    if ep is None:
        raise EngineError(f"unknown engine {name!r}; known: {', '.join(names())}")
    try:
        cls = ep.load()
    except Exception as e:  # noqa: BLE001 - a broken plugin reports, never tracebacks
        raise EngineError(f"engine plugin {ep.name!r} failed to load: {e.__class__.__name__}: {e}")
    if not (isinstance(cls, type) and issubclass(cls, Engine)):
        raise EngineError(f"engine {name!r} does not provide an Engine class")
    return cls


def resolve(name, langs):
    """The Engine subclass to use: a named one if it is available, or for
    "auto" the first available engine in this platform's order."""
    langs = list(langs)
    if name and name != "auto":
        cls = load(name)
        ok, reason = cls.available(langs)
        if not ok:
            raise EngineError(f"engine {name}: {reason}")
        return cls
    reasons = []
    for n in auto_order():
        cls = load(n)
        ok, reason = cls.available(langs)
        if ok:
            return cls
        reasons.append(f"{n}: {reason}")
    raise EngineError("no OCR engine available (" + "; ".join(reasons) + ")")


def cache_tag(engine_cls, langs, force=False):
    """Cache directory name for an engine and language setting."""
    return f"{engine_cls.name}-{engine_cls.lang_tag(list(langs))}" + ("-force" if force else "")


def parse_cache_tag(name):
    """(engine, lang, force) from a cache directory name."""
    force = name.endswith("-force")
    if force:
        name = name[:-6]
    engine, _, lang = name.partition("-")
    return engine, lang, force


def table(langs):
    """Rows (name, available, note) for every known engine; note is the reason
    when unavailable, 'auto' marks the one auto picks."""
    langs = list(langs)
    rows, picked = [], None
    for n in names():
        try:
            cls = load(n)
            ok, reason = cls.available(langs)
        except Exception as e:  # noqa: BLE001 - a broken plugin must not hide the others
            ok, reason = False, f"{e.__class__.__name__}: {e}"
        if ok and picked is None and n in auto_order():
            picked = n
        rows.append((n, ok, reason))
    out = []
    for n, ok, reason in rows:
        note = "auto" if n == picked else ("" if ok else reason)
        out.append((n, "yes" if ok else "no", note))
    return out
