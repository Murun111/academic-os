import io
import zipfile
from pathlib import Path

import pytest

from backend.services import text_extract as te
from backend.services.text_extract import extract_text

FIX = Path(__file__).parent / "fixtures" / "syllabus"


def _read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_txt_utf8_and_bom():
    assert extract_text(b"\xef\xbb\xbfHello \xc3\xa9", "a.txt") == "Hello é"


def test_txt_latin1_fallback():
    assert extract_text("café".encode("latin-1"), "a.md") == "café"


def test_unsupported_type():
    with pytest.raises(ValueError, match="unsupported file type"):
        extract_text(b"x", "a.xyz")


def test_input_cap():
    with pytest.raises(ValueError):
        extract_text(b"x" * (te.MAX_INPUT_BYTES + 1), "a.txt")


def test_output_cap():
    out = extract_text(b"a" * (te.MAX_OUTPUT_CHARS + 500), "a.txt")
    assert len(out) == te.MAX_OUTPUT_CHARS


def test_html_blocks_and_tables():
    html = (b"<html><head><title>T</title><style>p{}</style></head><body>"
            b"<h1>Course</h1><p>Intro</p><table><tr><th>Item</th><th>Due</th></tr>"
            b"<tr><td>Quiz 1</td><td>Sept 10</td></tr></table><script>x()</script></body></html>")
    out = extract_text(html, "s.html")
    lines = out.split("\n")
    assert "Course" in lines and "Intro" in lines
    assert "Item | Due" in lines
    assert "Quiz 1 | Sept 10" in lines
    assert "x()" not in out and "p{}" not in out


def test_html_fixture():
    out = extract_text(_read("calc150.html"), "calc150.html")
    assert "Problem Set 1" in out and "Sept 8" in out


def test_bio_txt_fixture():
    out = extract_text(_read("bio101.txt"), "bio101.txt")
    assert "Sept" in out or "September" in out


def test_docx_fixture():
    out = extract_text(_read("calc150.docx"), "calc150.docx")
    assert "CALC 150" in out and "Total Course Points: 500" in out


def test_docx_table_rows():
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    xml = (f'<w:document {ns}><w:body><w:p><w:r><w:t>Title</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    assert extract_text(buf.getvalue(), "x.docx") == "Title\nA | B"


def test_docx_invalid():
    with pytest.raises(ValueError):
        extract_text(b"not a zip", "x.docx")


@pytest.mark.parametrize("name,phrases", [
    ("hist210.pdf", ["HIST 210", "Midterm Exam", "Week 6", "Essay 1", "Fall 2026"]),
    ("calc150.pdf", ["CALC 150", "Problem Set 1 | Sept 8", "Quiz 2: Derivatives", "Oct 20", "Dec 14"]),
])
def test_pdf_stdlib_extractor(name, phrases):
    out = te._pdf_text_stdlib(_read(name))
    for ph in phrases:
        assert ph in out, ph


@pytest.mark.parametrize("name", ["hist210.pdf", "calc150.pdf"])
def test_pdf_public_api(name):
    out = extract_text(_read(name), name)
    assert "Fall 2026" in out and "September" in out


def test_pdf_stdlib_when_pypdf_missing(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "pypdf":
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert "HIST 210" in extract_text(_read("hist210.pdf"), "h.pdf")


def test_pdf_invalid():
    with pytest.raises(ValueError):
        extract_text(b"garbage", "x.pdf")


def test_cmap_bfrange_array_and_bfchar():
    cm = (b"1 begincodespacerange <0000> <FFFF> endcodespacerange "
          b"beginbfchar <0003> <0020> endbfchar "
          b"beginbfrange <0010> <0012> [<0041> <0042> <0043>] <0020> <0022> <0061> endbfrange")
    m, cl = te._parse_cmap(cm)
    assert cl == 2
    assert m[3] == " " and m[0x10] == "A" and m[0x12] == "C" and m[0x21] == "b"


def test_literal_string_escapes():
    s, end = te._read_literal(b"(a\\(b\\)\\n\\101(c)) rest", 0)
    assert s == b"a(b)\nA(c)"


def test_simple_content_stream():
    out = te._content_text(b"BT /F1 12 Tf 1 0 0 1 10 100 Tm (Hello) Tj 0 -14 Td [(Wor) -20 (ld)] TJ ET", {})
    assert out == "Hello\nWorld"


def test_docx_nested_table_rows_not_duplicated():
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    inner = "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>INNER</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    xml = (f'<w:document {W}><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>OUTER</w:t></w:r></w:p>'
           f'{inner}</w:tc></w:tr></w:tbl></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    out = extract_text(buf.getvalue(), "a.docx")
    assert out.count("INNER") == 1


def test_pdf_inflate_total_budget(monkeypatch):
    import zlib
    monkeypatch.setattr(te, "_TOTAL_INFLATE", 100)
    raw = zlib.compress(b"A" * 80)
    pdf = te._Pdf.__new__(te._Pdf)
    pdf._budget = te._TOTAL_INFLATE
    pdf.objs = {1: (b"<< /Filter /FlateDecode >>", raw), 2: (b"<< /Filter /FlateDecode >>", raw)}
    assert pdf.decode_stream(1) == b"A" * 80
    second = pdf.decode_stream(2)
    assert second is None or len(second) <= 20  # capped by the remaining budget


def test_pdf_empty_password_encrypted_is_readable():
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    w.encrypt("", owner_password="owner", use_128bit=True)  # RC4, no extra deps
    buf = io.BytesIO()
    w.write(buf)
    # decrypts with the empty password; a blank page then yields no text, not an "encrypted" error
    assert extract_text(buf.getvalue(), "a.pdf").strip() == ""


def test_pdf_obj_flood_without_endobj_is_linear():
    import time

    data = b"%PDF-1.4\n" + b"1 0 obj " * 40000  # ~320 KB, no endobj anywhere
    t = time.perf_counter()
    try:
        te._pdf_text_stdlib(data)
    except ValueError:
        pass
    assert time.perf_counter() - t < 2.0  # was ~6s+ (quadratic)
