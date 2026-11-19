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


# ------------------------------------------------------- PDF text layer

def test_pdf_text_layer_keeps_the_words_of_a_line_in_order(tmp_path, monkeypatch):
    """One printed line set in several font sizes: the boxes differ in top
    and height, the words must still come out left to right."""
    import make_fixtures
    path = str(tmp_path / "mixed.pdf")
    line1 = [(50, 700, 12, "For"), (80, 700, 9, "use on"), (120, 700, 16, "Apple-branded"),
             (240, 700, 10, "Systems")]
    line2 = [(50, 682, 9, "and"), (75, 682, 14, "nothing"), (135, 682, 10, "else whatsoever")]
    make_fixtures.write_pdf(path, [{"width": 595, "height": 842, "lines": line1 + line2}])
    monkeypatch.setenv("RGA_OCR_NO_OCR", "1")
    with open(path, "rb") as f:
        text = adapter.mode_pdf(f.read())
    assert text == "For use on Apple-branded Systems and nothing else whatsoever"


def test_paragraphs_ordered_keeps_reading_order_and_splits_at_a_column_jump():
    # two columns: the second starts back at the top of the page
    lines = [(0.10, 0.1, 0.02, "left one"), (0.125, 0.1, 0.02, "left two"),
             (0.10, 0.6, 0.02, "right one"), (0.125, 0.6, 0.02, "right two")]
    assert adapter.paragraphs(lines, ordered=True) == "left one left two\nright one right two"


class FakeOCR:
    """Stands in for adapter.OCR; fails on the pages named in bad."""
    bad = ()

    def __init__(self):
        self.calls = 0

    def text(self, img):
        self.calls += 1
        if self.calls in self.bad:
            raise OSError("model fetch failed")
        return f"scan {self.calls}"


def scan_pdf(tmp_path, pages):
    import make_fixtures
    jpeg = make_fixtures.jpeg_bytes(make_fixtures.text_image("x"))
    path = str(tmp_path / "scan.pdf")
    make_fixtures.write_pdf(path, [{"width": 595, "height": 842, "jpeg": jpeg}] * pages)
    with open(path, "rb") as f:
        return f.read()


def test_pdf_keeps_the_pages_read_when_one_page_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (2,))
    pages = adapter.mode_pdf(scan_pdf(tmp_path, 3)).split(adapter.PAGE_BREAK)
    assert pages == ["scan 1", "", "scan 3"]
    assert len(adapter.NOTES) == 1
    assert adapter.NOTES[0].startswith("OCR failed on 1 of 3 pages, first page 2: OSError: model fetch failed")


def test_pdf_fails_as_a_whole_when_no_page_could_be_read(tmp_path, monkeypatch):
    # the engine is the problem then: an error, so that the file is retried
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (1, 2))
    with pytest.raises(RuntimeError, match="OCR failed on every page; page 1: OSError"):
        adapter.mode_pdf(scan_pdf(tmp_path, 2))
    assert adapter.NOTES == []


def test_adapter_reports_a_partial_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (1,))
    report = tmp_path / "report"
    monkeypatch.setattr(adapter, "REPORT", str(report))
    monkeypatch.setattr(sys, "argv", ["adapter", "pdf", "/x/scan.pdf"])

    class Stdin:
        buffer = __import__("io").BytesIO(scan_pdf(tmp_path, 2))
    monkeypatch.setattr(sys, "stdin", Stdin)
    out = []
    monkeypatch.setattr(adapter, "write_out", out.append)
    adapter.main()
    assert out == [adapter.PAGE_BREAK + "scan 2"]
    events = [l.split("\t")[0] for l in report.read_text(encoding="utf-8").splitlines()]
    assert events == ["start", "partial", "done"]


# --------------------------------------------------- transparent images

@pytest.mark.parametrize("mode", ["RGBA", "LA", "PA", "P"])
def test_decode_puts_transparent_images_on_white(mode):
    """Dark text on a transparent background: a plain convert("RGB") shows
    the colour under the alpha channel, black on black."""
    import io
    from PIL import Image
    img = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    for x in range(10, 20):
        img.putpixel((x, 10), (0, 0, 0, 255))
    buf = io.BytesIO()
    if mode == "P":
        pal = Image.new("P", img.size, 0)
        pal.putpalette([0, 0, 0, 0, 0, 0])              # both entries black
        for x in range(10, 20):
            pal.putpixel((x, 10), 1)
        pal.save(buf, "PNG", transparency=0)            # entry 0 is transparent
    elif mode != "PA":
        img.convert(mode).save(buf, "PNG")
    # PNG cannot hold PA; it reaches to_rgb from other containers
    frame = adapter.to_rgb(img.convert("PA")) if mode == "PA" else adapter.decode(buf.getvalue())[0]
    assert frame.mode == "RGB"
    assert frame.getpixel((0, 0)) == (255, 255, 255)
    assert frame.getpixel((15, 10)) == (0, 0, 0)


# --------------------------------------------------------------- office

def office(members):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in members.items():
            z.writestr(name, body)
    return adapter.mode_office(buf.getvalue())


def test_office_runs_of_one_word_stay_one_word():
    slide = ('<p:sld><a:p><a:r><a:t>Kessel</a:t></a:r><a:r><a:t>anlage und</a:t></a:r>'
             '<a:r><a:t> Wartung</a:t></a:r><a:br/><a:r><a:t>Zeile zwei</a:t></a:r></a:p>'
             '<a:p><a:r><a:t>Absatz</a:t></a:r></a:p></p:sld>')
    assert office({"ppt/slides/slide1.xml": slide}) == "Kesselanlage und Wartung Zeile zwei\nAbsatz"
    shared = '<sst><si><r><t>Kessel</t></r><r><t>anlage</t></r></si><si><t>Zweite</t></si></sst>'
    sheet = '<worksheet><sheetData><row><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>'
    assert office({"xl/workbook.xml": "", "xl/sharedStrings.xml": shared,
                   "xl/worksheets/sheet1.xml": sheet}) == "Kesselanlage\nZweite"
    odp = ('<office:document-content><draw:page><text:p>Kessel<text:span>anlage</text:span>'
           '<text:s/>und<text:tab/>Wartung<text:line-break/>neu</text:p></draw:page>'
           '</office:document-content>')
    assert office({"content.xml": odp}) == "Kesselanlage und Wartung neu"


def test_office_cells_of_a_row_stay_apart():
    sheet = ('<worksheet><sheetData>'
             '<row><c r="A1"><v>12</v></c><c r="B1"><v>34</v></c><c r="C1" s="2"/>'
             '<c r="D1" t="s"><v>0</v></c><c r="E1"><f>A1+B1</f><v>46</v></c>'
             '<c r="F1" t="inlineStr"><is><t>frei</t></is></c><c r="G1"><v>7</v></c></row>'
             '<row><c r="A2"><v>56</v></c></row></sheetData></worksheet>')
    assert office({"xl/workbook.xml": "", "xl/worksheets/sheet1.xml": sheet}) == "12 34 A1+B1 46 frei 7\n56"
    ods = ('<office:document-content><table:table><table:table-row>'
           '<table:table-cell><text:p>12</text:p></table:table-cell>'
           '<table:table-cell><text:p>34</text:p></table:table-cell>'
           '</table:table-row></table:table></office:document-content>')
    assert office({"content.xml": ods}).split() == ["12", "34"]
