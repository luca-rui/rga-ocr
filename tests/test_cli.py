"""Unit tests for the CLI's own logic: cache removal scope, adapter list,
usage errors, the rga config pass-through to setup. No engine, no rga."""
import os
import re

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
    (["-r", "(", "."], "bad regex for the name pass"),
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
    # rga 0.10.10 rejects "--rga-cache-path DIR"
    o = cli.parse_args(["--rga-cache-path", "DIR", "q", "dir"])
    assert (o["query"], o["root"], o["pass"]) == ("q", "dir", ["--rga-cache-path=DIR"])
    o = cli.parse_args(["--rga-adapters=+mail", "q"])
    assert o["pass"] == ["--rga-adapters=+mail"]


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
