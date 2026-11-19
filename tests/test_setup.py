"""Unit tests for `rga-ocr setup`: the JSONC parser, the config merge and
the install-command table. No tools, no network."""
import json
import os
import re
import shutil
import sys
from types import SimpleNamespace

import pytest

from rga_ocr import setup_cmd as sc
from conftest import NAMES

JSONC = """\
// rga default config
{
  /* block comment, with a "quoted" string inside */
  "custom_adapters": [
    {
      "name": "other", "binary": "/opt/bin/other-adapter", "args": ["pdf", "${input_virtual_path}"],
      "description": "slash // inside a string stays",
    },
    {"name": "mine", "binary": "/usr/bin/true", "args": [],},
  ],
  "max_archive_recursion": 4,
}
"""


def test_load_jsonc_strips_comments_and_trailing_commas():
    cfg = sc.load_jsonc(JSONC)
    assert cfg["max_archive_recursion"] == 4
    names = [a["name"] for a in cfg["custom_adapters"]]
    assert names == ["other", "mine"]
    assert cfg["custom_adapters"][0]["description"] == "slash // inside a string stays"
    assert sc.load_jsonc("") == {}
    assert sc.load_jsonc("// only a comment\n") == {}


def test_load_jsonc_trailing_commas_only_outside_strings():
    assert sc.load_jsonc('{"a": ",}", "b": [",]", ", ]"]}') == {"a": ",}", "b": [",]", ", ]"]}
    assert sc.load_jsonc('{"a": [1, 2, // last\n ], /* done */ }') == {"a": [1, 2]}
    assert sc.load_jsonc('{"a": {"b": [[1,],],},}') == {"a": {"b": [[1]]}}
    assert sc.load_jsonc('{"a": "x\\\\",}') == {"a": "x\\"}
    for bad in ("[1,,]", "[,]", '{"a": 1,, }'):
        with pytest.raises(ValueError):
            sc.load_jsonc(bad)


def test_merge_keeps_foreign_entries():
    cfg = sc.load_jsonc(JSONC)
    merged = sc.merge_config(cfg, sc.adapter_entries())
    names = [a["name"] for a in merged["custom_adapters"]]
    assert names == ["ocrpdf", "ocrimg", "officexml", "other", "mine"]
    assert merged["max_archive_recursion"] == 4
    assert [a["name"] for a in cfg["custom_adapters"]] == ["other", "mine"]      # input untouched
    # idempotent
    again = sc.merge_config(merged, sc.adapter_entries())
    assert again == merged
    json.dumps(merged)                                            # serialisable


def test_adapter_entries_match_the_suite_and_the_interpreter():
    entries = sc.adapter_entries()
    assert [e["name"] for e in entries] == list(NAMES["adapters"].values())
    for e in entries:
        assert e["binary"] == sys.executable == NAMES["adapter_binary"]
        assert e["args"][:-2] == NAMES["adapter_args"]
        assert e["args"][-1] == "${input_virtual_path}"
        assert e["output_path_hint"].startswith("${input_virtual_path}.txt")
    assert entries[0]["output_path_hint"].endswith(NAMES["pdf_hint"])


@pytest.mark.parametrize("pm,missing,expect", [
    ("brew", ["rga", "pandoc"], ["brew install pandoc ripgrep-all"]),
    ("apt-get", ["rg"], ["sudo apt-get install ripgrep"]),
    ("scoop", ["rga", "rg"], ["scoop install rga"]),
    ("scoop", ["pandoc"], ["scoop install pandoc"]),
    ("choco", ["rga"], ["choco install ripgrep-all"]),
])
def test_install_commands(pm, missing, expect):
    assert sc.install_commands(missing, pm) == expect


def test_install_commands_fall_back_to_the_release_archive(monkeypatch):
    monkeypatch.setattr(sc.sys, "platform", "linux")
    monkeypatch.setattr(sc.platform, "machine", lambda: "x86_64")
    cmds = sc.install_commands(["rga", "rg"], "apt-get")
    assert cmds[0] == "sudo apt-get install ripgrep"
    assert "x86_64-unknown-linux-musl.tar.gz" in cmds[1]
    monkeypatch.setattr(sc.platform, "machine", lambda: "aarch64")
    assert "aarch64-unknown-linux-gnu" in sc.rga_download_url()
    monkeypatch.setattr(sc.sys, "platform", "win32")
    assert sc.rga_download_url().endswith("x86_64-pc-windows-msvc.zip")


