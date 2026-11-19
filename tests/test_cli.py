"""Unit tests for the CLI's own logic: cache removal scope, adapter list,
usage errors, the rga config pass-through to setup. No engine, no rga."""
import json
import os
import re
import sys

import pytest

from rga_ocr import cli
from conftest import NAMES, grep


def make_cache(base, *names):
    for n in names:
        os.makedirs(os.path.join(base, n))
        with open(os.path.join(base, n, "cache.sqlite3"), "wb") as f:
            f.write(b"x" * 1000)


def test_clear_cache_all_removes_only_caches(tmp_path, capsys):
    base = str(tmp_path / "cache")
    make_cache(base, "vision-auto", "none")
    os.makedirs(os.path.join(base, "unrelated"))
    with open(os.path.join(base, "notes.txt"), "w") as f:
        f.write("mine\n")

    assert cli.clear_cache(base, ["all"], dry_run=True) == 0
    out = capsys.readouterr().out
    assert grep(out, r"^would remove 2 cache\(s\) under " + re.escape(base) +
                r" \(0\.0 MB\); left alone: notes\.txt, unrelated$"), out
    assert os.path.isdir(os.path.join(base, "vision-auto"))

    assert cli.clear_cache(base, ["all"]) == 0
    out = capsys.readouterr().out
    assert grep(out, r"^removed 2 cache\(s\) under "), out
    assert sorted(os.listdir(base)) == ["notes.txt", "unrelated"]

    os.remove(os.path.join(base, "notes.txt"))
    os.rmdir(os.path.join(base, "unrelated"))
    assert cli.clear_cache(base, ["all"]) == 0
    out = capsys.readouterr().out
    assert grep(out, "^removed " + re.escape(base) + r" \(0\.0 MB\)$"), out
    assert not os.path.exists(base)


def test_clear_cache_refuses_root_and_home(tmp_path, monkeypatch):
    assert cli.clear_cache(os.path.abspath(os.sep), ["all"]) == 2
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert cli.clear_cache("~", ["all"]) == 2
    assert os.path.isdir(str(tmp_path))


def test_adapter_list_adds_ffmpeg_only_when_configured():
    o = {"ocr": True, "mail": False}
    assert "ffmpeg" not in cli.adapter_list(o, {"adapters_extra": ""})
    assert cli.adapter_list(o, {"adapters_extra": "ffmpeg"})[-1] == "ffmpeg"
    assert cli.adapter_list({"ocr": False, "mail": True}, {"adapters_extra": ""})[-1] == "mail"
    # --no-ocr: PDFs stay with our adapter (text layer only), no image
    # adapter, and never rga's poppler adapter, which needs pdftotext
    lst = cli.adapter_list({"ocr": False, "mail": False}, {"adapters_extra": ""})
    assert lst[:2] == ["ocrpdf", "officexml"]
    assert "ocrimg" not in lst and "poppler" not in lst
    # no duplicates when adapters_extra repeats a base adapter
    lst = cli.adapter_list(o, {"adapters_extra": "zip, ffmpeg"})
    assert lst.count("zip") == 1 and lst[-1] == "ffmpeg"


def test_rga_config_flag():
    assert cli.rga_config_flag([]) is None
    assert cli.rga_config_flag(["--rga-no-cache"]) is None
    assert cli.rga_config_flag(["--rga-no-cache", "--rga-config-file=/x/c.jsonc"]) == "/x/c.jsonc"


@pytest.fixture
def rga_cfg(tmp_path, monkeypatch):
    """rga's config path redirected into tmp_path; the file is absent."""
    path = tmp_path / "rga" / "config.jsonc"
    path.parent.mkdir()
    monkeypatch.setattr(cli.paths, "rga_config_path", lambda: str(path))
    return path


def test_run_config_is_written_when_rga_has_no_config(rga_cfg, tmp_path):
    from rga_ocr import setup_cmd
    got = cli.run_config([], str(tmp_path))
    assert got and os.path.dirname(got) == str(tmp_path)
    with open(got, encoding="utf-8") as f:
        assert json.load(f) == {"custom_adapters": setup_cmd.adapter_entries()}
    assert not rga_cfg.exists()          # rga's own file is never created


