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


def test_heic_without_pi_heif_is_a_retry_not_an_empty_file():
    """Where pi-heif has no wheels (Python 3.15, Windows on arm64) a HEIC
    file must not be cached as a file without text."""
    sample = os.path.join(os.path.dirname(__file__), "data", "shot.heic")
    # a process of its own: once registered, Pillow keeps the HEIF opener
    code = (
        "import sys; sys.modules['pi_heif'] = None\n"          # import raises ImportError
        "from rga_ocr import adapter\n"
        "data = open(sys.argv[1], 'rb').read()\n"
        "assert adapter.is_heif(data)\n"
        "for d in (data, b'not an image'):\n"
        "    try:\n"
        "        adapter.decode(d)\n"
        "    except Exception as e:\n"
        "        print(type(e).__name__, e)\n")
    p = subprocess.run([sys.executable, "-I", "-c", code, sample], capture_output=True, text=True)
    lines = p.stdout.splitlines()
    assert len(lines) == 2, p.stdout + p.stderr
    assert lines[0].startswith("EngineFailure MissingDecoder: HEIC and HEIF need pi-heif"), lines
    assert lines[1] == "RuntimeError not a decodable image", lines


def test_tesseract_language_mapping(monkeypatch, tmp_path):
    from rga_ocr.engines import tesseract as t
    assert t.codes_for([]) == ["eng"]
    assert t.codes_for(["de-DE", "en-US", "de-AT"]) == ["deu", "eng"]
    assert t.codes_for(["zh-TW"]) == ["chi_tra"] and t.codes_for(["zh"]) == ["chi_sim"]
    with pytest.raises(ValueError, match="no language file known for 'xx'"):
        t.codes_for(["xx"])
    # Tesseract's own file names pass as they are
    assert t.codes_for(["frk", "de", "chi_sim_vert"]) == ["frk", "deu", "chi_sim_vert"]
    # every tag leads to a file that exists (tl once led to tgl, which does not)
    assert set(t.LANG_CODES.values()) | {"chi_tra"} <= set(t.FILES)
    assert t.codes_for(["tl"]) == ["fil"]
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
            raise adapter.EngineFailure(OSError("model fetch failed"))
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
    # the engine is the problem then, not one page
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (1, 2))
    with pytest.raises(adapter.EngineFailure, match="OSError: model fetch failed"):
        adapter.mode_pdf(scan_pdf(tmp_path, 2))
    assert adapter.NOTES == []


def test_pdf_with_text_pages_is_retried_when_the_engine_is_down(tmp_path, monkeypatch):
    # pages with a text layer need no OCR and do not count: a file whose
    # scanned pages all failed must not be cached with those pages missing
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (1, 2))
    layers = iter(["a page that carries a text layer of its own", "", ""])
    monkeypatch.setattr(adapter, "_text_layer", lambda page: next(layers))
    with pytest.raises(adapter.EngineFailure):
        adapter.mode_pdf(scan_pdf(tmp_path, 3))
    assert adapter.NOTES == []


def test_ocr_wraps_engine_errors(monkeypatch):
    monkeypatch.setenv("RGA_OCR_ENGINE", "bogus")
    with pytest.raises(adapter.EngineFailure, match="EngineError: unknown engine 'bogus'"):
        adapter.OCR()

    class Broken(adapter.OCR):
        def __init__(self):
            class Engine:
                def recognize(self, img):
                    raise OSError("no\nmodel")
            self.engine = Engine()
    with pytest.raises(adapter.EngineFailure, match="OSError: no model"):
        from PIL import Image
        Broken().text(Image.new("RGB", (40, 40)))


def run_main(monkeypatch, tmp_path, mode, data):
    """adapter.main() on data; returns (output, report events)."""
    report = tmp_path / "report"
    monkeypatch.setattr(adapter, "REPORT", str(report))
    monkeypatch.setattr(sys, "argv", ["adapter", mode, "/x/file"])

    class Stdin:
        buffer = __import__("io").BytesIO(data)
    monkeypatch.setattr(sys, "stdin", Stdin)
    out = []
    monkeypatch.setattr(adapter, "write_out", out.append)
    adapter.main()
    return out, [l.split("\t")[0] for l in report.read_text(encoding="utf-8").splitlines()]