def test_extra_install_command_names_the_pypi_package(monkeypatch):
    monkeypatch.setattr(sc, "under_pipx", lambda: True)
    assert sc.extra_install_command("rapidocr") == 'pipx install --force "rga-ocr[rapidocr]"'
    monkeypatch.setattr(sc, "under_pipx", lambda: False)
    monkeypatch.setattr(sc, "under_uv_tool", lambda: False)
    monkeypatch.setattr(sc, "under_homebrew", lambda: False)
    monkeypatch.setattr(sc.sys, "platform", "linux")            # the Windows form has its own test
    assert sc.extra_install_command("vision") == f'"{sys.executable}" -m pip install "rga-ocr[vision]"'
    assert sc.uninstall_command() == f'"{sys.executable}" -m pip uninstall rga-ocr'
    monkeypatch.setattr(sc, "under_uv_tool", lambda: True)
    assert sc.extra_install_command("tesseract") == 'uv tool install --force "rga-ocr[tesseract]"'
    assert sc.uninstall_command() == "uv tool uninstall rga-ocr"
    monkeypatch.setattr(sc, "under_pipx", lambda: True)
    assert sc.uninstall_command() == "pipx uninstall rga-ocr"   # pipx is asked first


def test_pip_commands_run_in_powershell_and_cmd(monkeypatch):
    monkeypatch.setattr(sc, "under_pipx", lambda: False)
    monkeypatch.setattr(sc, "under_uv_tool", lambda: False)
    monkeypatch.setattr(sc, "under_homebrew", lambda: False)
    monkeypatch.setattr(sc.sys, "platform", "win32")
    monkeypatch.setattr(sc.sys, "executable", r"C:\venvs\x\Scripts\python.exe")
    assert sc.uninstall_command() == r"C:\venvs\x\Scripts\python.exe -m pip uninstall rga-ocr"
    # a quoted path at the start of a line is an expression in PowerShell
    monkeypatch.setattr(sc.sys, "executable", r"C:\Program Files\Py's\python.exe")
    assert sc.extra_install_command("winocr") == (
        r"& 'C:\Program Files\Py''s\python.exe' -m pip install " + '"rga-ocr[winocr]"')


