"""RapidOCR (PaddleOCR models on ONNX Runtime): pip-only, every platform.

The package ships one multilingual PP-OCRv6 model that covers Chinese,
Japanese, English and most Latin-script languages, so the default needs
no download. Other scripts use a per-script "mobile" model (PP-OCRv5,
PP-OCRv4 for Georgian) that RapidOCR fetches on first use.
"""

import os

from rga_ocr.engines import Engine

# Official onnxruntime wheels ship Microsoft's 1DS telemetry, on by default
# (docs/Privacy.md): a persistent device id and trace events uploaded over
# HTTPS. Only this variable, read once when the runtime initialises, keeps the
# uploader from being created at all, so it is set before anything imports
# onnxruntime (every path to the module comes through here). Set in the
# environment already: left alone.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

# languages the bundled multilingual model reads (primary subtags, lower case)
BUNDLED = set("""
zh ja en af az bs ca cs cy da de es et eu fi fr ga gl hr hu id is it ku la lb
lt lv mi ms mt nl no oc pl pt qu rm ro sr sk sl sq sv sw tl tr uz vi
""".split())

# other scripts: primary subtag -> RapidOCR recognition model (LangRec value)
# and the PP-OCR generation that ships it (rapidocr 3.10: only ka lacks a v5 model)
MODEL_VERSION = {"ka": "PP-OCRv4"}
MODEL_VERSION_DEFAULT = "PP-OCRv5"
SCRIPT_MODELS = {
    "ru": "cyrillic", "uk": "cyrillic", "be": "cyrillic", "bg": "cyrillic", "mk": "cyrillic",
    "kk": "cyrillic", "ky": "cyrillic", "mn": "cyrillic", "tg": "cyrillic",
    "ar": "arabic", "fa": "arabic", "ur": "arabic", "ps": "arabic", "ug": "arabic",
    "hi": "devanagari", "mr": "devanagari", "ne": "devanagari", "sa": "devanagari",
    "ko": "korean", "th": "th", "el": "el", "ta": "ta", "te": "te", "ka": "ka",
}


def model_for(langs):
    """'multi' for the bundled model, a LangRec value otherwise; raises on a
    mix of scripts or an unknown language."""
    models = set()
    for tag in langs:
        primary = tag.split("-")[0].split("_")[0].lower()
        if primary in BUNDLED:
            models.add("multi")
        elif primary in SCRIPT_MODELS:
            models.add(SCRIPT_MODELS[primary])
        else:
            raise ValueError(f"rapidocr has no model for language {tag!r}")
    if len(models) > 1:
        raise ValueError("rapidocr reads one script per run; mixed: " + ", ".join(sorted(models)))
    return models.pop() if models else "multi"


class RapidOCREngine(Engine):
    name = "rapidocr"
    extra = "rapidocr"
    modules = ("rapidocr", "onnxruntime")

    @classmethod
    def available(cls, langs):
        if not cls.installed():
            return False, "pip install 'rga-ocr[rapidocr]'"
        try:
            model_for(langs)
        except ValueError as e:
            return False, str(e)
        return True, ""

    @classmethod
    def lang_tag(cls, langs):
        return model_for(langs)

    def __init__(self, langs):
        super().__init__(langs)
        import logging
        from rapidocr import RapidOCR
        logging.getLogger("rapidocr").setLevel(logging.ERROR)
        params = {"Global.log_level": "error"}
        model = model_for(langs)
        if model != "multi":
            # rapidocr 3.x validates these as its own enums, not strings; the
            # per-script models exist only in the "mobile" tier (the default
            # "small" belongs to the PP-OCRv6 multilingual model)
            from rapidocr import LangRec, ModelType, OCRVersion
            params.update({"Rec.lang_type": LangRec(model),
                           "Rec.ocr_version": OCRVersion(MODEL_VERSION.get(model, MODEL_VERSION_DEFAULT)),
                           "Rec.model_type": ModelType.MOBILE})
        self.ocr = RapidOCR(params=params)

    def recognize(self, img):
        out = self.ocr(img)
        if out is None or out.boxes is None or out.txts is None:
            return []
        w, h = img.size
        lines = []
        for quad, text in zip(out.boxes, out.txts):
            if not text:
                continue
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            top, bottom = min(ys), max(ys)
            lines.append((top / h, min(xs) / w, (bottom - top) / h, str(text)))
        return lines


ENGINE = RapidOCREngine
