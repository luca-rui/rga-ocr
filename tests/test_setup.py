"""Unit tests for `rga-ocr setup`: the JSONC parser, the config merge and
the install-command table. No tools, no network."""
import json
import os
import re
import shutil
import sys

import pytest

from rga_ocr import setup_cmd as sc
from conftest import NAMES

JSONC = """\
// rga default config
{
  /* block comment, with a "quoted" string inside */
  "custom_adapters": [
    {
      "name": "visionpdf", "binary": "/old/bin/rga-adapter", "args": ["pdf", "${input_virtual_path}"],
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
    assert names == ["visionpdf", "mine"]
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


def test_merge_keeps_foreign_entries_and_drops_legacy_ones():
    cfg = sc.load_jsonc(JSONC)
    merged = sc.merge_config(cfg, sc.adapter_entries())
    names = [a["name"] for a in merged["custom_adapters"]]
    assert names == ["ocrpdf", "ocrimg", "officexml", "mine"]
    assert merged["max_archive_recursion"] == 4
    assert cfg["custom_adapters"][0]["name"] == "visionpdf"      # input untouched
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
    assert sc.extra_install_command("vision") == f'"{sys.executable}" -m pip install "rga-ocr[vision]"'


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