@pytest.mark.skipif(os.sep != "/", reason="Homebrew paths")
def test_homebrew_environment_gets_the_opt_path(monkeypatch, tmp_path):
    cellar = tmp_path / "Cellar" / "rga-ocr" / "0.2.1" / "libexec"
    (cellar / "bin").mkdir(parents=True)
    (cellar / "bin" / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(sc.sys, "prefix", str(cellar))
    monkeypatch.setattr(sc.sys, "executable", str(cellar / "bin" / "python"))
    opt = tmp_path / "opt" / "rga-ocr"
    stable = str(opt / "libexec" / "bin" / "python")
    assert sc.under_homebrew()
    assert sc.adapter_python() == str(cellar / "bin" / "python")    # no opt link yet
    opt.parent.mkdir()
    opt.symlink_to(cellar.parent)
    assert sc.adapter_python() == stable
    assert all(e["binary"] == stable for e in sc.adapter_entries())
    assert sc.uninstall_command() == "brew uninstall rga-ocr"
    hint = sc.extra_install_command("tesseract")
    assert hint == 'pipx install "rga-ocr[tesseract]" && brew uninstall rga-ocr && rga-ocr setup --apply'
    # pasted into zsh, which has no comments at the prompt by default,
    # nothing in the line may run on its own
    assert not set("#`;") & set(hint)
    out = sc.Out()
    sc.todo_extra(out, "rapidocr", "   # the portable engine")
    assert out.todos == [sc.extra_install_command("rapidocr")] and "vision engine only" in out.lines[0]
    # started through the opt link, the prefix is the stable one already
    monkeypatch.setattr(sc.sys, "prefix", str(opt / "libexec"))
    monkeypatch.setattr(sc.sys, "executable", stable)
    assert sc.under_homebrew() and sc.adapter_python() == stable
    # the same directory names elsewhere are no Homebrew
    for other in (tmp_path / "x" / "libexec", tmp_path / "opt" / "tool" / "libexec",
                  tmp_path / "venvs" / "rga-ocr"):
        monkeypatch.setattr(sc.sys, "prefix", str(other))
        assert not sc.under_homebrew()
        assert sc.adapter_python() == stable                        # falls back to sys.executable


def test_printed_paths_are_literal_words(monkeypatch):
    monkeypatch.setattr(sc.sys, "platform", "linux")
    assert sc.quote_path("/a/b") == "/a/b"
    assert sc.quote_path('/a b/$HOME"`x') == """'/a b/$HOME"`x'"""
    monkeypatch.setattr(sc.sys, "platform", "win32")
    assert sc.quote_path(r"D:\Cache [old]\it's") == r"'D:\Cache [old]\it''s'"


def test_uv_tool_environment_is_recognised(monkeypatch, tmp_path):
    env = tmp_path / "share" / "uv" / "tools" / "rga-ocr"
    env.mkdir(parents=True)
    monkeypatch.setattr(sc.sys, "prefix", str(env))
    assert sc.under_uv_tool()                                   # by its place under uv/tools
    moved = tmp_path / "elsewhere" / "rga-ocr"                  # UV_TOOL_DIR set
    moved.mkdir(parents=True)
    monkeypatch.setattr(sc.sys, "prefix", str(moved))
    assert not sc.under_uv_tool()
    (moved / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    assert sc.under_uv_tool()                                   # by uv's receipt
    monkeypatch.setattr(sc.sys, "prefix", str(tmp_path / "venvs" / "tools" / "x"))
    assert not sc.under_uv_tool()


class Rec(sc.Out):
    def section(self, title):
        self.lines.append("== " + title)


def fake_which(present):
    return lambda t: ("/bin/" + t) if t in present else None


@pytest.mark.parametrize("version, word, is_warning", [
    (sc.RGA_TESTED, "ripgrep-all " + ".".join(map(str, sc.RGA_TESTED)), False),
    ((0, 11, 0), "ripgrep-all 0.11.0", False),
    ((0, 9, 6), "ripgrep-all 0.9.6 is older than", True),
    (None, "gave no version number", True),
])
def test_check_tools_reports_the_rga_version_without_failing(monkeypatch, capsys, version, word, is_warning):
    monkeypatch.setattr(sc.shutil, "which", fake_which({"rga", "rga-preproc", "rg", "pandoc"}))
    monkeypatch.setattr(sc, "rga_version", lambda: version)
    out = Rec()
    assert sc.check_tools(out) is True                 # an old rga warns, it is no TODO
    assert out.todos == []
    assert any(word in ln for ln in out.lines), out.lines
    assert any("tested with" in ln for ln in out.lines) == is_warning, out.lines
    capsys.readouterr()


def test_rga_version_reads_the_real_binary_and_survives_a_missing_one():
    assert sc.rga_version("no-such-rga-binary") is None
    if shutil.which("rga"):
        v = sc.rga_version()
        assert v is not None and len(v) == 3, v        # any release: an old one only warns


@pytest.mark.parametrize("stdout, code, want", [
    ("ripgrep-all 0.10.10\n", 0, (0, 10, 10)),
    ("rga 0.10.9\r\n", 0, (0, 10, 9)),
    ("built with rustc 1.84.0\nripgrep-all 0.9.6\n", 0, (0, 9, 6)),     # not the first number in sight
    ("ripgrep-all 0.10.10\n", 1, None),
    ("ripgrep-all 0.10\n", 0, None),
    ("", 0, None),
])
def test_rga_version_reads_the_line_that_names_the_program(monkeypatch, stdout, code, want):
    import subprocess
    monkeypatch.setattr(sc.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, ""))
    assert sc.rga_version() == want


def test_check_tools_wants_rga_preproc(monkeypatch, capsys):
    monkeypatch.setattr(sc.shutil, "which", fake_which({"rga", "rg", "pandoc", "brew"}))
    monkeypatch.setattr(sc, "rga_version", lambda: sc.RGA_TESTED)
    monkeypatch.setattr(sc, "package_manager", lambda: "brew")
    out = Rec()
    assert sc.check_tools(out) is False
    assert out.todos == [sc.PREPROC_HINT], out.todos   # no "brew install" for a tool that has no package
    monkeypatch.setattr(sc, "package_manager", lambda: None)
    out = Rec()
    assert sc.check_tools(out) is False
    assert out.todos == [sc.PREPROC_HINT], out.todos
    # scoop has no package for it either, and must still say what to do
    assert sc.install_commands(["rga-preproc"], "scoop") == [sc.PREPROC_HINT]
    assert sc.install_commands(["rga", "rga-preproc"], "scoop") == ["scoop install rga"]
    # with rga missing too, installing rga covers it
    assert sc.install_commands(["rga", "rga-preproc"], "brew") == ["brew install ripgrep-all"]
    capsys.readouterr()


def test_remove_takes_our_adapters_out_and_keeps_the_rest(tmp_path, capsys):
    cfg_path = str(tmp_path / "rga" / "config.jsonc")
    os.makedirs(os.path.dirname(cfg_path))
    merged = sc.merge_config(sc.load_jsonc(JSONC), sc.adapter_entries())
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(merged, f)
    before = open(cfg_path, encoding="utf-8").read()

    out = Rec()
    assert sc.remove_from_rga_config(out, cfg_path) is True
    after = json.load(open(cfg_path, encoding="utf-8"))
    assert [a["name"] for a in after["custom_adapters"]] == ["other", "mine"]
    assert after["max_archive_recursion"] == 4
    assert open(cfg_path + ".bak", encoding="utf-8").read() == before
    assert any(ln.startswith("removed ocrpdf, ocrimg, officexml") for ln in out.lines), out.lines

    # a second run finds nothing and writes nothing
    stamp = os.stat(cfg_path).st_mtime_ns
    out = Rec()
    assert sc.remove_from_rga_config(out, cfg_path) is True
    assert os.stat(cfg_path).st_mtime_ns == stamp
    assert sorted(os.listdir(os.path.dirname(cfg_path))) == ["config.jsonc", "config.jsonc.bak"]
    assert any("left untouched" in ln for ln in out.lines), out.lines

    capsys.readouterr()


def test_remove_refuses_what_it_cannot_do_safely(tmp_path, monkeypatch, capsys):
    # a path somebody typed and that is not there: a typo, not "done"
    out = Rec()
    assert sc.remove_from_rga_config(out, str(tmp_path / "absent.jsonc")) is False
    assert any("no such file" in ln for ln in out.lines), out.lines
    # rga's own default config that was never written: nothing to do
    monkeypatch.setattr(sc.paths, "rga_config_path", lambda: str(tmp_path / "default.jsonc"))
    out = Rec()
    assert sc.remove_from_rga_config(out) is True
    for text in ("{ not json", "[1, 2]", "null", '{"custom_adapters": ["ocrimg"]}',
                 '{"custom_adapters": {"name": "ocrimg"}}'):
        odd = str(tmp_path / "odd.jsonc")
        with open(odd, "w", encoding="utf-8") as f:
            f.write(text)
        out = Rec()
        assert sc.remove_from_rga_config(out, odd) is False, text
        assert any("by hand" in ln for ln in out.lines), (text, out.lines)
        assert open(odd, encoding="utf-8").read() == text
    assert os.listdir(tmp_path) == ["odd.jsonc"]                # no backup of a file left alone
    capsys.readouterr()


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs a read-only file")
def test_remove_reports_a_config_it_cannot_write(tmp_path, capsys):
    cfg_path = str(tmp_path / "config.jsonc")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"custom_adapters": sc.adapter_entries()}, f)
    before = open(cfg_path, encoding="utf-8").read()
    os.chmod(cfg_path, 0o444)
    out = Rec()
    assert sc.remove_from_rga_config(out, cfg_path) is False
    assert any(ln.startswith("cannot write") for ln in out.lines), out.lines
    assert open(cfg_path, encoding="utf-8").read() == before
    capsys.readouterr()


