"""Plain-text extraction from uploaded syllabus-style files.

extract_text(data, filename) -> str for .txt/.md/.html/.htm/.docx/.pdf.
Stdlib only; uses pypdf for PDFs when it happens to be installed, otherwise a
small built-in PDF text extractor (FlateDecode + ToUnicode CMaps).
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import zlib
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_OUTPUT_CHARS = 200_000
_MAX_INFLATE = 64 * 1024 * 1024
_TOTAL_INFLATE = 128 * 1024 * 1024  # total across all streams of one PDF


def extract_text(data: bytes, filename: str) -> str:
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("file too large (max 25 MB)")
    ext = posixpath.splitext((filename or "").lower())[1]
    if ext in (".txt", ".md", ".markdown"):
        text = _decode_text(data)
    elif ext in (".html", ".htm"):
        text = _html_to_text(_decode_text(data))
    elif ext == ".docx":
        text = _docx_to_text(data)
    elif ext == ".pdf":
        text = _pdf_to_text(data)
    else:
        raise ValueError(f"unsupported file type {ext or filename!r}")
    return _finish(text)


def _finish(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_OUTPUT_CHARS]


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.lstrip("﻿")


# ---------------------------------------------------------------- HTML

_BLOCK = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "tr", "section", "article", "header", "footer", "blockquote",
    "pre", "hr", "dl", "dt", "dd", "caption", "thead", "tbody", "tfoot",
}
_SKIP = {"script", "style", "head", "noscript", "template"}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.cells_in_row = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "tr":
            self.out.append("\n")
            self.cells_in_row = 0
        elif tag in ("td", "th"):
            if self.cells_in_row:
                self.out.append(" | ")
            self.cells_in_row += 1
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self.skip:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in _BLOCK and tag != "br":
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def _html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    p.close()
    lines = []
    for ln in "".join(p.out).split("\n"):
        ln = re.sub(r" {2,}", " ", ln).strip()
        ln = re.sub(r"^\|\s*|\s*\|$", "", ln).strip() if ln.startswith("|") or ln.endswith("|") else ln
        lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------- DOCX

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_para(p: ET.Element) -> str:
    parts: list[str] = []
    for el in p.iter():
        if el.tag == _W + "t":
            parts.append(el.text or "")
        elif el.tag == _W + "tab":
            parts.append("\t")
        elif el.tag in (_W + "br", _W + "cr"):
            parts.append("\n")
    return "".join(parts)


def _docx_block(el: ET.Element, out: list[str]) -> None:
    for child in el:
        if child.tag == _W + "p":
            out.append(_docx_para(child))
        elif child.tag == _W + "tbl":
            for tr in child.findall(_W + "tr"):
                cells = []
                for tc in tr.findall(_W + "tc"):
                    paras: list[str] = []
                    _docx_block(tc, paras)
                    cells.append(" ".join(s.strip() for s in paras if s.strip()))
                out.append(" | ".join(cells))
        elif child.tag in (_W + "sdt", _W + "sdtContent", _W + "body"):
            _docx_block(child, out)


def _docx_to_text(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        info = zf.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError("not a valid .docx file") from e
    if info.file_size > _MAX_INFLATE:
        raise ValueError("docx content too large")
    try:
        root = ET.fromstring(zf.read(info))
    except ET.ParseError as e:
        raise ValueError("docx document.xml is not valid XML") from e
    out: list[str] = []
    body = root.find(_W + "body")
    _docx_block(body if body is not None else root, out)
    return "\n".join(out)


# ---------------------------------------------------------------- PDF

def _pdf_to_text(data: bytes) -> str:
    if not data.lstrip()[:1024].startswith(b"%PDF") and b"%PDF" not in data[:1024]:
        raise ValueError("not a valid PDF file")
    try:
        import pypdf  # type: ignore
    except ImportError:
        pypdf = None
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                # Permission-restricted PDFs usually have an empty user password.
                try:
                    ok = bool(reader.decrypt(""))
                except Exception:
                    ok = False
                if not ok:
                    raise ValueError("encrypted PDFs are not supported")
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
            if text.strip():
                return text
            if reader.is_encrypted:
                return ""  # decrypted fine but no text; the stdlib path cannot read encrypted streams
        except ValueError:
            raise
        except Exception:
            pass  # fall through to the built-in extractor
    return _pdf_text_stdlib(data)


_OBJ_RE = re.compile(rb"(?<![\d])(\d+)\s+(\d+)\s+obj\b")
_REF_RE = re.compile(rb"(\d+)\s+\d+\s+R\b")


def _inflate(raw: bytes, limit: int = _MAX_INFLATE) -> bytes | None:
    limit = max(0, min(limit, _MAX_INFLATE))
    try:
        d = zlib.decompressobj()
        out = d.decompress(raw, limit)
        return out
    except zlib.error:
        # tolerate truncated/garbled tails
        try:
            d = zlib.decompressobj()
            return d.decompress(raw.strip(b"\r\n"), limit)
        except zlib.error:
            return None


def _balanced(buf: bytes, start: int) -> bytes:
    """Return the << ... >> dict starting at buf[start:] (start points at '<<')."""
    depth = 0
    i = start
    n = len(buf)
    while i < n - 1:
        two = buf[i:i + 2]
        if two == b"<<":
            depth += 1
            i += 2
        elif two == b">>":
            depth -= 1
            i += 2
            if depth == 0:
                return buf[start:i]
        else:
            i += 1
    return buf[start:]


class _Pdf:
    def __init__(self, data: bytes) -> None:
        self.objs: dict[int, tuple[bytes, bytes | None]] = {}  # num -> (dict/body, stream)
        self._budget = _TOTAL_INFLATE  # running cap on total inflated bytes
        self._scan(data)

    def _scan(self, data: bytes) -> None:
        for m in _OBJ_RE.finditer(data):
            num = int(m.group(1))
            body_start = m.end()
            sm = re.compile(rb"stream\r?\n").search(data, body_start, body_start + 4096 + 0)
            em = data.find(b"endobj", body_start)
            if em < 0:
                em = len(data)
            head_end = sm.start() if sm and sm.start() < em else em
            head = data[body_start:head_end]
            stream = None
            if sm and sm.start() < em:
                s = sm.end()
                lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", head)
                e = -1
                if lm:
                    cand = s + int(lm.group(1))
                    if data[cand:cand + 20].lstrip(b"\r\n ").startswith(b"endstream"):
                        e = cand
                if e < 0:
                    e = data.find(b"endstream", s)
                    if e < 0:
                        e = em
                    else:
                        while e > s and data[e - 1:e] in (b"\n", b"\r"):
                            e -= 1
                stream = data[s:e]
            self.objs[num] = (head, stream)
        # unpack object streams
        for num, (head, stream) in list(self.objs.items()):
            if stream is not None and b"/ObjStm" in head:
                dec = self.decode_stream(num)
                if dec is None:
                    continue
                nm = re.search(rb"/N\s+(\d+)", head)
                fm = re.search(rb"/First\s+(\d+)", head)
                if not (nm and fm):
                    continue
                n, first = int(nm.group(1)), int(fm.group(1))
                pairs = re.findall(rb"(\d+)\s+(\d+)", dec[:first])[:n]
                offs = [(int(a), int(b)) for a, b in pairs]
                for idx, (onum, off) in enumerate(offs):
                    end = offs[idx + 1][1] + first if idx + 1 < len(offs) else len(dec)
                    self.objs.setdefault(onum, (dec[first + off:end], None))

    def head(self, num: int) -> bytes:
        return self.objs.get(num, (b"", None))[0]

    def decode_stream(self, num: int) -> bytes | None:
        head, stream = self.objs.get(num, (b"", None))
        if stream is None:
            return None
        if b"/FlateDecode" in head or b"/Fl " in head or b"/Fl]" in head:
            if re.search(rb"/Filter\s*\[[^\]]*\].*?/Filter", head, re.S):
                return None
            if self._budget <= 0:
                return None
            out = _inflate(stream, self._budget)
            if out is None:
                return None
            self._budget -= len(out)
            pm = re.search(rb"/Predictor\s+(\d+)", head)
            if pm and int(pm.group(1)) >= 10:
                cm = re.search(rb"/Columns\s+(\d+)", head)
                out = _png_unpredict(out, int(cm.group(1)) if cm else 1)
            return out
        if re.search(rb"/Filter\s*(\[|/)", head):
            return None  # unsupported filter (DCT, LZW, ASCII85...)
        return stream

    # -- dict helpers
    def dict_value(self, d: bytes, key: bytes) -> bytes | None:
        """Raw value text for /Key in dict bytes d (handles refs, nested dicts)."""
        m = re.search(rb"/" + re.escape(key) + rb"(?![\w])\s*", d)
        if not m:
            return None
        i = m.end()
        if d[i:i + 2] == b"<<":
            return _balanced(d, i)
        if d[i:i + 1] == b"[":
            depth = 0
            for j in range(i, len(d)):
                if d[j:j + 1] == b"[":
                    depth += 1
                elif d[j:j + 1] == b"]":
                    depth -= 1
                    if depth == 0:
                        return d[i:j + 1]
            return d[i:]
        rm = _REF_RE.match(d, i)
        if rm:
            return rm.group(0)
        vm = re.match(rb"/?[^\s/<>\[\]]+", d[i:])
        return vm.group(0) if vm else None

    def resolve_dict(self, val: bytes | None) -> bytes:
        if val is None:
            return b""
        rm = _REF_RE.fullmatch(val.strip())
        if rm:
            return self.head(int(rm.group(1)))
        return val

    def page_fonts(self, page_num: int) -> dict[bytes, int]:
        num: int | None = page_num
        seen = set()
        while num is not None and num not in seen:
            seen.add(num)
            h = self.head(num)
            res = self.resolve_dict(self.dict_value(h, b"Resources"))
            fval = self.dict_value(res, b"Font") if res else None
            if fval:
                fd = self.resolve_dict(fval)
                return {
                    m.group(1): int(m.group(2))
                    for m in re.finditer(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+\d+\s+R", fd)
                }
            pm = self.dict_value(h, b"Parent")
            rm = _REF_RE.fullmatch(pm.strip()) if pm else None
            num = int(rm.group(1)) if rm else None
        return {}

    def page_contents(self, page_num: int) -> bytes:
        h = self.head(page_num)
        cv = self.dict_value(h, b"Contents")
        if not cv:
            return b""
        nums = [int(x) for x in _REF_RE.findall(cv)]
        chunks = []
        for n in nums:
            dec = self.decode_stream(n)
            if dec:
                chunks.append(dec)
        return b"\n".join(chunks)


def _png_unpredict(data: bytes, columns: int) -> bytes:
    row = columns + 1
    out = bytearray()
    prev = bytearray(columns)
    for i in range(0, len(data) - row + 1, row):
        ft = data[i]
        cur = bytearray(data[i + 1:i + row])
        if ft == 1:
            for j in range(1, columns):
                cur[j] = (cur[j] + cur[j - 1]) & 255
        elif ft == 2:
            for j in range(columns):
                cur[j] = (cur[j] + prev[j]) & 255
        elif ft == 3:
            for j in range(columns):
                left = cur[j - 1] if j else 0
                cur[j] = (cur[j] + (left + prev[j]) // 2) & 255
        elif ft == 4:
            for j in range(columns):
                a = cur[j - 1] if j else 0
                b = prev[j]
                c = prev[j - 1] if j else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[j] = (cur[j] + pr) & 255
        out += cur
        prev = cur
    return bytes(out)


# -- CMaps

def _hex_bytes(h: bytes) -> bytes:
    h = re.sub(rb"\s+", b"", h)
    if len(h) % 2:
        h += b"0"
    return bytes.fromhex(h.decode("ascii"))


def _utf16(b: bytes) -> str:
    try:
        return b.decode("utf-16-be")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def _parse_cmap(cm: bytes) -> tuple[dict[int, str], int]:
    mapping: dict[int, str] = {}
    code_len = 0
    for blk in re.findall(rb"begincodespacerange(.*?)endcodespacerange", cm, re.S):
        m = re.search(rb"<([0-9A-Fa-f\s]+)>", blk)
        if m:
            code_len = max(code_len, len(_hex_bytes(m.group(1))))
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cm, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]*)>", blk):
            mapping[int.from_bytes(_hex_bytes(a), "big")] = _utf16(_hex_bytes(b))
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cm, re.S):
        pos = 0
        pat = re.compile(rb"<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f\s]*>)")
        for m in pat.finditer(blk, pos):
            lo = int.from_bytes(_hex_bytes(m.group(1)), "big")
            hi = int.from_bytes(_hex_bytes(m.group(2)), "big")
            if hi - lo > 0xFFFF:
                continue
            tgt = m.group(3)
            if tgt.startswith(b"["):
                items = re.findall(rb"<([0-9A-Fa-f\s]*)>", tgt)
                for k, it in enumerate(items):
                    if lo + k <= hi:
                        mapping[lo + k] = _utf16(_hex_bytes(it))
            else:
                base = _hex_bytes(tgt[1:-1])
                if not base:
                    continue
                base_int = int.from_bytes(base, "big")
                width = len(base)
                for k in range(hi - lo + 1):
                    mapping[lo + k] = _utf16((base_int + k).to_bytes(width, "big"))
    return mapping, code_len


class _Font:
    def __init__(self, pdf: _Pdf, num: int) -> None:
        h = pdf.head(num)
        self.type0 = b"/Type0" in h
        self.map: dict[int, str] = {}
        self.code_len = 2 if self.type0 else 1
        self.widths: dict[int, float] = {}
        self.dw = 500.0 if not self.type0 else 1000.0
        try:
            self._load_widths(pdf, h)
        except Exception:
            pass
        tu = pdf.dict_value(h, b"ToUnicode")
        rm = _REF_RE.fullmatch(tu.strip()) if tu else None
        if rm:
            dec = pdf.decode_stream(int(rm.group(1)))
            if dec:
                self.map, cl = _parse_cmap(dec)
                if cl:
                    self.code_len = cl

    def _load_widths(self, pdf: "_Pdf", h: bytes) -> None:
        num_re = rb"-?\d+\.?\d*"
        if self.type0:
            dv = pdf.dict_value(h, b"DescendantFonts")
            rm = _REF_RE.search(dv or b"")
            if not rm:
                return
            dh = pdf.head(int(rm.group(1)))
            m = re.search(rb"/DW\s+(" + num_re + rb")", dh)
            if m:
                self.dw = float(m.group(1))
            wv = pdf.dict_value(dh, b"W")
            wv = pdf.resolve_dict(wv) if wv and _REF_RE.fullmatch(wv.strip()) else wv
            if wv:
                for m in re.finditer(rb"(\d+)\s*\[([^\]]*)\]|(\d+)\s+(\d+)\s+(" + num_re + rb")", wv):
                    if m.group(1) is not None:
                        c0 = int(m.group(1))
                        for k, w in enumerate(re.findall(num_re, m.group(2))):
                            self.widths[c0 + k] = float(w)
                    else:
                        lo, hi = int(m.group(3)), int(m.group(4))
                        if hi - lo <= 0xFFFF:
                            w = float(m.group(5))
                            for c in range(lo, hi + 1):
                                self.widths[c] = w
        else:
            fc = re.search(rb"/FirstChar\s+(\d+)", h)
            wv = pdf.dict_value(h, b"Widths")
            wv = pdf.resolve_dict(wv) if wv and _REF_RE.fullmatch(wv.strip()) else wv
            if fc and wv:
                for k, w in enumerate(re.findall(num_re, wv)):
                    self.widths[int(fc.group(1)) + k] = float(w)

    def advance(self, raw: bytes) -> float:
        n = self.code_len
        tot = 0.0
        for i in range(0, len(raw) - n + 1, n):
            code = int.from_bytes(raw[i:i + n], "big")
            tot += self.widths.get(code, self.dw)
        return tot

    def decode(self, raw: bytes) -> str:
        n = self.code_len
        out = []
        if n == 1:
            for b in raw:
                out.append(self.map.get(b, chr(b) if b >= 32 or b in (9, 10) else ""))
        else:
            for i in range(0, len(raw) - n + 1, n):
                code = int.from_bytes(raw[i:i + n], "big")
                ch = self.map.get(code)
                if ch is None:
                    ch = chr(code) if (not self.map and 32 <= code < 0xD800) else ""
                out.append(ch)
        return "".join(out)


# -- content streams

_TOKEN_RE = re.compile(
    rb"""
    (?P<ws>\s+|%[^\r\n]*)
  | (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<dictopen><<) | (?P<dictclose>>>)
  | (?P<lit>\()
  | (?P<arropen>\[) | (?P<arrclose>\])
  | (?P<name>/[^\s/<>\[\]()%]*)
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<op>[^\s/<>\[\]()%]+)
    """,
    re.X,
)
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


def _read_literal(buf: bytes, i: int) -> tuple[bytes, int]:
    """buf[i] == '('. Returns (bytes, index after closing paren)."""
    out = bytearray()
    depth = 1
    i += 1
    n = len(buf)
    while i < n:
        c = buf[i]
        if c == 0x5C:  # backslash
            i += 1
            if i >= n:
                break
            c = buf[i]
            if c in _ESC:
                out.append(_ESC[c])
            elif 0x30 <= c <= 0x37:
                j = i
                while j < n and j < i + 3 and 0x30 <= buf[j] <= 0x37:
                    j += 1
                out.append(int(buf[i:j], 8) & 255)
                i = j - 1
            elif c in (10, 13):
                if c == 13 and buf[i + 1:i + 2] == b"\n":
                    i += 1
            else:
                out.append(c)
        elif c == 0x28:
            depth += 1
            out.append(c)
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out.append(c)
        else:
            out.append(c)
        i += 1
    return bytes(out), n


def _tokens(buf: bytes):
    i, n = 0, len(buf)
    while i < n:
        if buf[i] == 0x28:
            s, i = _read_literal(buf, i)
            yield ("str", s)
            continue
        m = _TOKEN_RE.match(buf, i)
        if not m:
            i += 1
            continue
        i = m.end()
        k = m.lastgroup
        v = m.group()
        if k == "ws" or k in ("dictopen", "dictclose"):
            continue
        if k == "hex":
            yield ("str", _hex_bytes(v[1:-1]))
        elif k == "num":
            try:
                yield ("num", float(v))
            except ValueError:
                pass
        elif k == "name":
            yield ("name", v[1:])
        elif k == "arropen":
            yield ("[", None)
        elif k == "arrclose":
            yield ("]", None)
        else:
            yield ("op", v)


class _Line:
    """Collects fragments for one visual line, joining by horizontal gap."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def add(self, text: str, gap: float | None, size: float) -> None:
        if not text:
            return
        if self.parts and gap is not None:
            prev = self.parts[-1]
            if not (prev.endswith(" ") or text.startswith(" ")):
                if gap > 1.5 * size:
                    self.parts.append(" | ")
                elif gap > 0.3 * size:
                    self.parts.append(" ")
        self.parts.append(text)

    def text(self) -> str:
        return re.sub(r"[ \t]+", " ", "".join(self.parts)).strip()


