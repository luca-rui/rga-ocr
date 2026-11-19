"""End-to-end tests: the CLI as a subprocess against the fixture tree.

Tests that read the OCR cache populate it themselves, so the module is
order-independent; running it top to bottom still gives a cold first run.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from conftest import (HERE, IS_WINDOWS, NAMES, NEEDLE, TESSDATA_LANGS, Tool, cache_tag, clean_err, engine_name, grep, rel,
                      spy_config)

P = NAMES["prog"]
E = NAMES["env_prefix"]
def cache_id(name):
    return hashlib.sha1(name.encode()).hexdigest()[:7]


# ------------------------------------------------------------- cold run

def test_cold_run(tool):
    t0 = time.perf_counter()
    r = tool.search()
    dt = time.perf_counter() - t0
    print(f"cold: {dt:.1f}s exit {r.code}")
    out = r.out
    assert r.code == 0, r.err
    assert grep(out, "^" + rel("Angebot_Wartungsvertrag_Kesselanlage_2026.bin") + "$"), out
    assert grep(out, "^" + rel("Ordner Wartungsvertrag Kesselanlage") + "$"), out
    assert grep(out, "^" + rel("notes.txt") + r":2:Angebot Wartungsvertrag Kesselanlage Nord liegt vor\.$"), out
    assert grep(out, "^" + rel("sub", ".hidden", "secret.md") + ":3:"), out
    assert grep(out, "^" + rel("textlayer.pdf") + r":[0-9]+:Page 2:.*Wartungsvertrag Kesselanlage"), out
    assert not grep(out, "^" + rel("textlayer.pdf") + r":[0-9]+:Page 1:"), out
    assert grep(out, "^" + rel("sub", "scan.pdf") + r":[0-9]+:Page 1:.*Wartungsvertrag Kesselanlage"), out
    assert grep(out, "^" + rel("photo.jpg") + ":"), out
    assert grep(out, "^" + rel("IMG_0001.JPG") + ":"), out
    assert grep(out, "^" + rel("sub", "shot.png") + ":"), out
    assert grep(out, "^" + rel("rotated.jpg") + ":"), out
    if os.path.isfile(os.path.join(tool.fx, "shot.heic")):
        assert grep(out, "^" + rel("shot.heic") + ":"), out
    assert grep(out, "^" + rel("vertrag.docx") + ":"), out
    assert grep(out, "^" + rel("tabelle.xlsx") + r":[0-9]+:Page 1:.*Wartungsvertrag Kesselanlage"), out
    assert grep(out, "^" + rel("deck.pptx") + r":[0-9]+:Page 2:.*Wartungsvertrag Kesselanlage"), out
    assert grep(out, "^" + rel("tabelle.ods") + r":[0-9]+:Page 1:.*Wartungsvertrag Kesselanlage West"), out
    assert grep(out, "^" + rel("deck.odp") + r":[0-9]+:Page 2:.*Wartungsvertrag Kesselanlage"), out
    assert not grep(out, "^" + rel("deck.odp") + r":[0-9]+:Page 1:"), out
    for ext in ("tif", "tiff", "webp", "gif", "bmp"):
        if os.path.isfile(os.path.join(tool.fx, "formats", "photo." + ext)):
            assert grep(out, "^" + rel("formats", "photo." + ext) + ":"), out
        else:
            assert ext == "webp", f"fixture formats/photo.{ext} was not written"
    assert grep(out, "^" + rel("bundle.zip") + r":[0-9]+:needle\.jpg: .*Wartungsvertrag Kesselanlage"), out
    # snippet window
    assert grep(out, "^" + rel("deck.pptx") + r":[0-9]+:Page 3: …[^…]*Wartungsvertrag Kesselanlage[^…]*…$"), out
    assert grep(out, "^" + rel("long.txt") + r":2:…[^…]*Mitte Wartungsvertrag Kesselanlage Ende[^…]*…$"), out
    assert not grep(out, "^" + rel("long.txt") + r":2:.{300,}"), out
    # exclusions and decoys
    assert not grep(out, r"\.git" + re.escape(os.sep)), out
    assert not grep(out, "node_modules"), out
    assert not grep(out, r"decoy\.png"), out
    assert not grep(out, r"decoy\.pdf"), out
    assert not grep(out, "^" + rel("Angebot") + r"[^:]*\.bin:"), out
    assert clean_err(r), r.err


# rga's config path redirected to argv[1]: the CLI without --rga-config-file,
# and without touching the config of the user who runs the suite. That only
# moves where the tool looks; blind_rga() below does the same for rga.
# The script also says on stderr whether the run wrote its own config: on
# Windows that line is what tells a run that brought its entries from one
# that found them in a config already on the machine.
NO_SETUP = ("import sys\n"
            "from rga_ocr import cli, paths\n"
            "cfg = sys.argv[1]\n"
            "paths.rga_config_path = lambda: cfg\n"
            "real = cli.run_config\n"
            "def run_config(passed, run_dir):\n"
            "    own = real(passed, run_dir)\n"
            "    print('own-config:', 'yes' if own else 'no', file=sys.stderr)\n"
            "    return own\n"
            "cli.run_config = run_config\n"
            "sys.exit(cli.main(sys.argv[2:]))\n")


def blind_rga(tool, empty):
    """The suite's environment with rga's own config directory moved to an
    empty one, so that a config the user set up cannot make the test pass.
    Not possible on Windows, where rga asks the system for the directory;
    a CI runner has no such config."""
    if IS_WINDOWS:
        return tool.env
    if sys.platform != "darwin":
        return tool.env_with({"XDG_CONFIG_HOME": empty})
    extra = {"HOME": empty}
    if engine_name() == "tesseract" and "TESSDATA_PREFIX" not in os.environ:
        # the language files may sit under the real home directory
        from rga_ocr.engines import tesseract
        found = tesseract.find_tessdata(TESSDATA_LANGS)
        if found:
            extra["TESSDATA_PREFIX"] = found
    return tool.env_with(extra)


def test_search_without_setup(tool, tmp_path):
    """No --rga-config-file and no `setup --apply`: the run brings its own
    adapter entries, and rga's config stays as it was."""
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(os.path.join(tool.fx, "photo.png"), docs)
    empty = tmp_path / "home"
    empty.mkdir()
    env = blind_rga(tool, str(empty))

    def search(cfg):
        cmd = [sys.executable, "-X", "utf8", "-c", NO_SETUP, str(cfg), "--no-cache", NEEDLE, str(docs)]
        p = subprocess.run(cmd, cwd=str(tmp_path), env=env, capture_output=True, timeout=600)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

    absent = tmp_path / "absent.jsonc"
    code, out, err = search(absent)
    assert code == 0 and "photo.png" in out, (code, out, err)
    assert "own-config: yes" in err, err
    assert not absent.exists()

    # entries that point at an interpreter that is gone, next to a foreign adapter
    stale = spy_config()
    for a in stale["custom_adapters"]:
        a["binary"] = str(tmp_path / "gone" / "python")
    stale["custom_adapters"].append({
        "name": "mine", "description": "someone else's", "version": 1, "extensions": ["mine"],
        "mimetypes": [], "binary": sys.executable, "args": ["-c", "pass"],
        "disabled_by_default": True, "match_only_by_mime": False})
    text = json.dumps(stale)
    cfg = tmp_path / "stale.jsonc"
    cfg.write_text(text, encoding="utf-8")
    code, out, err = search(cfg)
    assert code == 0 and "photo.png" in out, (code, out, err)
    assert "own-config: yes" in err, err
    assert cfg.read_text(encoding="utf-8") == text


