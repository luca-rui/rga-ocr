"""End-to-end tests: the CLI as a subprocess against the fixture tree.

Tests that read the OCR cache populate it themselves, so the module is
order-independent; running it top to bottom still gives a cold first run.
"""
import hashlib
import json
import os
import re
import shutil
import time

import pytest

from conftest import (HERE, IS_WINDOWS, NAMES, NEEDLE, Tool, cache_tag, clean_err, engine_name, grep, rel,
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
    env = {"ADAPTER_SPY_LOG": log}

    def calls():
        try:
            with open(log, encoding="utf-8") as f:
                return [line.split("\t", 1) for line in f.read().splitlines()]
        except FileNotFoundError:
            return []

    cold = t.search(env=env)
    assert cold.code == 0, cold.err
    first = calls()
    assert sorted(mode for mode, _ in first) == ["image", "image", "office", "pdf"], first
    assert any(path.endswith("scan.pdf") for _, path in first), first

    warm = t.search(env=env)
    assert warm.code == 0, warm.err
    # rg prints files in the order its threads finish them
    assert sorted(warm.out.splitlines()) == sorted(cold.out.splitlines())
    assert calls() == first, "the warm run started adapters: %r" % calls()[len(first):]
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

STATUS = r"searching [0-9]+ s · [0-9]+ hits? · [0-9]+ files? OCR'd"
SUMMARY = r"^searched [0-9]+\.[0-9] s · [0-9]+ hits? · [0-9]+ files? OCR'd$"


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
def test_status_line_of_a_no_ocr_run_does_not_claim_ocr(tool):
    code, raw = tool.run_pty("--no-ocr", "--no-cache", NEEDLE, ".")
    assert code == 0
    out = render(raw)
    assert grep(out, r"^searched [0-9]+\.[0-9] s · [0-9]+ hits? · [0-9]+ files? read$"), out
    assert "OCR'd" not in raw.decode("utf-8", "replace")


@pty_only
def test_status_line(tool):
    code, raw = tool.run_pty("--no-cache", NEEDLE, ".")
    assert code == 0
    out = raw.decode("utf-8", "replace").replace("\r", "")
    assert grep(out, STATUS), out
    assert grep(out, r"OCR'd · [^ ]*(photo|shot|scan|rotated|IMG_0001|needle|textlayer|deck|tabelle)"), out
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
    # populate: default cache, a forced one, and an entry under <root>/broken
    assert tool.search().code == 0
    assert tool.run("--force-ocr", NEEDLE, ".").code == 0
    assert tool.run("needle", broken_dir(tool)).code == 0
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
    # the broken-pdf entry sits under <root>/broken, so the common parent is <root>
    parent = os.path.dirname(os.path.realpath(tool.fx))
    folders = re.escape(os.path.join(parent, "{fixtures (")) + r"[0-9]+\), broken \(1\)\}$"
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
