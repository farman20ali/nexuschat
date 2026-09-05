import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_config_path() -> Path:
    if "NEXUSCHAT_CONFIG_PATH" in os.environ:
        return Path(os.environ["NEXUSCHAT_CONFIG_PATH"]).expanduser().resolve()
    
    local_env = ROOT / ".env"
    if (ROOT / "pyproject.toml").is_file() or local_env.is_file():
        return local_env

    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        config_dir = base / "NexusChat"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        config_dir = base / "nexuschat"

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.env"


def load_env(path=None):
    from shared.auth import decrypt_config_val
    env_path = Path(path) if path else get_config_path()
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value.startswith("enc:"):
            value = decrypt_config_val(value)
        if key and key not in os.environ:
            os.environ[key] = value



def resolve_path(value, default):
    raw = value if value is not None else default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def get_default_data_dir():
    # If running in local source repository (dev mode), keep data inside repository
    if (ROOT / "pyproject.toml").is_file() or (ROOT / ".env").is_file():
        return ROOT / "data"
    
    # Otherwise, use platform OS-standard user data directory
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "NexusChat" / "data"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
        return base / "nexuschat" / "data"


load_env()

DEFAULT_DATA = get_default_data_dir()
DATA_DIR = resolve_path(os.environ.get("CHAT_DATA_DIR"), DEFAULT_DATA)
FILE_DIR = resolve_path(os.environ.get("CHAT_FILE_DIR"), DATA_DIR / "files")


def set_file_dir(path_str):
    global FILE_DIR
    if path_str:
        path = Path(path_str).expanduser().resolve()
        FILE_DIR = path
        FILE_DIR.mkdir(parents=True, exist_ok=True)


DB_HOST = os.environ.get("CHAT_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("CHAT_DB_PORT", "5433"))
DB_NAME = os.environ.get("CHAT_DB_NAME", "tkinter")
DB_USER = os.environ.get("CHAT_DB_USER", "postgres")
DB_PASSWORD = os.environ.get("CHAT_DB_PASSWORD", "admin123")

TCP_PORT = int(os.environ.get("CHAT_TCP_PORT", "8082"))
DISCOVERY_PORT = int(os.environ.get("CHAT_DISCOVERY_PORT", "8083"))
