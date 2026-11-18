"""Unit tests for the adapter's engine-independent parts."""
import os
import subprocess
import sys

import pytest

from rga_ocr import adapter, engines

HERE = os.path.dirname(os.path.abspath(__file__))


def test_paragraphs_joins_adjacent_lines():
    # top-down frame: line 2 sits right below line 1, line 3 a long way down
    lines = [(0.10, 0.1, 0.05, "Wartungsvertrag"),
             (0.16, 0.1, 0.05, "Kesselanlage"),
             (0.60, 0.1, 0.05, "Seite eins")]
    assert adapter.paragraphs(lines) == "Wartungsvertrag Kesselanlage\nSeite eins"
    # order of input does not matter
    assert adapter.paragraphs(list(reversed(lines))) == "Wartungsvertrag Kesselanlage\nSeite eins"
    assert adapter.paragraphs([]) == ""


def test_parse_cache_tag():
    assert engines.parse_cache_tag("vision-auto") == ("vision", "auto", False)
    assert engines.parse_cache_tag("vision-de-DE_en-US-force") == ("vision", "de-DE_en-US", True)
    assert engines.parse_cache_tag("none") == ("none", "", False)


def test_resolve_unknown():
    with pytest.raises(engines.EngineError, match="unknown engine 'bogus'"):
        engines.resolve("bogus", [])


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    fx = str(tmp_path_factory.mktemp("fx"))
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "make_fixtures.py"), fx], check=True)
    return fx


def test_decode_applies_orientation_and_cap(fixtures, monkeypatch):
    from PIL import Image
    with Image.open(os.path.join(fixtures, "photo.png")) as im:
        upright = im.size
    with open(os.path.join(fixtures, "rotated.jpg"), "rb") as f:
        frames = adapter.decode(f.read())
    assert len(frames) == 1
    assert frames[0].size == upright and frames[0].mode == "RGB"
    monkeypatch.setattr(adapter, "MAX_PIXELS", 300)
    with open(os.path.join(fixtures, "photo.png"), "rb") as f:
        small = adapter.decode(f.read())[0]
    assert max(small.size) == 300
    with pytest.raises(RuntimeError, match="not a decodable image"):
        adapter.decode(b"not an image")


def test_rapidocr_language_mapping():
    from rga_ocr.engines import rapidocr as r
    assert r.model_for([]) == "multi"
    assert r.model_for(["de-DE", "en-US", "fr"]) == "multi"
    assert r.model_for(["ru-RU", "uk"]) == "cyrillic"
    assert r.model_for(["ja"]) == "multi" and r.model_for(["ko"]) == "korean"
    with pytest.raises(ValueError, match="one script per run"):
        r.model_for(["de", "ru"])
    with pytest.raises(ValueError, match="no model for language 'xx'"):
        r.model_for(["xx"])


def test_rapidocr_models_resolve():
    """Every script model resolves to a model file in rapidocr's own routing
    table, with the parameters the engine passes (no download involved)."""
    pytest.importorskip("rapidocr")
    from rga_ocr.engines import rapidocr as r
    from rapidocr import LangRec, ModelType, OCRVersion
    from rapidocr.utils.model_resolver import route_to_model_key
    from rapidocr.utils.typings import TaskType
    rec = next(t for t in TaskType if t.value == "rec")
    for model in sorted(set(r.SCRIPT_MODELS.values())):
        version = OCRVersion(r.MODEL_VERSION.get(model, r.MODEL_VERSION_DEFAULT))
        key = route_to_model_key(rec, version, LangRec(model), ModelType.MOBILE)
        assert key, f"{model}: no {version.value} mobile recognition model"


def test_tesseract_language_mapping(monkeypatch, tmp_path):
    from rga_ocr.engines import tesseract as t
    assert t.codes_for([]) == ["eng"]
    assert t.codes_for(["de-DE", "en-US", "de-AT"]) == ["deu", "eng"]
    assert t.codes_for(["zh-TW"]) == ["chi_tra"] and t.codes_for(["zh"]) == ["chi_sim"]
    with pytest.raises(ValueError, match="no language code known for 'xx'"):
        t.codes_for(["xx"])
    assert t.ENGINE.lang_tag(["de", "en"]) == "deu_eng"
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))
    assert t.find_tessdata(["deu"]) is None
    (tmp_path / "deu.traineddata").write_bytes(b"x")
    assert t.find_tessdata(["deu"]) == str(tmp_path)


