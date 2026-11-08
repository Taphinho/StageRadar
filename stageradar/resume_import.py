import base64
from io import BytesIO
from pathlib import PurePath
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

MAX_FILE_SIZE = 5_000_000


def extract_resume(filename: str, content: str) -> str:
    try:
        data = base64.b64decode(content, validate=True)
    except ValueError:
        raise ValueError("Fichier non valide.") from None
    if not data or len(data) > MAX_FILE_SIZE:
        raise ValueError("Le CV doit faire moins de 5 Mo.")
    suffix = PurePath(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("Le PDF est protégé. Importez une version sans mot de passe.")
            if len(reader.pages) > 30:
                raise ValueError("Le CV doit contenir au maximum 30 pages.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif suffix == ".docx":
            with ZipFile(BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 5_000_000:
                    raise ValueError("Document trop volumineux après décompression.")
                xml = archive.read(info)
            if b"<!DOCTYPE" in xml:
                raise ValueError("Document non valide.")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            text = "\n".join("".join(p.itertext()) for p in root.iter(ns + "p"))
        elif suffix == ".txt":
            text = data.decode("utf-8-sig")
        else:
            raise ValueError("Formats acceptés : PDF, DOCX et TXT.")
    except ValueError:
        raise
    except Exception:
        raise ValueError(
            "Impossible de lire ce fichier. Essayez un PDF texte, DOCX ou TXT."
        ) from None
    text = text.strip()
    if not text:
        raise ValueError(
            "Aucun texte détecté. Pour un CV scanné, importez une version contenant du texte ou collez-le ci-dessous."
        )
    if len(text) > 60_000:
        raise ValueError("Le texte du CV dépasse 60 000 caractères.")
    return text