def test_adapter_reports_engine_failures_as_retry_and_unreadable_files_as_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (1, 2))
    assert run_main(monkeypatch, tmp_path, "pdf", scan_pdf(tmp_path, 2)) == ([], ["start", "retry", "done"])
    (tmp_path / "report").unlink()
    assert run_main(monkeypatch, tmp_path, "pdf", b"this is not a pdf") == ([], ["start", "error", "done"])
    (tmp_path / "report").unlink()
    assert run_main(monkeypatch, tmp_path, "image", b"not an image") == ([], ["start", "error", "done"])


def test_adapter_reports_a_partial_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(FakeOCR, "bad", (1,))
    out, events = run_main(monkeypatch, tmp_path, "pdf", scan_pdf(tmp_path, 2))
    assert out == [adapter.PAGE_BREAK + "scan 2"]
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
    if mode == "PA":
        # PNG cannot hold PA; it reaches to_rgb from other containers. Built
        # by hand: older Pillow drops the alpha in convert("PA").
        pa = Image.new("P", img.size, 0)
        pa.putpalette([0, 0, 0])
        pa.putalpha(img.getchannel("A"))
        assert pa.mode == "PA"
        frame = adapter.to_rgb(pa)
    else:
        frame = adapter.decode(buf.getvalue())[0]
    assert frame.mode == "RGB"
    assert frame.getpixel((0, 0)) == (255, 255, 255)
    assert frame.getpixel((15, 10)) == (0, 0, 0)


# --------------------------------------------------------------- office

def office_file(members):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


def office(members):
    return adapter.mode_office(office_file(members))


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


class PictureOCR:
    """Stands in for adapter.OCR on the pictures of a slide deck: the text
    of a picture is its bytes; fails on the pictures named in bad."""
    bad = ()
    made = 0
    seen = []

    def __init__(self):
        PictureOCR.made += 1

    def text_of_bytes(self, data):
        PictureOCR.seen.append(data)
        if data in self.bad:
            raise adapter.EngineFailure(OSError("model fetch failed"))
        return ["read " + data.decode()]