def test_run_config_is_not_needed_after_setup(rga_cfg, tmp_path):
    from rga_ocr import setup_cmd
    other = {"name": "mine", "binary": "/bin/cat"}
    # the order among other adapters does not matter, comments are fine
    cfg = {"custom_adapters": [other] + setup_cmd.adapter_entries()}
    rga_cfg.write_text("// by hand\n" + json.dumps(cfg), encoding="utf-8")
    assert cli.run_config([], str(tmp_path)) is None
    assert os.listdir(tmp_path) == ["rga"]


def test_run_config_replaces_entries_of_another_installation(rga_cfg, tmp_path):
    from rga_ocr import setup_cmd
    stale = setup_cmd.adapter_entries(binary="/gone/bin/python")
    other = {"name": "mine", "binary": "/bin/cat"}
    text = json.dumps({"max_archive_recursion": 2, "custom_adapters": stale + [other]})
    rga_cfg.write_text(text, encoding="utf-8")
    got = cli.run_config(["-j", "2"], str(tmp_path))
    with open(got, encoding="utf-8") as f:
        merged = json.load(f)
    assert merged == {"max_archive_recursion": 2,
                      "custom_adapters": setup_cmd.adapter_entries() + [other]}
    assert rga_cfg.read_text(encoding="utf-8") == text


def test_run_config_stays_out_of_the_way(rga_cfg, tmp_path, capsys):
    # the caller's own --rga-config-file wins, whatever rga's config holds
    assert cli.run_config(["--rga-config-file=/x/c.jsonc"], str(tmp_path)) is None
    assert capsys.readouterr().err == ""
    # a config that cannot be read here is left to rga, with a word on why
    # the adapter entries are not put in
    for text in ("{ not json", "[]", '{"custom_adapters": "x"}', '{"custom_adapters": ["x"]}'):
        rga_cfg.write_text(text, encoding="utf-8")
        assert cli.run_config([], str(tmp_path)) is None
        err = capsys.readouterr().err
        assert err.count("\n") == 1 and "cannot read " + str(rga_cfg) in err, err
    assert os.listdir(tmp_path) == ["rga"]


def test_run_config_reads_a_config_with_hash_comments(rga_cfg, tmp_path, capsys):
    # rga accepts "#" comments; the run must still get its adapter entries
    rga_cfg.write_text('# mine\n{"max_archive_recursion": 2, # deep enough\n}\n', encoding="utf-8")
    got = cli.run_config([], str(tmp_path))
    assert got and capsys.readouterr().err == ""
    with open(got, encoding="utf-8") as f:
        assert json.load(f)["max_archive_recursion"] == 2


def test_forget_failed_drops_the_rows_of_failed_files(tmp_path):
    import sqlite3
    if sqlite3.sqlite_version_info < (3, 38):
        pytest.skip("rga's schema needs SQLite 3.38 (strict tables, unixepoch)")
    d = str(tmp_path / "vision-auto")
    held = cli.prepare_cache(d)
    root = os.path.join(os.path.abspath(os.sep), "docs")
    rows = [("ocrpdf", os.path.join(root, "bad.pdf")), ("ocrpdf", os.path.join(root, "good.pdf")),
            ("ocrpdf", os.path.join(root, "bad.pdf2")), ("zip", os.path.join(root, "sub", "box.zip")),
            ("zip", os.path.join(root + "2", "box.zip"))]

    def fill():
        held.execute("delete from preproc_cache")
        for adapter_name, f in rows:
            held.execute("insert into preproc_cache (config_hash, adapter, adapter_version, active_adapters, "
                         "file_path, file_mtime_unix_ms, text_content_zstd) values ('h', ?, 1, 'x', ?, 0, x'00')",
                         (adapter_name, f))
        held.commit()

    def left():
        return [r[0] for r in held.execute("select file_path from preproc_cache order by rowid")]

    # a file on disk: reported with rga's "/./" after the search root
    fill()
    cli.forget_failed(held, [os.path.join(root, ".", "bad.pdf")], root)
    assert left() == [f for _a, f in rows[1:]]
    # an archive member: reported by its inner path, so the archive rows
    # below the search root go, and nothing else
    fill()
    cli.forget_failed(held, [os.path.join("inner", "scan.png")], root)
    assert left() == [f for _a, f in rows[:3] + rows[4:]]
    # the search root is the archive itself
    fill()
    cli.forget_failed(held, ["inner/scan.png"], rows[3][1])
    assert left() == [f for _a, f in rows[:3] + rows[4:]]
    fill()
    cli.forget_failed(held, [], root)
    cli.forget_failed(None, [rows[1][1]], root)
    assert len(left()) == 5
    held.close()
    cli.forget_failed(held, [rows[1][1]], root)   # a closed or broken database costs only the retry