def test_winocr_language_matching():
    from rga_ocr.engines import winocr as w
    installed = ["en-US", "de-DE"]
    assert w.match_language(["de-DE"], installed) == "de-DE"
    assert w.match_language(["de-at"], installed) == "de-DE"
    assert w.match_language(["fr", "en"], installed) == "en-US"
    assert w.match_language(["fr"], installed) is None
    assert w.match_language([], installed) is None
    assert 'Language.OCR~~~de-DE~0.0.1.0' in w.capability_command("de-DE")
    if sys.platform != "win32":
        assert w.ENGINE.available([])[0] is False


def test_rapidocr_module_opts_out_of_onnxruntime_telemetry(monkeypatch):
    import importlib
    from rga_ocr.engines import rapidocr
    loaded_before = "onnxruntime" in sys.modules
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    importlib.reload(rapidocr)
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
    # the module itself must not import onnxruntime: the variable has to be
    # in place before the runtime initialises
    assert ("onnxruntime" in sys.modules) == loaded_before
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    importlib.reload(rapidocr)
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "0"


def test_pdf_no_ocr_reads_the_text_layer_and_never_starts_an_engine(fixtures, monkeypatch):
    def no_engine():
        raise AssertionError("OCR engine constructed")
    monkeypatch.setattr(adapter, "OCR", no_engine)
    monkeypatch.setenv("RGA_OCR_NO_OCR", "1")
    monkeypatch.setenv("RGA_OCR_FORCE_OCR", "1")      # NO_OCR wins
    with open(os.path.join(fixtures, "textlayer.pdf"), "rb") as f:
        pages = adapter.mode_pdf(f.read()).split(adapter.PAGE_BREAK)
    assert len(pages) == 2
    assert "Wartungsvertrag Kesselanlage" in pages[1]
    with open(os.path.join(fixtures, "sub", "scan.pdf"), "rb") as f:
        assert adapter.mode_pdf(f.read()).strip() == ""
    monkeypatch.delenv("RGA_OCR_NO_OCR")
    monkeypatch.delenv("RGA_OCR_FORCE_OCR")
    with open(os.path.join(fixtures, "sub", "scan.pdf"), "rb") as f, pytest.raises(AssertionError):
        adapter.mode_pdf(f.read())


def test_adapter_process_exits_zero_on_unknown_mode():
    r = subprocess.run([sys.executable, "-m", "rga_ocr.adapter", "nope", "x"],
                       input=b"data", capture_output=True, timeout=60)
    assert r.returncode == 0
    assert r.stdout == b""
    assert b"unknown mode" in r.stderr


def test_winocr_cache_tag_names_the_pack_that_does_the_work(monkeypatch):
    from rga_ocr.engines import winocr as w
    monkeypatch.setattr(w, "_installed", lambda: ["en-US", "de-DE"])
    assert w.ENGINE.lang_tag(["de"]) == "de-DE"
    assert w.ENGINE.lang_tag(["de-AT", "en"]) == "de-DE"
    assert w.ENGINE.lang_tag(["fr", "en"]) == "en-US"
    assert w.ENGINE.lang_tag(["fr"]) == "fr"                 # no pack: the requested tags
    assert w.ENGINE.lang_tag([]) == "auto"
    assert engines.cache_tag(w.ENGINE, ["de", "en"], force=True) == "winocr-de-DE-force"
    assert engines.parse_cache_tag("winocr-de-DE-force") == ("winocr", "de-DE", True)

    def broken():
        raise OSError("no WinRT")
    monkeypatch.setattr(w, "_installed", broken)
    assert w.ENGINE.lang_tag(["de", "en"]) == "de_en"