def test_warm_run(tool, tmp_path):
    """A second run over the same files starts no adapter: every answer
    comes from the cache. Seen through a spy in front of the adapter, on
    one file per adapter and one archive member, with a cache of its own."""
    t = Tool(str(tmp_path / "warm"))
    os.makedirs(t.fx)
    for name in ("photo.png", "tabelle.xlsx", "bundle.zip", os.path.join("sub", "scan.pdf")):
        shutil.copy(os.path.join(tool.fx, name), t.fx)
    with open(t.rga_config, "w", encoding="utf-8") as f:
        json.dump(spy_config(), f, indent=2)
    log = os.path.join(t.root, "adapter-calls")
    os.makedirs(log)
    env = {"ADAPTER_SPY_LOG": log}

    def calls():
        # one file per adapter call, see spy_adapter.py
        found = []
        for name in os.listdir(log):
            with open(os.path.join(log, name), encoding="utf-8") as f:
                found.append(f.read().rstrip("\n").split("\t", 1))
        return sorted(found)

    cold = t.search(env=env)
    assert cold.code == 0, cold.err
    first = calls()
    assert sorted(mode for mode, _ in first) == ["image", "image", "office", "pdf"], first
    assert any(path.endswith("scan.pdf") for _, path in first), first

    warm = t.search(env=env)
    assert warm.code == 0, warm.err
    # rg prints files in the order its threads finish them
    assert sorted(warm.out.splitlines()) == sorted(cold.out.splitlines())
    again = calls()
    assert again == first, "the warm run started adapters: %r" % [c for c in again if c not in first]
    assert clean_err(warm), warm.err


def test_rapidocr_reads_a_non_latin_script(tool, tmp_path):
    """`--lang ru` routes to the Cyrillic model, which rapidocr fetches on
    first use; the default model reads no Cyrillic. The sample is a tracked
    PNG, Pillow's bundled font has no Cyrillic glyphs to draw one with."""
    if engine_name() != "rapidocr":
        pytest.skip("rapidocr only: the other engines pick their script from the language packs installed")
    d = tmp_path / "ru"
    d.mkdir()
    shutil.copy(os.path.join(HERE, "data", "cyrillic.png"), str(d))
    # --no-cache: no rapidocr-cyrillic directory in the cache the other tests list
    r = tool.run("--lang", "ru", "--no-cache", "обслуживание", str(d), cwd=str(tmp_path))
    if r.code != 0 and re.search(r"(?i)download|urlopen|urlerror|connection|timed? ?out|getaddrinfo|"
                                 r"name resolution|max retries|ssl", r.err):
        pytest.skip("Cyrillic model not fetched: " + r.err.strip().splitlines()[-1])
    assert r.code == 0, (r.out, r.err)
    assert grep(r.out, r"cyrillic\.png:1:Договор на обслуживание"), r.out
    assert clean_err(r), r.err