@pytest.mark.parametrize("flag,key,value", [
    ("--snippet", "snippet", "40"), ("--name-blank", "name_blank", "strict"),
    ("--engine", "engine", "tesseract"), ("--lang", "lang", "de-DE,en-US"),
    ("--exclude", "exclude", "a,b"), ("--config", None, "/x/profile"),
])
def test_value_flags_take_both_forms(flag, key, value):
    for argv in ([flag, value, "q", "dir"], [flag + "=" + value, "q", "dir"]):
        o = cli.parse_args(argv)
        assert (o["config"] if key is None else o["flags"][key]) == value, argv
        assert (o["query"], o["root"], o["pass"]) == ("q", "dir", []), argv
    # the value may hold a "=" itself, and may be empty
    assert cli.parse_args(["--exclude=a=b", "q"])["flags"]["exclude"] == "a=b"
    assert cli.parse_args(["--exclude=", "q"])["flags"]["exclude"] == ""


@pytest.mark.parametrize("flag", ["-e", "--regexp", "--type-add", "--type-clear", "--ignore-file", "-g",
                                  "--context-separator", "--maxdepth", "--hostname-bin"])
def test_rg_value_flags_keep_their_value(flag):
    # the value must not turn into the query or the directory
    o = cli.parse_args([flag, "VALUE", "q", "dir"])
    assert (o["query"], o["root"], o["pass"]) == ("q", "dir", [flag, "VALUE"])
    if flag.startswith("--"):
        o = cli.parse_args([flag + "=VALUE", "q", "dir"])
        assert (o["query"], o["root"], o["pass"]) == ("q", "dir", [flag + "=VALUE"])


def test_replace_passes_through_with_json_only():
    for argv in (["--json", "--replace", "X", "q"], ["--replace=X", "--json", "q"]):
        o = cli.parse_args(argv)
        assert o["query"] == "q" and o["pass"][0].startswith("--replace"), argv


@pytest.mark.parametrize("args,msg", [
    (["--snippet"], "--snippet needs a value"),
    (["--replace", "X", "q", "."], "--replace needs --json"),
    (["--replace=X", "q", "."], "--replace needs --json"),
    (["--count=x", "q", "."], "--count is not supported"),
    (["a", "b", "c"], "too many arguments: c"),
    (["-r", "--names-only", "(", "."], "file names are not searched: Python cannot read this regex"),
    (["-l", "x", "."], "-l is not supported: the content pass reads rg's JSON output"),
    (["--files", "."], "--files is not supported"),
])
def test_usage_errors_exit_2(cli, args, msg):
    r = cli.run(*args, cwd=cli.root)
    assert r.code == 2, (r.out, r.err)
    assert r.out == ""
    assert r.err.startswith(NAMES["prog"] + ": " + msg), r.err
    assert "Traceback" not in r.err


