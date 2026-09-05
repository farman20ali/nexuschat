import os
import re
import zipfile
from io import BytesIO
from pathlib import Path


_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)


def safe_filename(name):
    base = Path(name).name.strip() or "file"
    cleaned = _UNSAFE.sub("_", base).strip(" .")
    return (cleaned[:180] or "file")


def zip_paths(file_paths):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in file_paths:
            archive.write(path, os.path.basename(path))
    return buffer.getvalue()