# ------------------------------------------------------------- snippets

def test_full_and_snippet(tool):
    r = tool.run("--full", NEEDLE, ".")
    assert grep(r.out, "^" + rel("long.txt") + r":2:Lorem ipsum.*Kesselanlage.*aliqua\. $"), r.out
    assert "…" not in r.out
    r = tool.run("--snippet", "10", NEEDLE, ".")
    assert grep(r.out, "^" + rel("long.txt") + r":2:…ua\. Mitte Wartungsvertrag Kesselanlage Ende\. Lor…$"), r.out
    r = tool.search(env={E + "SNIPPET": "0"})
    assert "…" not in r.out


# ------------------------------------------------------------- exit codes

def test_no_hit_and_errors(tool):
    assert tool.run("xyzzy_not_there", ".").code == 1
    r = tool.run("--rga-config-file=" + os.path.join(tool.root, "nonexistent"), "xyzzy", ".")
    assert r.code == 2, (r.out, r.err)
    assert tool.run("xyzzy", os.path.join(tool.root, "nonexistent", "path")).code == 2


def test_case_sensitive(tool):
    r = tool.run("-s", "wartungsvertrag kesselanlage", ".")
    assert not grep(r.out, r"notes\.txt"), r.out
    assert r.code == 1
    r = tool.run("-s", NEEDLE, ".")
    assert grep(r.out, r"notes\.txt:2:"), r.out


def test_regex(tool):
    r = tool.run("-r", r"Wartungs\w+[ _]Kessel", ".")
    assert grep(r.out, r"notes\.txt:2:"), r.out
    assert grep(r.out, "^" + rel("Angebot_Wartungsvertrag")), r.out


# ------------------------------------------------------------- name pass

def test_name_blank_modes(tool):
    r = tool.run("--names-only", "Angebot Wartungsvertrag", ".")
    assert "Angebot_Wartungsvertrag" in r.out, r.out
    r = tool.run("--names-only", "Wartungsvertrag Kesselanlage 2026", ".")
    assert "Kesselanlage_2026" in r.out, r.out
    r = tool.run("--names-only", "--name-blank", "strict", "Angebot Wartungsvertrag", ".")
    assert "Angebot_Wartungsvertrag" not in r.out, r.out
    assert r.code == 1
    r = tool.run("--names-only", "--name-blank", "separators", "Angebot Wartungsvertrag", ".")
    assert "Angebot_Wartungsvertrag" in r.out, r.out
    r = tool.run("--names-only", "Wartungsvertrag Kessel anlage", ".")
    assert "Kesselanlage" not in r.out, r.out
    assert r.code == 1
    r = tool.run("--names-only", "--name-blank-optional", "Wartungsvertrag Kessel anlage", ".")
    assert "Angebot_Wartungsvertrag_Kesselanlage" in r.out, r.out


def test_names_only_and_no_names(tool):
    r = tool.run("--names-only", NEEDLE, ".")
    assert "Angebot_Wartungsvertrag" in r.out, r.out
    assert "notes.txt" not in r.out, r.out
    r = tool.run("--no-names", NEEDLE, ".")
    assert not grep(r.out, "^" + rel("Angebot_Wartungsvertrag_Kesselanlage_2026.bin") + "$"), r.out
    assert "notes.txt" in r.out, r.out


def test_rg_value_flags_pass_through(tool):
    # -e adds a pattern for the content pass; its value is not the DIR
    r = tool.run("--no-names", "-e", "Termin offen", "kein-treffer-xyz", "notes.txt")
    assert r.code == 0 and "Termin offen" in r.out, (r.out, r.err)
    r = tool.run("--no-names", "--type-add", "notiz:*.txt", "-t", "notiz", NEEDLE, ".")
    assert r.code == 0 and grep(r.out, "^" + rel("notes.txt") + ":2:"), (r.out, r.err)
    assert ".pdf" not in r.out, r.out
    r = tool.run("--no-names", "--json", "--replace", "ERSETZT", NEEDLE, "notes.txt")
    events = [json.loads(l) for l in r.out.splitlines()]
    subs = [m for e in events if e["type"] == "match" for m in e["data"]["submatches"]]
    assert subs and all(m["replacement"]["text"] == "ERSETZT" for m in subs), r.out


# ------------------------------------------------------------- OCR switches

def test_no_ocr(tool):
    # the text layer comes from the ocrpdf adapter, which joins the lines of
    # a paragraph: the phrase wrapped across two lines matches here too
    r = tool.run("--no-ocr", NEEDLE, ".")
    assert grep(r.out, r"textlayer\.pdf:[0-9]+:Page 2:.*Wartungsvertrag Kesselanlage"), r.out
    assert "scan.pdf" not in r.out, r.out
    assert "photo.jpg" not in r.out, r.out
    assert os.path.isdir(os.path.join(tool.cache, "none"))
    # --no-ocr wins over --force-ocr; --no-cache, so the adapter runs again
    r = tool.run("--no-ocr", "--force-ocr", "--no-cache", NEEDLE, ".")
    assert grep(r.out, r"textlayer\.pdf:[0-9]+:Page 2:"), r.out
    assert "scan.pdf" not in r.out, r.out


