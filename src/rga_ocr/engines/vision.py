"""Apple Vision text recognition (macOS, PyObjC)."""

import io
import sys

from rga_ocr.engines import Engine


def macos_version():
    """(major, minor) of the running macOS, (0, 0) when unknown."""
    import platform
    ver = platform.mac_ver()[0]
    try:
        parts = [int(x) for x in ver.split(".")[:2]]
        return tuple(parts + [0] * (2 - len(parts)))
    except ValueError:
        return (0, 0)


class VisionEngine(Engine):
    name = "vision"
    extra = "vision"
    modules = ("Vision", "Quartz")

    @classmethod
    def available(cls, langs):
        if sys.platform != "darwin":
            return False, "macOS only"
        if macos_version() < (13, 0):
            return False, "needs macOS 13 or newer"
        if not cls.installed():
            return False, "pip install 'rga-ocr[vision]'"
        return True, ""

    def __init__(self, langs):
        super().__init__(langs)
        import Quartz as Q
        import Vision as V   # noqa: N814
        # PyObjC resolves attributes lazily; bind everything once up front.
        self.cf_data = Q.CFDataCreate
        self.src_from_data = Q.CGImageSourceCreateWithData
        self.image_at = Q.CGImageSourceCreateImageAtIndex
        self.handler_cls = V.VNImageRequestHandler
        self.request_cls = V.VNRecognizeTextRequest
        self.level_accurate = V.VNRequestTextRecognitionLevelAccurate

    def _cgimage(self, img):
        buf = io.BytesIO()
        img.save(buf, "PNG", compress_level=1)
        data = buf.getvalue()
        src = self.src_from_data(self.cf_data(None, data, len(data)), None)
        cg = self.image_at(src, 0, None) if src is not None else None
        if cg is None:
            raise RuntimeError("ImageIO could not read the image")
        return cg

    def recognize(self, img):
        req = self.request_cls.alloc().init()
        req.setRecognitionLevel_(self.level_accurate)
        req.setUsesLanguageCorrection_(True)
        if self.langs:
            req.setRecognitionLanguages_(self.langs)
        else:
            req.setAutomaticallyDetectsLanguage_(True)     # macOS 13+
            req.setRecognitionLanguages_(["en-US"])
        handler = self.handler_cls.alloc().initWithCGImage_options_(self._cgimage(img), None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok:
            raise RuntimeError(f"Vision request failed: {err}")
        lines = []
        for obs in req.results() or []:
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            box = obs.boundingBox()                  # normalised, origin bottom-left
            h = box.size.height
            top = 1.0 - (box.origin.y + h)           # flip to top-down
            lines.append((top, box.origin.x, h, cands[0].string()))
        return lines


ENGINE = VisionEngine