def test_prepare_cache(tmp_path):
    from rga_ocr import cli
    import sqlite3
    if sqlite3.sqlite_version_info < (3, 38):
        pytest.skip("rga's schema needs SQLite 3.38 (strict tables, unixepoch)")
    d = str(tmp_path / "vision-auto")
    held = cli.prepare_cache(d)
    assert held is not None
    db = os.path.join(d, "cache.sqlite3")
    assert os.path.isfile(db)
    con = sqlite3.connect(db)
    try:
        assert con.execute("pragma user_version").fetchone()[0] == 3
        assert con.execute("pragma application_id").fetchone()[0] == 924716026
        assert con.execute("pragma journal_mode").fetchone()[0] == "wal"
        cols = [r[1] for r in con.execute("pragma table_info(preproc_cache)")]
        assert cols == ["config_hash", "adapter", "adapter_version", "created_unix_ms",
                        "active_adapters", "file_path", "file_mtime_unix_ms", "text_content_zstd"]
        # a writer gets in while the parent holds its connection
        con.execute("insert into preproc_cache (config_hash, adapter, adapter_version, active_adapters, "
                    "file_path, file_mtime_unix_ms, text_content_zstd) values ('h', 'a', 1, 'x', 'f', 0, x'00')")
        con.commit()
    finally:
        con.close()
    assert len(cli.read_cache_rows(db)) == 1
    assert cli.cache_names(str(tmp_path)) == ["vision-auto"]
    held.close()
    # an existing database is left alone (second call, same schema version)
    held = cli.prepare_cache(d)
    assert held is not None
    held.close()
    assert len(cli.read_cache_rows(db)) == 1


def test_prepare_cache_leaves_existing_database_alone(tmp_path):
    """A database from another ripgrep-all version (other user_version) is
    opened, not re-stamped: rga owns its schema."""
    from rga_ocr import cli
    import sqlite3
    d = str(tmp_path / "vision-auto")
    os.makedirs(d)
    db = os.path.join(d, "cache.sqlite3")
    con = sqlite3.connect(db)
    con.executescript("pragma user_version = 4; create table preproc_cache (x); insert into preproc_cache values (1);")
    con.close()
    before = open(db, "rb").read()
    held = cli.prepare_cache(d)
    assert held is not None
    held.close()
    assert open(db, "rb").read() == before
    con = sqlite3.connect(db)
    assert con.execute("pragma user_version").fetchone()[0] == 4
    assert con.execute("select count(*) from preproc_cache").fetchone()[0] == 1
    con.close()


def test_prepare_cache_keeps_unreadable_existing_file(tmp_path):
    """A cache.sqlite3 that is not a database is left for rga (and the
    user) to deal with, never deleted."""
    from rga_ocr import cli
    d = str(tmp_path / "none")
    os.makedirs(d)
    db = os.path.join(d, "cache.sqlite3")
    with open(db, "wb") as f:
        f.write(b"not a database " * 100)
    assert cli.prepare_cache(d) is None
    assert open(db, "rb").read() == b"not a database " * 100


def test_prepare_cache_unsupported_sqlite(tmp_path, monkeypatch):
    """If this SQLite cannot run rga's schema, no database is left behind
    and rga creates its own."""
    from rga_ocr import cli
    monkeypatch.setattr(cli, "RGA_CACHE_SCHEMA", "create table preproc_cache (x) nonsense;")
    d = str(tmp_path / "none")
    assert cli.prepare_cache(d) is None
    assert os.path.isdir(d)
    assert os.listdir(d) == []


def test_rga_value_flags_reach_rga_in_the_equals_form():
    # rga 0.10.10 rejects "--rga-max-archive-recursion 2"
    o = cli.parse_args(["--rga-max-archive-recursion", "2", "q", "dir"])
    assert (o["query"], o["root"], o["pass"]) == ("q", "dir", ["--rga-max-archive-recursion=2"])
    o = cli.parse_args(["--rga-max-archive-size=2G", "q"])
    assert o["pass"] == ["--rga-max-archive-size=2G"]


