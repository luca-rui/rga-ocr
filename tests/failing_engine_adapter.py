"""Stand-in for the adapter in the rga config of one end-to-end test: the
adapter itself, with an OCR engine that fails while the file named by
ADAPTER_ENGINE_DOWN exists (a model download without network, say)."""
import os
import sys

from rga_ocr import adapter

real = adapter.OCR


def ocr():
    if os.path.exists(os.environ.get("ADAPTER_ENGINE_DOWN", "")):
        raise adapter.EngineFailure(OSError("model fetch failed"))
    return real()


adapter.OCR = ocr
adapter.main()
for stream in (sys.stdout, sys.stderr):
    try:
        stream.flush()
    except (OSError, ValueError):
        pass
os._exit(0)