SLIDE = "<p:sld><a:p><a:r><a:t>{}</a:t></a:r></a:p></p:sld>"
RELS = ('<Relationships>'
        '<Relationship Id="rId1" Type="http://x/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        '{}</Relationships>')
IMAGE_REL = '<Relationship Id="rId{}" Type="http://x/relationships/image" Target="{}"{}/>'


def deck(**media):
    return {"ppt/slides/slide1.xml": SLIDE.format("Agenda"),
            "ppt/slides/_rels/slide1.xml.rels": RELS.format(
                IMAGE_REL.format(2, "../media/a.png", "") + IMAGE_REL.format(3, "../media/drawing.emf", "")
                + IMAGE_REL.format(4, "/ppt/media/b.jpg", "")
                + IMAGE_REL.format(5, "https://example.org/c.png", ' TargetMode="External"')),
            "ppt/slides/slide2.xml": SLIDE.format("Status"),
            "ppt/slides/_rels/slide2.xml.rels": RELS.format(IMAGE_REL.format(2, "../media/a.png", "")),
            "ppt/slides/slide3.xml": SLIDE.format("Ende"),
            "ppt/media/a.png": b"one", "ppt/media/b.jpg": b"two", "ppt/media/drawing.emf": b"vector",
            "ppt/media/unused.png": b"unused", **media}


@pytest.fixture
def picture_ocr(monkeypatch):
    monkeypatch.setattr(adapter, "OCR", PictureOCR)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(PictureOCR, "bad", ())
    monkeypatch.setattr(PictureOCR, "made", 0)
    monkeypatch.setattr(PictureOCR, "seen", [])
    monkeypatch.delenv("RGA_OCR_NO_OCR", raising=False)
    return PictureOCR


def test_pictures_on_pptx_slides_are_read_with_their_slide(picture_ocr):
    pages = office(deck()).split(adapter.PAGE_BREAK)
    assert pages == ["Agenda\nread one\nread two", "Status\nread one", "Ende"]
    # one engine for the file, and a picture two slides show is read once;
    # the vector drawing, the external link and the unused picture are not
    assert picture_ocr.made == 1
    assert picture_ocr.seen == [b"one", b"two"]
    assert adapter.NOTES == []


def test_pictures_on_odp_slides_and_an_empty_slide_keeps_its_page(picture_ocr):
    page = "<draw:page>{}</draw:page>"
    odp = ("<office:document-content>" + page.format("<text:p>Agenda</text:p>") + page.format("")
           + page.format('<draw:frame><draw:image xlink:href="Pictures/a.png"/></draw:frame>')
           + page.format('<text:p>Ende</text:p><draw:image xlink:href="./Pictures/a.png"/>'
                         '<draw:image xlink:href="Pictures/gone.png"/>')
           + "</office:document-content>")
    pages = office({"content.xml": odp, "Pictures/a.png": b"one"}).split(adapter.PAGE_BREAK)
    assert pages == ["Agenda", "", "read one", "Ende\nread one"]
    assert picture_ocr.seen == [b"one"]


def test_no_ocr_leaves_the_pictures_of_a_deck_alone(picture_ocr, monkeypatch):
    monkeypatch.setenv("RGA_OCR_NO_OCR", "1")
    assert office(deck()).split(adapter.PAGE_BREAK) == ["Agenda", "Status", "Ende"]
    assert picture_ocr.made == 0


def test_deck_keeps_its_text_when_some_pictures_fail(picture_ocr, monkeypatch):
    monkeypatch.setattr(PictureOCR, "bad", (b"two",))
    assert office(deck()).split(adapter.PAGE_BREAK) == ["Agenda\nread one", "Status\nread one", "Ende"]
    assert adapter.NOTES == ["OCR failed on 1 of 2 pictures: OSError: model fetch failed"]


def test_deck_is_retried_and_keeps_its_text_when_the_engine_is_down(picture_ocr, monkeypatch, tmp_path):
    monkeypatch.setattr(PictureOCR, "bad", (b"one", b"two"))
    with pytest.raises(adapter.EngineFailure) as e:
        office(deck())
    assert e.value.text.split(adapter.PAGE_BREAK) == ["Agenda", "Status", "Ende"]
    # the adapter writes the text of the slides and reports a retry
    out, events = run_main(monkeypatch, tmp_path, "office", office_file(deck()))
    assert out == [adapter.PAGE_BREAK.join(["Agenda", "Status", "Ende"])]
    assert events == ["start", "retry", "done"]


def test_an_engine_that_does_not_start_is_tried_once_per_deck(picture_ocr, monkeypatch):
    class Down(PictureOCR):
        def __init__(self):
            super().__init__()
            raise adapter.EngineFailure(OSError("no language data"))
    monkeypatch.setattr(PictureOCR, "made", 0)
    monkeypatch.setattr(adapter, "OCR", Down)
    with pytest.raises(adapter.EngineFailure, match="no language data") as e:
        office(deck())
    assert e.value.text.split(adapter.PAGE_BREAK) == ["Agenda", "Status", "Ende"]
    assert PictureOCR.made == 1


def test_an_image_too_small_for_text_never_reaches_the_engine(monkeypatch):
    # a rule or a bullet on a slide: Apple Vision raises on a side of 2 pixels,
    # and a deck of such pictures would be read again on every search
    from PIL import Image

    class NoEngine(adapter.OCR):
        def __init__(self):
            self.engine = None      # any call would raise
    ocr = NoEngine()
    for size in ((1, 1), (2000, 2), (9, 400)):
        assert ocr.text(Image.new("RGB", size, "white")) == ""
    with pytest.raises(adapter.EngineFailure):
        ocr.text(Image.new("RGB", (10, 10), "white"))


def test_deck_with_more_pictures_than_the_limit(picture_ocr, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_PICTURES", 1)
    assert office(deck()).split(adapter.PAGE_BREAK) == ["Agenda\nread one", "Status\nread one", "Ende"]
    assert adapter.NOTES == ["more than 1 pictures, the rest was not read (RGA_OCR_MAX_PICTURES raises the limit)"]


def test_a_picture_that_cannot_be_decoded_costs_only_itself(monkeypatch):
    # the real OCR class up to the decoder: these bytes are no image
    class NoEngine(adapter.OCR):
        def __init__(self):
            pass
    monkeypatch.setattr(adapter, "OCR", NoEngine)
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.delenv("RGA_OCR_NO_OCR", raising=False)
    assert office(deck()).split(adapter.PAGE_BREAK) == ["Agenda", "Status", "Ende"]
    assert adapter.NOTES == ["2 of 2 pictures could not be read"]


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


# --------------------------------------------------------------- limits

def tiff(frames):
    import io
    from PIL import Image
    imgs = [Image.new("RGB", (40, 30), (255, 255, 255)) for _ in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, "TIFF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def test_frames_come_one_at_a_time():
    it = adapter.frames(tiff(4))
    assert iter(it) is it                        # a generator, not a list of every frame
    assert next(it).size == (40, 30)
    assert len(list(it)) == 3
    assert len(adapter.decode(tiff(4))) == 4


def test_image_with_more_frames_than_the_limit_is_read_up_to_it(monkeypatch):
    monkeypatch.setattr(FakeOCR, "text_of_bytes", adapter.OCR.text_of_bytes, raising=False)
    monkeypatch.setattr(adapter, "OCR", FakeOCR)
    monkeypatch.setattr(FakeOCR, "bad", ())
    monkeypatch.setattr(adapter, "NOTES", [])
    monkeypatch.setattr(adapter, "MAX_FRAMES", 3)
    assert adapter.mode_image(tiff(5)) == "scan 1\n\nscan 2\n\nscan 3"
    assert adapter.NOTES == ["more than 3 frames, the rest was not read (RGA_OCR_MAX_FRAMES raises the limit)"]
    # at the limit nothing is left out and nothing is reported
    monkeypatch.setattr(adapter, "NOTES", [])
    assert adapter.mode_image(tiff(3)).count("scan") == 3
    assert adapter.NOTES == []


def test_office_text_beyond_the_limit_is_left_out_and_reported(monkeypatch):
    def slide(word, n):
        return "<p:sld>" + f"<a:p><a:r><a:t>{word}</a:t></a:r></a:p>" * n + "</p:sld>"
    deck = {"ppt/slides/slide1.xml": slide("eins", 20000),      # about 700 kB
            "ppt/slides/slide2.xml": slide("zwei", 20000),
            "ppt/slides/slide3.xml": slide("drei", 10)}
    monkeypatch.setattr(adapter, "NOTES", [])
    whole = office(deck)
    assert adapter.NOTES == [] and whole.count("zwei") == 20000 and whole.count("drei") == 10
    monkeypatch.setattr(adapter, "MAX_OFFICE_MB", 1)
    cut = office(deck)
    assert cut.count("eins") == 20000                 # what was read is kept
    assert 0 < cut.count("zwei") < 20000 and "drei" not in cut
    assert len(adapter.NOTES) == 1, adapter.NOTES     # once, not once per member
    assert adapter.NOTES[0].startswith("more than 1 MB of text, read up to there, the rest from ppt/slides/slide2.xml on")
    # the same text packed small: the bytes read count, not the size of the file
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("content.xml", "<office:document-content><text:p>" + "A" * (3 << 20) + "</text:p></office:document-content>")
    assert len(buf.getvalue()) < 10000
    monkeypatch.setattr(adapter, "NOTES", [])
    assert len(adapter.mode_office(buf.getvalue())) <= 1 << 20
    assert len(adapter.NOTES) == 1