def _content_text(content: bytes, fonts: dict[bytes, _Font]) -> str:
    lines: list[str] = []
    line = _Line()
    font: _Font | None = None
    size = 12.0
    tc = 0.0
    tz = 1.0
    a_sc = 1.0
    d_sc = 1.0
    lx = ly = 0.0     # text line origin
    pen = 0.0         # advance since origin, same units as lx
    have_pos = False
    leading = 0.0
    stack: list = []
    arr: list | None = None

    def flush():
        nonlocal line
        t = line.text()
        if t:
            lines.append(t)
        line = _Line()

    def move(nx: float, ny: float):
        """Set a new text-line origin; decide newline vs same line."""
        nonlocal lx, ly, pen, have_pos
        if have_pos and abs(ny - ly) > 1.0:
            flush()
            gap = None
        elif have_pos:
            gap = nx - (lx + pen)
        else:
            gap = None
        lx, ly, pen, have_pos = nx, ny, 0.0, True
        return gap

    pending_gap: float | None = None

    def show(raw: bytes):
        nonlocal pen, pending_gap
        f = font
        txt = f.decode(raw) if f else raw.decode("latin-1", "replace")
        line.add(txt, pending_gap, size * abs(a_sc))
        pending_gap = None
        n = len(raw) // (f.code_len if f else 1)
        # advance estimate: real widths if known, else half an em
        w = f.advance(raw) if f else n * 500.0
        pen += (w * size / 1000.0 + n * tc) * tz * abs(a_sc)

    for kind, val in _tokens(content):
        if kind == "[":
            arr = []
            continue
        if kind == "]":
            if arr is not None:
                stack.append(("arr", arr))
            arr = None
            continue
        if arr is not None:
            if kind in ("str", "num"):
                arr.append(val)
            continue
        if kind != "op":
            stack.append((kind, val))
            if len(stack) > 64:
                del stack[:32]
            continue
        op = val
        nums = [v for k, v in stack if k == "num"]
        if op == b"BT":
            a_sc = d_sc = 1.0
        elif op == b"ET":
            pass
        elif op == b"Tf":
            names = [v for k, v in stack if k == "name"]
            if names:
                font = fonts.get(names[-1])
            if nums:
                size = abs(nums[-1]) or size
        elif op == b"Tc" and nums:
            tc = nums[-1]
        elif op == b"Tz" and nums:
            tz = nums[-1] / 100.0
        elif op == b"TL" and nums:
            leading = nums[-1]
        elif op == b"Tm" and len(nums) >= 6:
            a_sc = nums[0] if nums[0] else 1.0
            d_sc = nums[3] if nums[3] else 1.0
            pending_gap = move(nums[4], nums[5])
        elif op in (b"Td", b"TD") and len(nums) >= 2:
            if op == b"TD":
                leading = -nums[1] * d_sc
            pending_gap = move(lx + nums[0] * a_sc, ly + nums[1] * d_sc)
        elif op == b"T*":
            pending_gap = move(lx, ly - leading * d_sc if leading else ly - size * d_sc)
        elif op == b"Tj" and stack and stack[-1][0] == "str":
            show(stack[-1][1])
        elif op == b"TJ" and stack and stack[-1][0] == "arr":
            for item in stack[-1][1]:
                if isinstance(item, bytes):
                    show(item)
                elif isinstance(item, float):
                    pen -= item / 1000.0 * size * tz * abs(a_sc)
                    if item < -250:
                        pending_gap = (pending_gap or 0.0) + (-item / 1000.0 * size * abs(a_sc))
        elif op in (b"'", b'"') and stack and stack[-1][0] == "str":
            pending_gap = move(lx, ly - leading * d_sc if leading else ly - size * d_sc)
            show(stack[-1][1])
        stack.clear()
    flush()
    return "\n".join(lines)