def test_no_ocr_set_in_the_environment_does_not_reach_an_ocr_run(tool):
    # an exported RGA_OCR_NO_OCR would otherwise cache scans as empty text
    # under the engine's cache directory
    r = tool.run("--no-cache", NEEDLE, ".", env={"RGA_OCR_NO_OCR": "1"})
    assert grep(r.out, "^" + rel("sub", "scan.pdf") + ":"), r.out


def test_force_ocr(tool):
    t0 = time.perf_counter()
    r = tool.run("--force-ocr", NEEDLE, ".")
    print(f"force cold: {time.perf_counter() - t0:.1f}s")
    assert grep(r.out, r"textlayer\.pdf:[0-9]+:Page 2:"), r.out
    assert grep(r.out, r"scan\.pdf:"), r.out
    assert os.path.isdir(os.path.join(tool.cache, cache_tag(force=True)))
    # the page has a text layer: forced, its OCR text comes after the layer,
    # so the needle is found twice there and once without the flag

    def hits(out):
        return len(re.findall(r"(?m)^.*textlayer\.pdf:[0-9]+:Page 2:", out))
    plain = tool.run(NEEDLE, ".")
    assert hits(plain.out) == 1, plain.out
    assert hits(r.out) > hits(plain.out), r.out


def test_lang(tool):
    r = tool.run("--lang", "de-DE,en-US", NEEDLE, "sub")
    assert grep(r.out, r"scan\.pdf:"), r.out
    assert os.path.isdir(os.path.join(tool.cache, cache_tag("de-DE,en-US")))


# ------------------------------------------------------------- json

def test_json(tool):
    r = tool.run("--json", NEEDLE, ".")
    lines = [l for l in r.out.splitlines() if l.strip()]
    events = [json.loads(l) for l in lines]
    assert len(events) > 5
    name = {"type": "name", "path": "." + os.sep + "Angebot_Wartungsvertrag_Kesselanlage_2026.bin"}
    assert name in events, lines
    assert any(e.get("type") == "match" for e in events)
    # name hits first, also on a pipe, where Python buffers its own text
    kinds = [e.get("type") == "name" for e in events]
    assert kinds == sorted(kinds, reverse=True), [e.get("type") for e in events]
    assert grep(r.out, r'"text":"Lorem ipsum.*Mitte Wartungsvertrag Kesselanlage Ende'), r.out
    assert "…" not in r.out


# ------------------------------------------------------------- excludes

def test_exclude(tool):
    git_obj = re.escape(os.path.join(".git", "objects", "x"))
    r = tool.run("--no-exclude", "--no-names", NEEDLE, ".")
    assert grep(r.out, git_obj), r.out
    r = tool.run("--exclude", "node_modules", "--no-names", NEEDLE, ".")
    assert grep(r.out, git_obj), r.out
    assert "node_modules" not in r.out, r.out


# ------------------------------------------------------------- status line

STATUS = r"searching [0-9]+ s · [0-9]+ hits? · [0-9]+ files? read"
SUMMARY = r"^searched [0-9]+\.[0-9] s · [0-9]+ hits? · [0-9]+ files? read$"


def strip_status(raw):
    """Drop every status-line redraw; keep what a pipe would have seen."""
    text = raw.decode("utf-8", "replace")
    return re.sub(r"\r\x1b\[K[^\r\n]*", "", text).replace("\r\n", "\n")


def render(raw):
    """What a terminal shows: a carriage return overwrites the line."""
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    return re.sub(r"[^\n]*\r", "", text).replace("\x1b[K", "")


pty_only = pytest.mark.skipif(IS_WINDOWS, reason="pty-based check")


@pty_only
def test_status_line_does_not_claim_ocr(tool):
    # the count takes in text files and PDFs with a text layer as well
    for flags in (["--no-ocr"], []):
        code, raw = tool.run_pty(*flags, "--no-cache", NEEDLE, ".")
        assert code == 0
        assert grep(render(raw), SUMMARY), render(raw)
        assert "OCR'd" not in raw.decode("utf-8", "replace")


@pty_only
def test_status_line(tool):
    code, raw = tool.run_pty("--no-cache", NEEDLE, ".")
    assert code == 0
    out = raw.decode("utf-8", "replace").replace("\r", "")
    assert grep(out, STATUS), out
    assert grep(out, r"read · [^ ]*(photo|shot|scan|rotated|IMG_0001|needle|textlayer|deck|tabelle)"), out
    out = strip_status(raw)
    assert grep(out, r"^1:Page 1: .*Wartungsvertrag Kesselanlage.*Seite eins$"), out
    assert grep(out, r"^# names$"), out
    assert not grep(out, r"searching [0-9]+ s"), out
    out = render(raw)
    assert grep(out, SUMMARY), out
    r = tool.search()
    assert not grep(r.err, "^searched "), r.err


