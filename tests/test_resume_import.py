import base64
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter

from stageradar.resume_import import extract_resume


def encoded(data):
    return base64.b64encode(data).decode()


def test_import_text_and_word():
    assert extract_resume("cv.txt", encoded("Python sécurité".encode())) == "Python sécurité"
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Python</w:t></w:r></w:p></w:body></w:document>',
        )
    assert extract_resume("CV.DOCX", encoded(data.getvalue())) == "Python"


def test_empty_pdf_and_unsupported_file():
    data = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(data)
    with pytest.raises(ValueError, match="Aucun texte"):
        extract_resume("scan.pdf", encoded(data.getvalue()))
    with pytest.raises(ValueError, match="Formats acceptés"):
        extract_resume("cv.exe", encoded(b"abc"))
    with pytest.raises(ValueError):
        extract_resume("cv.txt", "%%")