def test_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    cfg_path = str(tmp_path / "config.jsonc")
    seen = []
    for _ in range(4):
        b = sc.backup_path(cfg_path)
        assert b not in seen
        seen.append(b)
        open(b, "w").close()
    assert seen[0] == cfg_path + ".bak"


def test_leftovers_never_print_a_recursive_delete_of_the_cache_dir(tmp_path, monkeypatch, capsys):
    """cache_dir is the user's word: it can be the home directory or /."""
    profile = tmp_path / "pro file"
    profile.write_text("", encoding="utf-8")
    monkeypatch.setattr(sc.sys, "platform", "linux")            # the commands asserted below are the POSIX ones
    monkeypatch.setattr(sc.paths, "tessdata_dir", lambda: str(tmp_path / "tess data"))
    (tmp_path / "tess data").mkdir()
    for cache_dir in ("~", "/", str(tmp_path), "."):
        out = Rec()
        sc.leftovers(out, str(profile), cache_dir, str(profile))
        cache_lines = [ln for ln in out.lines if ln.startswith("OCR cache")]
        assert len(cache_lines) == 1 and "rm " not in cache_lines[0], out.lines
        assert cache_lines[0].endswith(f"rga-ocr --clear-cache all --config '{profile}'"), cache_lines
        assert f"profile: rm -- '{profile}'" in out.lines, out.lines
        assert f"Tesseract language files: rm -rf -- '{tmp_path / 'tess data'}'" in out.lines, out.lines
    out = Rec()
    sc.leftovers(out, str(profile), str(tmp_path / "no-cache-here"))
    assert not any(ln.startswith("OCR cache") for ln in out.lines)
    capsys.readouterr()


def test_setup_remove_end_to_end_deletes_nothing_but_the_entries(cli, tmp_path):
    import subprocess
    cfg = str(tmp_path / "other.jsonc")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(sc.merge_config({"custom_adapters": [{"name": "mine", "binary": "/usr/bin/true", "args": []}]},
                                  sc.adapter_entries()), f)
    profile = tmp_path / "profile"
    cache = tmp_path / "cache"
    (cache / "vision-auto").mkdir(parents=True)
    profile.write_text(f"cache_dir = {cache}\n", encoding="utf-8")

    env = {k: v for k, v in cli.env.items() if k != NAMES["env_prefix"] + "CACHE_DIR"}   # the profile names it

    def run(*args):
        return subprocess.run(NAMES["cli"] + ["--rga-config-file=" + cfg, "setup", *args], cwd=cli.root,
                              env=env, capture_output=True, text=True, encoding="utf-8")
    p = run("--remove", "--config", str(profile))
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert [a["name"] for a in json.load(open(cfg, encoding="utf-8"))["custom_adapters"]] == ["mine"]
    assert os.path.isfile(cfg + ".bak")
    assert profile.exists() and (cache / "vision-auto").is_dir()        # printed, not deleted
    quoted = sc.quote_path(str(profile))                        # per platform, as the code prints it
    assert f"OCR cache in {cache}: rga-ocr --clear-cache all --config {quoted}" in p.stdout, p.stdout
    rm = "Remove-Item -LiteralPath" if sys.platform == "win32" else "rm --"
    assert f"profile: {rm} {quoted}" in p.stdout, p.stdout
    assert "uninstall rga-ocr" in p.stdout, p.stdout
    # the printed cache command works and takes only the cache directories
    (cache / "vision-auto" / "cache.sqlite3").write_bytes(b"")
    (cache / "mine.txt").write_text("keep", encoding="utf-8")
    c = subprocess.run(NAMES["cli"] + ["--clear-cache", "all", "--config", str(profile)], cwd=cli.root,
                       env=env, capture_output=True, text=True, encoding="utf-8")
    assert c.returncode == 0, (c.stdout, c.stderr)
    assert not (cache / "vision-auto").exists() and (cache / "mine.txt").exists()
    # an empty path (`--rga-config-file=$UNSET`) must not reach the real config
    e = subprocess.run(NAMES["cli"] + ["--rga-config-file=", "setup", "--remove"], cwd=cli.root,
                       env=env, capture_output=True, text=True, encoding="utf-8")
    assert e.returncode == 2 and "--rga-config-file= needs a path" in e.stderr, (e.stdout, e.stderr)
    p = run("--remove", "--config", str(profile))
    assert p.returncode == 0 and "left untouched" in p.stdout, p.stdout
    other = subprocess.run(NAMES["cli"] + ["--rga-config-file=" + cfg + ".typo", "setup", "--remove"],
                           cwd=cli.root, env=env, capture_output=True, text=True, encoding="utf-8")
    assert other.returncode == 1 and "no such file" in other.stdout, other.stdout
    for bad in (["--remove", "--apply"], ["--remove", "--engine", "vision"], ["--remove", "--lang=de"]):
        p = run(*bad)
        assert p.returncode == 2 and "--remove goes with --config only" in p.stderr, (bad, p.stderr)


