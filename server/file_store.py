import logging
import shutil
import uuid
from pathlib import Path

from shared.files import safe_filename
from server import settings

logger = logging.getLogger(__name__)


class FileStore:
    def __init__(self, root=None):
        self.root = Path(root or settings.FILE_DIR)
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp = self.root / "tmp"
        self.temp.mkdir(parents=True, exist_ok=True)

    def new_temp(self):
        path = self.temp / f"{uuid.uuid4().hex}.part"
        return path

    def finalize(self, temp_path, original_name):
        stored_name = f"{uuid.uuid4().hex}_{safe_filename(original_name)}"
        dest = self.root / stored_name
        shutil.move(str(temp_path), str(dest))
        return stored_name, dest

    def path_for(self, stored_name):
        name = Path(stored_name).name
        if name != stored_name:
            raise ValueError("invalid stored name")
        return self.root / name

    def delete(self, stored_name):
        path = self.path_for(stored_name)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not delete %s: %s", path, exc)
