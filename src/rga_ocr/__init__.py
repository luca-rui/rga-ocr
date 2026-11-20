"""rga-ocr: file-name search plus ripgrep-all content search with OCR adapters."""

PROG = "rga-ocr"
VERSION = "0.2.6"
ENV_PREFIX = "RGA_OCR_"
# version of the three rga adapters: raised when the text they put out for
# the same file changes, so that rga and the content cache read files again
ADAPTER_VERSION = 3