def test_setup_help_and_bad_flag(cli):
    r = cli.run("setup", "--help", cwd=cli.root)
    assert r.code == 0 and "usage: rga-ocr [--rga-config-file=F] setup [--apply]" in r.out
    assert "Exit status: 0 ready, 1 something to do, 2 usage error" in r.out
    r = cli.run("setup", "--bogus", cwd=cli.root)
    assert r.code == 2


# ------------------------------------------------------ engine checks

def test_check_engine_auto_falls_through_to_an_installed_engine(monkeypatch, tmp_path):
    """auto with rapidocr absent and tesserocr installed but without
    language files: setup proposes the tessdata fetch instead of pip."""
    from rga_ocr import engines, paths
    from rga_ocr.engines import tesseract as t
    monkeypatch.setattr(engines, "resolve",
                        lambda name, langs: (_ for _ in ()).throw(engines.EngineError("no OCR engine available")))
    monkeypatch.setattr(engines, "auto_order", lambda: ["rapidocr", "tesseract"])
    monkeypatch.setattr(engines.load("rapidocr"), "installed", classmethod(lambda c: False))
    tess = engines.load("tesseract")
    monkeypatch.setattr(tess, "installed", classmethod(lambda c: True))
    monkeypatch.setattr(tess, "available", classmethod(lambda c, langs: (False, "no language files for eng")))
    monkeypatch.setattr(t, "find_tessdata", lambda codes: None)
    monkeypatch.setattr(paths, "tessdata_dir", lambda: str(tmp_path))
    out = sc.Out()
    assert sc.check_engine(out, "auto", [], apply=False) is False
    assert any("auto will pick tesseract once it is ready: no language files for eng" in l
               for l in out.lines), out.lines
    assert any(td.startswith("fetch " + t.DOWNLOAD_BASE + "eng.traineddata -> ") for td in out.todos), out.todos
    assert not any("pip install" in td for td in out.todos), out.todos


def test_check_engine_named_but_not_installed(monkeypatch):
    from rga_ocr import engines
    tess = engines.load("tesseract")
    monkeypatch.setattr(tess, "installed", classmethod(lambda c: False))
    monkeypatch.setattr(tess, "available", classmethod(lambda c, langs: (False, "pip install 'rga-ocr[tesseract]'")))
    out = sc.Out()
    assert sc.check_engine(out, "tesseract", [], apply=False) is False
    assert any("rga-ocr[tesseract]" in td for td in out.todos), out.todos


def test_fetch_reports_failure_and_removes_the_part_file(monkeypatch, tmp_path):
    import urllib.error
    import urllib.request

    def boom(url, timeout=None):
        with open(str(tmp_path / "eng.traineddata.part"), "wb") as f:
            f.write(b"partial")
        raise urllib.error.URLError("name resolution failed")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    out = sc.Out()
    dest = str(tmp_path / "eng.traineddata")
    assert sc.fetch("https://example.invalid/eng.traineddata", dest, out) is False
    assert not os.path.exists(dest + ".part") and not os.path.exists(dest)
    assert any(l.startswith("fetch failed: ") for l in out.lines), out.lines
    assert out.todos == [f'curl -sSL -o "{dest}" https://example.invalid/eng.traineddata']


