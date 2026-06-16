from __future__ import annotations

import sys
from pathlib import Path


def extract_with_pdfplumber(path: Path) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"\n\n[Page {idx}]\n{text}")
    return "".join(pages)


def extract_with_pypdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"\n\n[Page {idx}]\n{text}")
    return "".join(pages)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_pdf_text.py <pdf>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 2
    try:
        text = extract_with_pdfplumber(path)
    except Exception:
        text = extract_with_pypdf(path)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
