"""Plain text out of an uploaded CV (PDF, Word .docx or text), with hard size limits.

The file is read in memory and dropped: the caller keeps only the skills found in the text.
A CV is typed by a stranger, so every format is read defensively: sizes capped before
unpacking, no macros or external references followed, and a page cap on PDFs.
"""

import io
import re
import zipfile

from defusedxml import ElementTree
from pypdf import PdfReader

from erio_api.errors import ApiError

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 15
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 30_000
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _unreadable(why: str) -> ApiError:
    return ApiError(422, "unreadable_cv", why)


def _pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise _unreadable("that PDF is protected by a lock")
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n".join(page.extract_text() or "" for page in pages)
    except ApiError:
        raise
    except Exception as error:  # a damaged file can raise nearly anything
        raise _unreadable("that PDF could not be read") from error


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_XML_BYTES:
                raise _unreadable("that document is too large to read")
            with archive.open(info) as part:
                root = ElementTree.fromstring(part.read(MAX_XML_BYTES + 1))
    except ApiError:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, ElementTree.ParseError) as error:
        raise _unreadable("that Word file could not be read") from error
    lines = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        lines.append("".join(node.text or "" for node in paragraph.iter(f"{WORD_NS}t")))
    return "\n".join(lines)


def extract_text(filename: str, data: bytes) -> str:
    """The text of a ``.pdf``, ``.docx``, ``.txt`` or ``.md`` file, or a 4xx ApiError."""
    if len(data) > MAX_FILE_BYTES:
        raise ApiError(
            413, "too_large", f"the CV file is over {MAX_FILE_BYTES // (1024 * 1024)} MB"
        )
    name = filename.lower()
    if name.endswith(".pdf") or data.startswith(b"%PDF"):
        text = _pdf(data)
    elif name.endswith(".docx") or data.startswith(b"PK"):
        text = _docx(data)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ApiError(415, "unsupported_cv", "send a PDF, Word (.docx) or text file")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        raise _unreadable("no text found; a scanned image needs to be typed or pasted instead")
    return text[:MAX_TEXT_CHARS]