def _page_order(pdf: _Pdf) -> list[int]:
    pages = [n for n, (h, _) in pdf.objs.items()
             if re.search(rb"/Type\s*/Page(?![\w])", h)]
    # follow the page tree when possible, else object order
    roots = [n for n, (h, _) in pdf.objs.items() if re.search(rb"/Type\s*/Catalog", h)]
    ordered: list[int] = []

    def walk(num: int, depth=0):
        if depth > 32 or num in ordered:
            return
        h = pdf.head(num)
        if re.search(rb"/Type\s*/Pages(?![\w])", h):
            kv = pdf.dict_value(h, b"Kids")
            for k in _REF_RE.findall(kv or b""):
                walk(int(k), depth + 1)
        elif re.search(rb"/Type\s*/Page(?![\w])", h):
            ordered.append(num)

    if roots:
        pv = pdf.dict_value(pdf.head(roots[0]), b"Pages")
        rm = _REF_RE.fullmatch(pv.strip()) if pv else None
        if rm:
            walk(int(rm.group(1)))
    return ordered or sorted(pages)


def _pdf_text_stdlib(data: bytes) -> str:
    if re.search(rb"/Encrypt\s", data[-4096:]) or re.search(rb"trailer[^>]*?/Encrypt", data, re.S):
        raise ValueError("encrypted PDFs are not supported")
    pdf = _Pdf(data)
    font_cache: dict[int, _Font] = {}
    pages_out = []
    total = 0
    for pnum in _page_order(pdf):
        fonts = {}
        for name, fnum in pdf.page_fonts(pnum).items():
            if fnum not in font_cache:
                font_cache[fnum] = _Font(pdf, fnum)
            fonts[name] = font_cache[fnum]
        txt = _content_text(pdf.page_contents(pnum), fonts)
        if txt:
            pages_out.append(txt)
            total += len(txt)
            if total > MAX_OUTPUT_CHARS:
                break
    return "\n\n".join(pages_out)