@pytest.mark.parametrize("argv, word", [
    (["-rX", "q"], "--replace TEXT"), (["-ir", "q"], "--replace TEXT"), (["-Ur", "X", "q"], "--replace TEXT"),
    (["-il", "q"], "-l (in -il) is not supported"), (["-Uc", "q"], "-c (in -Uc) is not supported"),
    (["--generate", "man", "q"], "--generate is not supported"), (["--generate=man", "q"], "--generate is not supported"),
])
def test_bundled_short_flags_cannot_smuggle_refused_ones(argv, word, capsys):
    with pytest.raises(SystemExit) as e:
        cli.parse_args(argv)
    assert e.value.code == 2
    assert word in capsys.readouterr().err


def test_bundles_and_attached_values_that_are_fine_pass_through():
    for arg in ("-C2", "-j4", "-gr*.txt", "-tr", "-UP", "-M300"):      # an r or l inside a value is no flag
        assert cli.parse_args([arg, "q"])["pass"] == [arg], arg


# ------------------------------------------- profile, environment, engines

def test_profile_hash_starts_a_comment_only_after_a_blank(tmp_path):
    p = tmp_path / "config"
    p.write_text("# a full line\n"
                 "  # an indented one\n"
                 "exclude = build#2, .git   # trailing\n"
                 "engine = tesseract\t# after a tab\n"
                 "lang = de-DE#x\n", encoding="utf-8")
    assert cli.load_profile(str(p)) == {"exclude": "build#2, .git", "engine": "tesseract", "lang": "de-DE#x"}


def test_init_config_leaves_cache_dir_to_the_default(tmp_path):
    p = str(tmp_path / "sub" / "config")
    assert cli.init_config(p) == 0
    vals = cli.load_profile(p)
    assert "cache_dir" not in vals
    assert vals["engine"] == "auto"
    with open(p, encoding="utf-8") as f:
        assert grep(f.read(), r"^# cache_dir = ")
    assert cli.settings_from(p)["cache_dir"] == cli.DEFAULTS["cache_dir"]


def test_lang_takes_commas_and_blanks():
    from rga_ocr import engines
    for value in ("de-DE,en-US", "de-DE en-US", " de-DE ,  en-US\t", "de-DE\nen-US"):
        assert engines.parse_langs(value) == ["de-DE", "en-US"], value
    assert engines.parse_langs("") == [] and engines.parse_langs(None) == []
    assert cli.as_list("my dir, other") == ["my dir", "other"]      # exclude stays comma-only


def test_unknown_environment_variables_are_named_once(monkeypatch, capsys):
    env = {"RGA_OCR_LANGUAGE": "de", "RGA_OCR_ENGINE": "auto", "RGA_OCR_NO_OCR": "1",
           "RGA_OCR_CACHE_DIR": "/x", "RGA_OCR_RENDER_DPI": "150", "RGA_OCRX": "1", "PATH": "/bin"}
    assert cli.unknown_env(env) == ["RGA_OCR_LANGUAGE"]
    for k in [k for k in os.environ if k.startswith("RGA_OCR_")]:
        monkeypatch.delenv(k)
    cli.environment_hints()
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("RGA_OCR_LANGUAGE", "de")
    monkeypatch.setenv("RGA_OCR_ENGIN", "vision")
    cli.environment_hints()
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "RGA_OCR_ENGIN, RGA_OCR_LANGUAGE ignored" in err, err


def test_every_variable_the_source_reads_is_known():
    """INTERNAL_ENV is a hand-kept list; a variable the code starts reading
    without an entry there would be reported to the user as a typo."""
    src = os.path.dirname(cli.__file__)
    read = set()
    for dirpath, _, files in os.walk(src):
        for fn in files:
            if fn.endswith(".py"):
                with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                    text = f.read()
                read |= set(re.findall(r'ENV_PREFIX \+ "([A-Z_]+)"', text))
                read |= set(re.findall(r'_env_num\("([A-Z_]+)"', text))
    assert {"REPORT", "ENGINE", "MIN_TEXT_CHARS"} <= read          # the scan finds something
    known = {k.upper() for k in cli.DEFAULTS} | set(cli.INTERNAL_ENV)
    assert read <= known, sorted(read - known)


class FakeEntryPoint:
    def __init__(self, name):
        self.name = name


