# Security

## Supported versions

| version | supported |
|---------|-----------|
| 0.1.x   | yes       |

## Reporting a vulnerability

Please report vulnerabilities through GitHub's private vulnerability
reporting on this repository ("Security" tab, "Report a vulnerability")
rather than in a public issue. You should hear back within a week.

What counts: anything that makes `rga-ocr` read, write or delete files it
should not, execute content from a searched document, or leak document
contents off the machine. Crashes on malformed input are ordinary bugs
unless they lead to one of those.

`rga-ocr` runs `rga`, `rg`, `pandoc` and the OCR engines on whatever
documents you point it at. Decoding bugs in those tools and in the
libraries it imports (PDFium, libheif, Pillow, the ONNX models) are
reported upstream; this project pins no vulnerable versions knowingly and
updates its floors when an advisory calls for it.
