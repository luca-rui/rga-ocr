"""Tesseract through tesserocr (wheels bundle the library; language files
are fetched separately into the tool's data directory or TESSDATA_PREFIX)."""

import os

from rga_ocr.engines import Engine

# BCP 47 primary subtag -> Tesseract traineddata name (ISO 639-2/T)
LANG_CODES = {
    "en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "nl": "nld",
    "da": "dan", "sv": "swe", "no": "nor", "nb": "nor", "fi": "fin", "pl": "pol", "cs": "ces",
    "sk": "slk", "hu": "hun", "ro": "ron", "tr": "tur", "el": "ell", "ru": "rus", "uk": "ukr",
    "bg": "bul", "sr": "srp", "hr": "hrv", "sl": "slv", "lt": "lit", "lv": "lav", "et": "est",
    "ca": "cat", "eu": "eus", "gl": "glg", "ga": "gle", "cy": "cym", "is": "isl", "mt": "mlt",
    "sq": "sqi", "mk": "mkd", "be": "bel", "ka": "kat", "hy": "hye", "he": "heb", "ar": "ara",
    "fa": "fas", "ur": "urd", "hi": "hin", "bn": "ben", "ta": "tam", "te": "tel", "th": "tha",
    "vi": "vie", "id": "ind", "ms": "msa", "tl": "tgl", "ja": "jpn", "ko": "kor", "zh": "chi_sim",
    "la": "lat", "af": "afr", "sw": "swa",
}
DEFAULT = ["eng"]
DOWNLOAD_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/"


def codes_for(langs):
    out = []
    for tag in langs:
        primary = tag.split("-")[0].split("_")[0].lower()
        code = "chi_tra" if tag.lower() in ("zh-tw", "zh-hant", "zh-hk") else LANG_CODES.get(primary)
        if code is None:
            raise ValueError(f"tesseract: no language code known for {tag!r}")
        if code not in out:
            out.append(code)
    return out or list(DEFAULT)


def tessdata_candidates():
    """Directories searched for traineddata files, first match wins."""
    from rga_ocr import paths
    out = []
    if os.environ.get("TESSDATA_PREFIX"):
        out.append(os.environ["TESSDATA_PREFIX"])
    out.append(paths.tessdata_dir())
    return out


def find_tessdata(codes):
    """The first candidate directory holding every requested language."""
    for d in tessdata_candidates():
        if all(os.path.isfile(os.path.join(d, c + ".traineddata")) for c in codes):
            return d
    return None


class TesseractEngine(Engine):
    name = "tesseract"
    extra = "tesseract"
    modules = ("tesserocr",)

    @classmethod
    def available(cls, langs):
        if not cls.installed():
            return False, "pip install 'rga-ocr[tesseract]'"
        try:
            codes = codes_for(langs)
        except ValueError as e:
            return False, str(e)
        if find_tessdata(codes) is None:
            from rga_ocr import paths
            missing = " ".join(codes)
            return False, (f"language files {missing} missing; rga-ocr setup --apply fetches them "
                           f"into {paths.tessdata_dir()} (or set TESSDATA_PREFIX)")
        return True, ""

    @classmethod
    def lang_tag(cls, langs):
        return "+".join(codes_for(langs)).replace("+", "_")

    def __init__(self, langs):
        super().__init__(langs)
        from tesserocr import PSM, PyTessBaseAPI
        codes = codes_for(langs)
        path = find_tessdata(codes)
        if path is None:
            raise RuntimeError("tesseract language files missing: " + " ".join(codes))
        self.api = PyTessBaseAPI(path=path, lang="+".join(codes), psm=PSM.AUTO)

    def recognize(self, img):
        from tesserocr import RIL
        w, h = img.size
        self.api.SetImage(img)
        self.api.Recognize()
        it = self.api.GetIterator()
        lines = []
        if it is None:
            return lines
        while True:
            if not it.Empty(RIL.TEXTLINE):
                text = (it.GetUTF8Text(RIL.TEXTLINE) or "").strip()
                x1, y1, x2, y2 = it.BoundingBox(RIL.TEXTLINE)
                if text:
                    lines.append((y1 / h, x1 / w, (y2 - y1) / h, text))
            if not it.Next(RIL.TEXTLINE):
                break
        return lines


ENGINE = TesseractEngine