def test_engine_plugins_with_unusable_names_are_left_out(monkeypatch, capsys):
    from rga_ocr import engines
    eps = [FakeEntryPoint(n) for n in ("good_one", "my-engine", "Upper", "x2")]
    monkeypatch.setattr(engines, "_entry_points", lambda: eps)
    assert sorted(engines._external()) == ["good_one", "x2"]
    assert engines.rejected_plugins() == ["Upper", "my-engine"]
    assert "my-engine" not in engines.names() and "good_one" in engines.names()
    for k in [k for k in os.environ if k.startswith("RGA_OCR_")]:
        monkeypatch.delenv(k)
    cli.environment_hints()
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "'Upper', 'my-engine' ignored" in err, err


@pytest.mark.parametrize("rows, engine, code, line", [
    ([("vision", "yes", "auto"), ("tesseract", "no", "why")], "auto", 0, None),
    ([("vision", "yes", "auto"), ("tesseract", "no", "why")], "vision", 0, "configured: vision (available)"),
    ([("vision", "yes", "auto"), ("tesseract", "no", "why")], "tesseract", 1, "configured: tesseract (NOT available)"),
    ([("vision", "yes", "auto"), ("tesseract", "no", "why")], "bogus", 1, "configured: bogus (NOT available)"),
    ([("vision", "no", "why"), ("tesseract", "no", "why")], "auto", 1, "configured: auto (no engine available)"),
    ([("vision", "yes", "auto")], "", 0, None),
])
def test_engines_exit_code_says_whether_the_configured_engine_works(monkeypatch, capsys, rows, engine, code, line):
    from rga_ocr import engines
    monkeypatch.setattr(engines, "table", lambda langs: rows)
    assert cli.print_engines({"engine": engine, "lang": ""}) == code
    out = capsys.readouterr().out
    assert ("configured:" in out) == (line is not None), out
    if line:
        assert line in out, out


def test_rga_flags_the_search_sets_itself_are_not_passed_twice():
    # rga takes --rga-cache-path and --rga-accurate only once, and its
    # --rga-no-cache makes every custom adapter fail
    for argv in (["--rga-cache-path", "DIR"], ["--rga-cache-path=DIR"]):
        o = cli.parse_args(argv + ["q", "dir"])
        assert (o["query"], o["root"], o["pass"], o["flags"]) == ("q", "dir", [], {"cache_dir": "DIR"})
    o = cli.parse_args(["--accurate", "--rga-accurate", "--rga-no-cache", "q"])
    assert (o["accurate"], o["no_cache"], o["pass"]) == (True, True, [])
    with pytest.raises(SystemExit):
        cli.parse_args(["q", "--rga-cache-path"])


def test_name_pattern_gives_up_on_a_regex_only_rg_can_read(capsys):
    assert cli.name_pattern(r"\p{Lu}est", True, "nonletter", False, True) is None
    assert "file names are not searched" in capsys.readouterr().err
    assert cli.name_pattern(r"\p{Lu}est", False, "nonletter", False, True).search("a \\p{Lu}est b")


def test_rga_adapters_of_the_caller_are_worked_into_the_list():
    # rga takes the last --rga-adapters only, and the search passes its own
    st = {"adapters_extra": ""}
    base = cli.adapter_list({"ocr": True, "mail": False}, st)
    for argv in (["--rga-adapters=-ocrimg,zip", "q"], ["--rga-adapters", "-ocrimg,zip", "q"]):
        o = cli.parse_args(argv)
        assert o["pass"] == [], argv
        assert cli.adapter_list(o, st) == [a for a in base if a not in ("ocrimg", "zip")]
    o = cli.parse_args(["--rga-adapters=+ffmpeg,zip", "q"])
    assert cli.adapter_list(o, st) == base + ["ffmpeg"]
    o = cli.parse_args(["--rga-adapters=pandoc,ocrpdf", "q"])
    assert cli.adapter_list(o, st) == ["pandoc", "ocrpdf"]