@pty_only
def test_progress_switches(tool):
    code, raw = tool.run_pty("--no-cache", "--no-progress", NEEDLE, ".")
    out = raw.decode("utf-8", "replace").replace("\r", "")
    assert not grep(out, r"searching [0-9]+ s"), out
    assert not grep(out, "^searched "), out
    assert "Page 1: Scan:" in out or grep(out, r"Page 1: .*Wartungsvertrag Kesselanlage"), out
    try:
        with open(tool.profile, "w", encoding="utf-8") as f:
            f.write("progress = false\n")
        code, raw = tool.run_pty("--no-cache", NEEDLE, ".")
        out = raw.decode("utf-8", "replace").replace("\r", "")
        assert not grep(out, r"searching [0-9]+ s"), out
        code, raw = tool.run_pty("--no-cache", NEEDLE, ".", env={E + "PROGRESS": "true"})
        out = raw.decode("utf-8", "replace").replace("\r", "")
        assert grep(out, r"searching [0-9]+ s"), out
    finally:
        os.remove(tool.profile)


def test_transparent_image_is_read(tool, tmp_path):
    """Dark text on a transparent background, through the real engine."""
    import make_fixtures
    d = tmp_path / "alpha"
    d.mkdir()
    from PIL import Image
    ink = make_fixtures.text_image("Wartungsvertrag Kesselanlage").convert("L").point(lambda v: 255 if v < 128 else 0)
    img = Image.new("RGBA", ink.size, (0, 0, 0, 0))
    img.putalpha(ink)                                   # black everywhere, opaque where the text is
    img.save(str(d / "clear.png"))
    # --no-cache: a folder outside the fixture tree must not show in the shared cache
    r = tool.run("--no-cache", "Kesselanlage", str(d))
    assert r.code == 0 and grep(r.out, r"clear\.png:1:.*Kesselanlage"), (r.out, r.err)


# ------------------------------------------------------------- adapter errors

def broken_dir(tool):
    d = os.path.join(tool.root, "broken")
    if not os.path.isdir(d):
        os.makedirs(d)
        with open(os.path.join(d, "broken.pdf"), "w") as f:
            f.write("this is not a pdf\n")
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("needle here\n")
    return d


def test_adapter_error_forwarded(tool):
    r = tool.run("needle", broken_dir(tool))
    assert r.code == 0, (r.out, r.err)
    assert grep(r.err, "^" + re.escape(P) + r": adapter pdf failed on broken\.pdf: "), r.err
    assert grep(r.out, r"a\.txt:1:needle here"), r.out


def test_rga_flags_the_search_sets_itself(tool, tmp_path):
    """rga takes --rga-cache-path and --rga-accurate only once and its
    --rga-no-cache breaks custom adapters; the search sets all three."""
    own = str(tmp_path / "own-cache")
    for flags in (["--rga-cache-path", own], ["--rga-cache-path=" + own, "--accurate", "--rga-accurate"],
                  ["--rga-no-cache"]):
        r = tool.search(*flags)
        assert r.code == 0 and grep(r.out, r"photo\.png"), (flags, r.out, r.err)
        assert not grep(r.err, "provided more than once|preprocessor command failed"), (flags, r.err)
    # a directory per engine and language, as below cache_dir
    assert [d for d in os.listdir(own) if os.path.isfile(os.path.join(own, d, "cache.sqlite3"))], os.listdir(own)


def test_regex_only_rg_can_read_still_searches_the_contents(tool):
    r = tool.run("-r", r"\p{Lu}artungsvertrag", tool.fx)
    assert r.code == 0 and grep(r.out, r"photo\.png"), (r.out, r.err)
    assert grep(r.err, "^" + re.escape(P) + ": file names are not searched: "), r.err
    r = tool.run("-r", "--names-only", r"\p{Lu}", tool.fx)
    assert r.code == 2 and r.out == "", (r.out, r.err)