def test_git_blob_id_is_the_id_git_gives(tmp_path):
    empty, hello = tmp_path / "empty", tmp_path / "hello"
    empty.write_bytes(b"")
    hello.write_bytes(b"hello\n")
    assert sc.git_blob_id(str(empty)) == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"     # git hash-object
    assert sc.git_blob_id(str(hello)) == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_fetch_installs_only_the_expected_file(monkeypatch, tmp_path):
    import io
    import urllib.request
    body = {}
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(body["data"]))
    dest = str(tmp_path / "eng.traineddata")
    expect = (6, "ce013625030ba8dba906f756967f9e9ca394464a")            # b"hello\n"

    for data, why in ((b"hel", "got 3 of 6 bytes"), (b"hallo\n", "the content is not the file")):
        body["data"] = data
        out = sc.Out()
        assert sc.fetch("https://example.invalid/eng.traineddata", dest, out, expect=expect) is False
        assert not os.path.exists(dest) and not os.path.exists(dest + ".part")
        assert any(l.startswith("fetch failed: " + why) for l in out.lines), out.lines

    body["data"] = b"hello\n"
    assert sc.fetch("https://example.invalid/eng.traineddata", dest, sc.Out(), expect=expect) is True
    with open(dest, "rb") as f:
        assert f.read() == b"hello\n"


def test_language_files_are_fetched_from_a_fixed_commit_and_checked(monkeypatch, tmp_path):
    from rga_ocr import engines, paths
    from rga_ocr.engines import tesseract as t
    assert re.search(r"/raw/[0-9a-f]{40}/$", t.DOWNLOAD_BASE), t.DOWNLOAD_BASE
    assert all(size > 0 and re.fullmatch(r"[0-9a-f]{40}", blob) for size, blob in t.FILES.values())
    tess = engines.load("tesseract")
    monkeypatch.setattr(tess, "installed", classmethod(lambda c: True))
    monkeypatch.setattr(t, "find_tessdata", lambda codes: None)
    monkeypatch.setattr(paths, "tessdata_dir", lambda: str(tmp_path))
    seen = []
    monkeypatch.setattr(sc, "fetch", lambda url, dest, out, expect=None: seen.append((url, expect)) or True)
    sc.check_engine(sc.Out(), "tesseract", ["de"], apply=True)
    assert seen == [(t.DOWNLOAD_BASE + "deu.traineddata", t.FILES["deu"])], seen


def test_missing_engine_names_the_install_command_of_this_environment(monkeypatch):
    from rga_ocr import engines
    rapid = engines.load("rapidocr")
    monkeypatch.setattr(rapid, "installed", classmethod(lambda c: False))
    monkeypatch.setattr(sc, "under_homebrew", lambda: False)
    monkeypatch.setattr(sc, "under_pipx", lambda: True)
    assert rapid.available([]) == (False, 'not installed: pipx install --force "rga-ocr[rapidocr]"')
    # Homebrew: the formula has no extras, a pip command would lead nowhere
    monkeypatch.setattr(sc, "under_pipx", lambda: False)
    monkeypatch.setattr(sc, "under_homebrew", lambda: True)
    ok, reason = rapid.available([])
    assert not ok and "rga-ocr setup --engine rapidocr" in reason and "pip install" not in reason


def test_missing_language_files_hint_names_engine_and_languages(monkeypatch, tmp_path):
    from rga_ocr import engines
    from rga_ocr.engines import tesseract as t
    tess = engines.load("tesseract")
    monkeypatch.setattr(tess, "installed", classmethod(lambda c: True))
    monkeypatch.setattr(t, "find_tessdata", lambda codes: None)
    ok, reason = tess.available(["de-DE", "fr"])
    assert not ok and "rga-ocr setup --apply --engine tesseract --lang de-DE,fr fetches" in reason
    ok, reason = tess.available([])
    assert "rga-ocr setup --apply --engine tesseract fetches" in reason


# ------------------------------------------------------- adapter command

def test_adapter_flags_follow_the_place_of_the_install(monkeypatch, tmp_path):
    import site
    user = tmp_path / "user" / "site-packages"
    (user / "rga_ocr").mkdir(parents=True)
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(user))
    assert sc.in_user_site(str(user / "rga_ocr")) is True
    assert sc.in_user_site(str(tmp_path / "venv" / "site-packages" / "rga_ocr")) is False
    assert sc.in_user_site() is False and sc.adapter_args()[0] == "-I"
    monkeypatch.setattr(sc, "in_user_site", lambda: True)
    # -I would hide the user site-packages and with it this package
    assert sc.adapter_args() == ["-P", "-X", "utf8", "-m", "rga_ocr.adapter"]
    assert sc.adapter_entries()[0]["args"][:4] == ["-P", "-X", "utf8", "-m"]


def test_setup_starts_the_adapter(monkeypatch):
    out = sc.Out()
    assert sc.adapter_starts(out) is True and out.lines == ["the adapter starts"]
    monkeypatch.setattr(sc, "adapter_args", lambda: ["-I", "-m", "rga_ocr_not_there.adapter"])
    out = sc.Out()
    assert sc.adapter_starts(out) is False
    assert "the adapter does not start" in out.lines[0] and "rga_ocr_not_there" in out.lines[0], out.lines
    # and verify stops there
    out = sc.Out()
    assert sc.verify(out, apply=True) is False and len(out.lines) == 1