def test_color_flag(capsys):
    assert cli.parse_args(["q"])["color"] == "auto"
    assert cli.parse_args(["--color", "always", "q", "dir"])["color"] == "always"
    o = cli.parse_args(["--color=never", "q"])
    assert (o["color"], o["query"], o["pass"]) == ("never", "q", [])
    with pytest.raises(SystemExit):
        cli.parse_args(["--color", "blue", "q"])
    assert "--color: expected auto, always or never" in capsys.readouterr().err
    assert cli.Printer(False, "always").color is True
    assert cli.Printer(True, "never").color is False
    assert cli.Printer(False).color is False


@pytest.mark.parametrize("argv", [["-o"], ["--heading"], ["-M", "100"], ["--max-columns=100"], ["--vimgrep"]])
def test_rg_formatting_flags_are_named_as_having_no_effect(argv, capsys):
    o = cli.parse_args(argv + ["q", "dir"])
    assert (o["query"], o["root"], o["pass"]) == ("q", "dir", argv)
    assert argv[0].split("=")[0] + " has no effect" in capsys.readouterr().err
    cli.parse_args(["-g", "*.pdf", "q"])
    assert "no effect" not in capsys.readouterr().err


def test_name_event_of_a_name_that_is_not_utf8():
    assert json.loads(cli.name_event("a/ä.txt")) == {"type": "name", "path": "a/ä.txt"}
    # what os.listdir gives on Linux for the bytes b"sch\xf6n.txt"
    name = "sch\udcf6n.txt"
    line = cli.name_event(name)
    line.encode("utf-8")                     # no lone surrogate left
    ev = json.loads(line)
    # Windows encodes the lone surrogate as three bytes, each one replaced
    assert ev["path"] == ("sch���n.txt" if sys.platform == "win32" else "sch�n.txt")
    import base64
    assert base64.b64decode(ev["path_bytes"]) == os.fsencode(name)


def test_setup_after_its_flags_is_a_search_and_says_so(cli):
    r = cli.run("--names-only", "--lang", "en-US", "setup", cwd=cli.root)
    assert r.code == 1 and "Traceback" not in r.err, r.err
    assert 'searching for the word "setup"; the setup command goes first' in r.err, r.err
    r = cli.run("--names-only", "setup", cwd=cli.root)
    assert r.err == "", r.err


def test_output_a_stream_cannot_encode_is_escaped(cli, tmp_path):
    """A file name with a character the output encoding lacks (a C locale,
    a redirect on Windows) must not end the search with a traceback."""
    import subprocess
    (tmp_path / "Kessel-日本.txt").write_text("x\n")
    env = cli.env_with({"PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii"})
    p = subprocess.run([sys.executable, "-m", "rga_ocr.cli", "--names-only", "Kessel", str(tmp_path)],
                       env=env, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert b"Traceback" not in p.stderr, p.stderr
    # a pipe on Windows gets UTF-8 whatever the environment says
    want = "Kessel-日本.txt".encode() if sys.platform == "win32" else b"Kessel-\\u65e5\\u672c.txt"
    assert want in p.stdout, p.stdout


@pytest.mark.skipif(os.name != "posix", reason="directory modes are POSIX")
def test_cache_directories_are_created_for_the_user_only(tmp_path):
    old = os.umask(0o022)
    try:
        d = tmp_path / "shared" / "rga-ocr" / "vision-auto"
        (tmp_path / "shared").mkdir(mode=0o755)
        con = cli.prepare_cache(str(d))
        if con is not None:
            con.close()
        assert (d / "cache.sqlite3").is_file()
        assert oct(d.stat().st_mode & 0o777) == "0o700"
        assert oct(d.parent.stat().st_mode & 0o777) == "0o700"
        # a directory that was there keeps its mode
        assert oct((tmp_path / "shared").stat().st_mode & 0o777) == "0o755"
        cli.private_makedirs(str(tmp_path / "shared"))
        assert oct((tmp_path / "shared").stat().st_mode & 0o777) == "0o755"
    finally:
        os.umask(old)