def test_engine_failure_is_not_cached(tool, tmp_path):
    """While the OCR engine fails (a model download without network), files
    produce no text. That must not stay in the cache: once the engine works,
    the same search finds them, on disk and inside an archive."""
    t = Tool(str(tmp_path / "down"))
    os.makedirs(t.fx)
    for name in ("photo.png", "bundle.zip"):
        shutil.copy(os.path.join(tool.fx, name), t.fx)
    with open(os.path.join(t.fx, "broken.pdf"), "w") as f:
        f.write("this is not a pdf\n")
    cfg = spy_config()
    for a in cfg["custom_adapters"]:
        a["args"] = [os.path.join(HERE, "failing_engine_adapter.py") if x.endswith("spy_adapter.py") else x
                     for x in a["args"]]
    with open(t.rga_config, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    down = os.path.join(t.root, "engine-down")
    env = {"ADAPTER_ENGINE_DOWN": down}
    failed = "^" + re.escape(P) + r": adapter image failed on photo\.png: OSError: model fetch failed \(not cached"
    unreadable = "^" + re.escape(P) + r": adapter pdf failed on broken\.pdf: "
    open(down, "w").close()
    member = "^" + re.escape(P) + r": adapter image failed on needle\.jpg: OSError: model fetch failed \(not cached"
    for run in range(2):                     # the second run does not answer from the cache
        r = t.search(env=env)
        # not "no hit" (1): files went unread
        assert r.code == 2, (r.code, r.err)
        assert not grep(r.out, r"photo\.png|needle\.jpg"), r.out
        assert grep(r.err, failed) and grep(r.err, member), r.err
        # a file that cannot be opened is reported once, then cached as empty
        assert bool(grep(r.err, unreadable)) == (run == 0), r.err
    os.remove(down)
    r = t.search(env=env)
    assert r.code == 0, (r.code, r.err)
    assert grep(r.out, r"^(\.[/\\])?photo\.png:"), (r.out, r.err)
    assert grep(r.out, r"^(\.[/\\])?bundle\.zip:"), (r.out, r.err)
    assert not grep(r.err, "model fetch failed"), r.err
    assert not grep(r.err, unreadable), r.err


# ------------------------------------------------------------- profile

def test_profile(tool):
    try:
        r = tool.run("--init-config")
        assert grep(r.out, "^wrote " + re.escape(tool.profile) + "$"), r.out
        assert os.path.isfile(tool.profile)
        r = tool.run("--init-config")
        assert grep(r.out, "^profile exists"), r.out
        r = tool.run("wartungsvertrag kesselanlage", ".")
        assert grep(r.out, r"notes\.txt:2:"), r.out
        with open(tool.profile, "w", encoding="utf-8") as f:
            f.write("case = sensitive\nexclude = node_modules\nname_blank = strict\nsnippet = 0\nbogus = 1\n")
        r = tool.run("wartungsvertrag kesselanlage", ".")
        assert r.code == 1, r.out
        assert "unknown key 'bogus'" in r.err, r.err
        r = tool.search()
        assert grep(r.out, re.escape(os.path.join(".git", "objects", "x"))), r.out
        assert not grep(r.out, "^" + rel("Angebot_Wartungsvertrag")), r.out
        assert grep(r.out, "^" + rel("long.txt") + ":2:Lorem ipsum"), r.out
        r = tool.run("wartungsvertrag kesselanlage", ".", env={E + "CASE": "insensitive"})
        assert grep(r.out, r"notes\.txt:2:"), r.out
        r = tool.run("-i", "wartungsvertrag kesselanlage", ".", env={E + "CASE": "sensitive"})
        assert grep(r.out, r"notes\.txt:2:"), r.out
        r = tool.run("--names-only", "Angebot Wartungsvertrag", ".", env={E + "NAME_BLANK": "nonletter"})
        assert "Angebot_Wartungsvertrag" in r.out, r.out
    finally:
        if os.path.exists(tool.profile):
            os.remove(tool.profile)


# ------------------------------------------------------------- cache

def test_cache_info_and_clear(tool):
    # populate: default cache, a forced one, and an entry under <root>/extra
    # (a file whose adapter run failed leaves no entry)
    assert tool.search().code == 0
    assert tool.run("--force-ocr", NEEDLE, ".").code == 0
    assert tool.run("needle", broken_dir(tool)).code == 0
    extra = os.path.join(tool.root, "extra")
    os.makedirs(extra, exist_ok=True)
    shutil.copy(os.path.join(tool.fx, "textlayer.pdf"), extra)
    assert tool.run(NEEDLE, extra).code == 0
    auto, force = cache_tag(), cache_tag(force=True)
    id_auto, id_force = cache_id(auto), cache_id(force)
    lang_auto = re.escape(auto[len(engine_name()) + 1:])      # the LANG column
    assert os.path.isdir(os.path.join(tool.cache, auto))

    r = tool.run("--cache-info")
    assert r.code == 0, r.err
    out = r.out
    assert grep(out, "^cache_dir: " + re.escape(os.path.abspath(tool.cache)) + "$"), out
    assert grep(out, r"^CACHE-ID +ENGINE +LANG +FORCE +ENTRIES +SIZE +LAST ADDED +FOLDERS$"), out
    row = "^" + id_auto + " +" + engine_name() + " +" + lang_auto + " +no "
    assert grep(out, row + r"+[1-9][0-9]* +[0-9]+\.[0-9] MB  20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}  "), out
    # the extra entry sits under <root>/extra, so the common parent is <root>
    parent = os.path.dirname(os.path.realpath(tool.fx))
    folders = re.escape(os.path.join(parent, "{fixtures (")) + r"[0-9]+\), (broken \(1\), )?extra \(1\)\}$"
    assert grep(out, "^" + id_auto + " .*  " + folders), out
    assert grep(out, "^" + id_force + " +" + engine_name() + " +" + lang_auto + r" +yes +[1-9][0-9]* +"), out

    r = tool.run("--clear-cache", id_force)
    assert r.code == 0, r.err
    assert grep(r.out, "^removed " + re.escape(force) + r" \([0-9]+\.[0-9] MB\)$"), r.out
    assert not os.path.exists(os.path.join(tool.cache, force))
    assert os.path.isdir(os.path.join(tool.cache, auto))

    r = tool.run("--clear-cache", "nope")
    assert r.code == 2
    assert "no cache with cache-id or directory 'nope'" in r.out + r.err

    r = tool.run("--dry-run", "--clear-cache", id_auto)
    assert r.code == 0, r.err
    assert grep(r.out, "^would remove " + re.escape(auto) + r" \([0-9]+\.[0-9] MB\)$"), r.out
    assert os.path.isdir(os.path.join(tool.cache, auto))

    r = tool.run("--clear-cache")
    assert r.code == 2
    both = r.out + r.err
    assert grep(both, row), both
    assert "nothing removed; give cache-ids, directory names, or 'all'" in both, both
    assert os.path.isdir(os.path.join(tool.cache, auto))

    cache_re = re.escape(tool.cache)
    r = tool.run("--clear-cache", "all", "--dry-run")
    assert r.code == 0, r.err
    assert grep(r.out, "^would remove " + cache_re + r" \([0-9]+\.[0-9] MB\)$"), r.out
    assert os.path.isdir(os.path.join(tool.cache, auto))

    r = tool.run("--clear-cache", "all")
    assert r.code == 0, r.err
    assert grep(r.out, row), r.out
    assert grep(r.out, "^removed " + cache_re + r" \([0-9]+\.[0-9] MB\)$"), r.out
    assert not os.path.exists(tool.cache)
    r = tool.run("--clear-cache", "all")
    assert grep(r.out, "^no cache at "), r.out
    r = tool.run("--cache-info")
    assert grep(r.out, "^no cache at "), r.out

    r = tool.run("--clear-cache", "all", env={E + "CACHE_DIR": os.path.abspath(os.sep)})
    assert r.code == 2, (r.out, r.err)

    r = tool.search()
    assert grep(r.out, r"Page 1: .*Wartungsvertrag Kesselanlage"), r.out


def test_clear_cache_all_keeps_foreign_files(tool, tmp_path):
    base = str(tmp_path / "cache")
    env = {E + "CACHE_DIR": base}
    assert tool.search(env=env).code == 0
    auto = cache_tag()
    assert os.path.isdir(os.path.join(base, auto))
    foreign = os.path.join(base, "notes.txt")
    with open(foreign, "w") as f:
        f.write("mine\n")
    r = tool.run("--clear-cache", "all", "--dry-run", env=env)
    assert r.code == 0, r.err
    assert grep(r.out, r"^would remove 1 cache\(s\) under " + re.escape(base) +
                r" \([0-9]+\.[0-9] MB\); left alone: notes\.txt$"), r.out
    assert os.path.isdir(os.path.join(base, auto))
    r = tool.run("--clear-cache", "all", env=env)
    assert r.code == 0, r.err
    assert grep(r.out, r"^removed 1 cache\(s\) under " + re.escape(base) + r" .*left alone: notes\.txt$"), r.out
    assert not os.path.exists(os.path.join(base, auto))
    assert os.path.exists(foreign)
    os.remove(foreign)
    r = tool.run("--clear-cache", "all", env=env)
    assert r.code == 0, r.err
    assert grep(r.out, "^removed " + re.escape(base) + r" \(0\.0 MB\)$"), r.out
    assert not os.path.exists(base)


# ------------------------------------------------------------- engines

def test_engines(tool):
    r = tool.run("--engines")
    assert r.code == 0, r.err
    assert grep(r.out, r"^ENGINE +AVAILABLE +NOTE"), r.out
    assert grep(r.out, "^" + engine_name() + r" +yes"), r.out
    for n in ("vision", "winocr", "rapidocr", "tesseract"):
        assert grep(r.out, "^" + n + r" +(yes|no)"), r.out
    assert grep(r.out, r"^[a-z0-9_-]+ +yes +auto$"), r.out        # the auto pick is marked
    r = tool.run("--engine", "bogus", NEEDLE, ".")
    assert r.code == 2, (r.out, r.err)
    assert "unknown engine 'bogus'" in r.err, r.err
    # the exit code of --engines answers "does my configured engine work here"
    r = tool.run("--engines", "--engine", "bogus")
    assert r.code == 1, (r.out, r.err)
    assert grep(r.out, r"^configured: bogus \(NOT available\)$"), r.out
    r = tool.run("--engine", "bogus", "--no-ocr", "Kesselanlage", ".")
    assert r.code in (0, 1), r.err                                  # no engine needed
    assert "unknown engine" not in r.err
    # blanks around a name mean the same to --engines and to the search
    r = tool.run("--engines", env={"RGA_OCR_ENGINE": " bogus "})
    assert r.code == 1 and grep(r.out, r"^configured: bogus \(NOT available\)$"), (r.out, r.err)
    r = tool.run(NEEDLE, ".", env={"RGA_OCR_ENGINE": " bogus "})
    assert r.code == 2 and "unknown engine 'bogus'" in r.err, r.err


def test_misspelt_environment_variable_gets_one_warning(tool):
    # the CLI warns once per run; the adapter never does (it does not
    # import the CLI, and rg drops a preprocessor's stderr anyway)
    r = tool.run(NEEDLE, ".", env={"RGA_OCR_LANGUAGE": "de-DE"})
    assert r.code == 0, r.err
    assert grep(r.out, "^" + rel("textlayer.pdf") + ":"), r.out
    assert r.err.count("RGA_OCR_LANGUAGE ignored: no such setting") == 1, r.err
    assert len(r.err.strip().splitlines()) == 1, r.err
    r = tool.run("setup", "--help", env={"RGA_OCR_LANGUAGE": "de-DE"})
    assert r.err.count("RGA_OCR_LANGUAGE ignored: no such setting") == 1, r.err


# ------------------------------------------------------------- output and stopping

def test_color_always_on_a_pipe(tool):
    r = tool.run("--no-names", NEEDLE, "notes.txt")
    assert r.code == 0 and "\x1b[" not in r.out, r.out
    # the suite sets NO_COLOR; an explicit flag wins over it
    r = tool.run("--color", "always", "--no-names", NEEDLE, "notes.txt")
    assert r.code == 0 and grep(r.out, "\x1b\\[[0-9;]*m" + NEEDLE.split()[0]), repr(r.out)
    r = tool.run("--color=always", "--json", "--no-names", NEEDLE, "notes.txt")
    assert "\x1b[" not in r.out, r.out


def test_caller_can_take_an_adapter_out(tool):
    r = tool.run("--no-names", "--rga-adapters=-" + NAMES["adapters"]["image"], NEEDLE, ".")
    assert r.code == 0 and clean_err(r), r.err
    assert grep(r.out, "^" + rel("notes.txt") + ":") and not grep(r.out, r"photo\.png"), r.out


@pytest.mark.skipif(sys.platform != "linux", reason="file names are bytes on Linux only")
def test_file_name_that_is_not_utf8(tool, tmp_path):
    import base64
    raw = os.fsencode(str(tmp_path)) + b"/Kesselanlage-sch\xf6n.txt"
    with open(raw, "w") as f:
        f.write("x\n")
    p = subprocess.run(tool.argv(["--names-only", "Kesselanlage", str(tmp_path)]), env=tool.env,
                       capture_output=True, timeout=60)
    assert p.returncode == 0 and b"Traceback" not in p.stderr, p.stderr
    assert b"Kesselanlage-sch\xf6n.txt" in p.stdout, p.stdout
    p = subprocess.run(tool.argv(["--json", "--names-only", "Kesselanlage", str(tmp_path)]), env=tool.env,
                       capture_output=True, timeout=60)
    ev = json.loads(p.stdout.decode("utf-8"))
    assert base64.b64decode(ev["path_bytes"]) == raw, ev


posix_only = pytest.mark.skipif(IS_WINDOWS, reason="signals and process groups")


def wait_for(cond, seconds, what):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        got = cond()
        if got:
            return got
        time.sleep(0.1)
    pytest.fail("timed out: " + what, pytrace=False)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SlowSearch:
    """A search whose adapter sleeps for a minute, started and left running:
    what stops it early must also stop rga, rg and the adapter."""

    def __init__(self, tool, tmp_path):
        t = Tool(str(tmp_path / "slow"))
        os.makedirs(t.fx)
        shutil.copy(os.path.join(tool.fx, "photo.png"), t.fx)
        cfg = spy_config()
        for a in cfg["custom_adapters"]:
            a["args"] = [os.path.join(HERE, "slow_adapter.py") if x.endswith("spy_adapter.py") else x
                         for x in a["args"]]
        with open(t.rga_config, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        self.pids = str(tmp_path / "pids")
        self.scratch = str(tmp_path / "scratch")
        os.makedirs(self.pids)
        os.makedirs(self.scratch)
        env = t.env_with({"ADAPTER_PIDS": self.pids, "TMPDIR": self.scratch})
        self.proc = subprocess.Popen(t.argv(["--no-cache", NEEDLE, "."]), cwd=t.fx, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.adapter = int(wait_for(lambda: os.listdir(self.pids), 60, "the adapter did not start")[0])
        except BaseException:
            self.proc.kill()
            raise

    def ended(self):
        """Exit status within 20 s (the adapter alone would take 60), with
        the adapter gone and the scratch directory removed."""
        try:
            code = self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            pytest.fail("the search went on", pytrace=False)
        wait_for(lambda: not alive(self.adapter), 10, "the adapter still runs")
        assert os.listdir(self.scratch) == [], os.listdir(self.scratch)
        return code


@posix_only
def test_sigterm_stops_the_whole_search(tool, tmp_path):
    import signal
    s = SlowSearch(tool, tmp_path)
    s.proc.send_signal(signal.SIGTERM)
    assert s.ended() == 128 + signal.SIGTERM


@posix_only
def test_search_stops_when_the_reader_of_its_output_leaves(tool, tmp_path):
    # `rga-ocr ... | head -1`: without a further hit nothing is written, so
    # no write fails; the closed pipe has to be noticed another way
    s = SlowSearch(tool, tmp_path)
    s.proc.stdout.close()
    assert s.ended() == 0


@posix_only
def test_rga_killed_by_a_signal_is_not_a_no_hit(tool, tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    rga = fake / "rga"
    rga.write_text("#!/bin/sh\nkill -KILL $$\n")
    rga.chmod(0o755)
    r = tool.run("--no-names", NEEDLE, ".", env={"PATH": str(fake) + os.pathsep + os.environ["PATH"]})
    assert r.code == 2, (r.code, r.err)
    assert grep(r.err, "^" + re.escape(P) + ": rga was stopped by signal 9; the search is incomplete$"), r.err