# -------------------------------------------------------- config write

CFG_WITH_COMMENT = """\
// keep me if you can
{
  "custom_adapters": [{"name": "mine", "binary": "/usr/bin/true", "args": []}],
  "max_archive_recursion": 4,
}
"""


def test_backup_path_keeps_the_first_bak(tmp_path):
    cfg = str(tmp_path / "config.jsonc")
    assert sc.backup_path(cfg) == cfg + ".bak"
    open(cfg + ".bak", "w").close()
    assert re.fullmatch(re.escape(cfg) + r"\.\d{8}-\d{6}\.bak", sc.backup_path(cfg))


def test_check_rga_config_does_not_ask_for_the_default_file(tmp_path, monkeypatch):
    # a search brings the entries along, so the dry run has nothing to do
    cfg = tmp_path / "default.jsonc"
    monkeypatch.setattr(sc.paths, "rga_config_path", lambda: str(cfg))
    out = sc.Out()
    assert sc.check_rga_config(out, apply=False) is True
    assert not out.todos and any("setup --apply" in line for line in out.lines)
    assert not cfg.exists()


def test_check_rga_config_writes_to_the_given_file(tmp_path, monkeypatch):
    cfg = str(tmp_path / "rga" / "config.jsonc")
    os.makedirs(os.path.dirname(cfg))
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(CFG_WITH_COMMENT)
    # the default path must stay untouched
    monkeypatch.setattr(sc.paths, "rga_config_path", lambda: str(tmp_path / "default.jsonc"))

    out = sc.Out()
    assert sc.check_rga_config(out, apply=False, rga_config=cfg) is False
    assert out.todos and "a .bak copy is kept, comments are not" in out.todos[-1]
    assert open(cfg, encoding="utf-8").read() == CFG_WITH_COMMENT

    out = sc.Out()
    assert sc.check_rga_config(out, apply=True, rga_config=cfg) is True
    assert open(cfg + ".bak", encoding="utf-8").read() == CFG_WITH_COMMENT
    merged = json.load(open(cfg, encoding="utf-8"))
    names = [a["name"] for a in merged["custom_adapters"]]
    assert names[:3] == list(NAMES["adapters"].values()) and "mine" in names
    assert merged["max_archive_recursion"] == 4
    assert not os.path.exists(str(tmp_path / "default.jsonc"))

    # a later change plus the second write: the first .bak stays, a
    # timestamped one holds the file as it was before this write
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(CFG_WITH_COMMENT.replace('"mine"', '"yours"'))
    out = sc.Out()
    assert sc.check_rga_config(out, apply=True, rga_config=cfg) is True
    assert open(cfg + ".bak", encoding="utf-8").read() == CFG_WITH_COMMENT
    stamped = [n for n in os.listdir(str(tmp_path / "rga")) if re.fullmatch(r"config\.jsonc\.\d{8}-\d{6}\.bak", n)]
    assert len(stamped) == 1, os.listdir(str(tmp_path / "rga"))


def test_check_rga_config_creates_the_file_and_then_leaves_it_alone(tmp_path):
    cfg = str(tmp_path / "new" / "config.jsonc")
    out = sc.Out()
    assert sc.check_rga_config(out, apply=True, rga_config=cfg) is True
    written = open(cfg, encoding="utf-8").read()
    assert [a["name"] for a in json.loads(written)["custom_adapters"]] == list(NAMES["adapters"].values())
    assert os.listdir(os.path.dirname(cfg)) == ["config.jsonc"]          # nothing to back up

    # a second run finds nothing to do: no write, no backup, with or without --apply
    for apply in (False, True):
        out = sc.Out()
        assert sc.check_rga_config(out, apply=apply, rga_config=cfg) is True
        assert "up to date" in out.lines and not out.todos
    assert open(cfg, encoding="utf-8").read() == written
    assert os.listdir(os.path.dirname(cfg)) == ["config.jsonc"]


def test_check_rga_config_leaves_a_file_it_cannot_parse(tmp_path):
    cfg = str(tmp_path / "config.jsonc")
    broken = '{"custom_adapters": [\n'
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(broken)
    out = sc.Out()
    assert sc.check_rga_config(out, apply=True, rga_config=cfg) is False
    assert any(line.startswith(f"cannot parse {cfg}: ") for line in out.lines), out.lines
    assert open(cfg, encoding="utf-8").read() == broken
    assert os.listdir(str(tmp_path)) == ["config.jsonc"]


LISTING = """Adapters:

 - **ocrpdf**
     rga-ocr pdf adapter
 - **ocrimg**
     rga-ocr image adapter
 - **officexml**
     rga-ocr office adapter
 - **pandoc**
     Uses pandoc to convert binary/unreadable text documents to plain markdown-like text
"""


def test_verify_runs_rga_only_with_apply(tmp_path, monkeypatch):
    cfg = str(tmp_path / "config.jsonc")
    ran = []

    def fake_run(cmd, **kw):
        ran.append(cmd)
        return SimpleNamespace(returncode=0, stdout=fake_run.stdout, stderr="")

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    monkeypatch.setattr(sc, "adapter_starts", lambda out: True)

    # no rga: nothing to verify with
    monkeypatch.setattr(sc.shutil, "which", lambda name: None)
    out = sc.Out()
    assert sc.verify(out, apply=True, rga_config=cfg) is False
    assert out.lines == ["rga not on PATH; skipped"] and not ran

    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/" + name)
    # dry run: prints the command, runs nothing
    out = sc.Out()
    assert sc.verify(out, apply=False, rga_config=cfg) is True
    assert out.lines[0].startswith(f"rga --rga-config-file={cfg} --rga-list-adapters") and not ran

    # --apply: rga lists the three adapters
    fake_run.stdout = LISTING
    out = sc.Out()
    assert sc.verify(out, apply=True, rga_config=cfg) is True
    assert ran == [["rga", f"--rga-config-file={cfg}", "--rga-list-adapters"]]
    assert out.lines == ["rga lists " + ", ".join(NAMES["adapters"].values())]

    # --apply: one adapter is not listed
    fake_run.stdout = LISTING.replace(" - **ocrimg**", " - **other**")
    out = sc.Out()
    assert sc.verify(out, apply=True, rga_config=cfg) is False
    assert out.lines == [f"rga does not list ocrimg; inspect {cfg}"]

    # without --rga-config-file the command carries no config flag
    del ran[:]
    fake_run.stdout = LISTING
    assert sc.verify(sc.Out(), apply=True) is True
    assert ran == [["rga", "--rga-list-adapters"]]


def test_setup_honours_rga_config_file_flag(cli, tmp_path):
    """`rga-ocr --rga-config-file=F setup` reports F, not the default path."""
    import subprocess
    cfg = str(tmp_path / "other.jsonc")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("{}\n")
    p = subprocess.run(NAMES["cli"] + ["--rga-config-file=" + cfg, "setup"], cwd=cli.root,
                       env=cli.env, capture_output=True, text=True, encoding="utf-8")
    assert p.returncode in (0, 1), p.stderr
    assert f"file: {cfg}" in p.stdout, p.stdout
    assert open(cfg, encoding="utf-8").read() == "{}\n"
    if shutil.which("rga"):
        assert f"rga --rga-config-file={cfg} --rga-list-adapters" in p.stdout, p.stdout


# ------------------------------------------------------------ engines

def test_plugin_load_failure_is_an_engine_error(monkeypatch):
    from rga_ocr import engines

    class BadEP:
        name = "broken"

        def load(self):
            raise ImportError("no module named nothing")
    monkeypatch.setattr(engines, "_external", lambda: {"broken": BadEP()})
    with pytest.raises(engines.EngineError, match="engine plugin 'broken' failed to load: ImportError"):
        engines.load("broken")


def test_vision_needs_macos_13(monkeypatch):
    import platform
    from rga_ocr.engines import vision
    monkeypatch.setattr(platform, "mac_ver", lambda: ("12.7.1", ("", "", ""), ""))
    assert vision.macos_version() == (12, 7)
    monkeypatch.setattr(platform, "mac_ver", lambda: ("", ("", "", ""), ""))
    assert vision.macos_version() == (0, 0)
    if sys.platform == "darwin":
        monkeypatch.setattr(platform, "mac_ver", lambda: ("12.7.1", ("", "", ""), ""))
        assert vision.VisionEngine.available([]) == (False, "needs macOS 13 or newer")


def test_load_jsonc_accepts_hash_comments_like_rga():
    text = '# top\n{\n  "accurate": false, # trailing note\n  "a": ["x # y", 2], # last\n}\n'
    assert sc.load_jsonc(text) == {"accurate": False, "a": ["x # y", 2]}
    assert sc.load_jsonc("# only a comment") == {}
    with pytest.raises(ValueError):
        sc.load_jsonc('{"a": tru # e\n}')


def test_registered_file_types():
    """The file types the adapters are registered for. The end-to-end suite
    takes its lists from the package, so a type dropped by mistake fails
    here by name."""
    assert sc.IMAGE_EXT == ["jpg", "jpeg", "png", "heic", "heif", "tif", "tiff", "webp", "gif", "bmp"]
    assert sc.OFFICE_EXT == ["xlsx", "pptx", "ods", "odp"]
    assert sc.IMAGE_MIME == ["image/jpeg", "image/png", "image/heic", "image/heif", "image/tiff",
                             "image/webp", "image/gif", "image/bmp"]
    assert len(sc.OFFICE_MIME) == len(sc.OFFICE_EXT)
    by_name = {e["name"]: e for e in sc.adapter_entries()}
    assert by_name["ocrimg"]["extensions"] == sc.IMAGE_EXT and by_name["ocrimg"]["mimetypes"] == sc.IMAGE_MIME
    assert by_name["officexml"]["extensions"] == sc.OFFICE_EXT
    assert by_name["ocrpdf"]["extensions"] == ["pdf"]
