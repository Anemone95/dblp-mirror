import importlib.util
import os
import urllib.parse
from types import SimpleNamespace

import settings


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SETTINGS_PATH = os.path.join(ROOT_DIR, "settings_local.py")

if os.path.exists(LOCAL_SETTINGS_PATH):
    spec = importlib.util.spec_from_file_location("settings_local", LOCAL_SETTINGS_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {LOCAL_SETTINGS_PATH}")
    settings_local = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings_local)
else:
    settings_local = None


CONFIG_KEYS = (
    "DBLP_SERVER",
    "DBLP_TOKEN",
    "DBLP_UPDATE_HOUR",
    "DB_PATH",
)


def _value(name):
    if settings_local is not None and hasattr(settings_local, name):
        return getattr(settings_local, name)
    return getattr(settings, name)


def load_config():
    values = {name: _value(name) for name in CONFIG_KEYS}
    if values["DB_PATH"] is None:
        values["DB_PATH"] = ROOT_DIR
    parsed_server = urllib.parse.urlparse(values["DBLP_SERVER"])
    values["SERVER_HOST"] = parsed_server.hostname or "127.0.0.1"
    values["SERVER_PORT"] = parsed_server.port or _default_port(parsed_server.scheme)
    values["DBLP_UPDATE_HOUR"] = int(values["DBLP_UPDATE_HOUR"])
    return SimpleNamespace(**values)


def _default_port(scheme):
    if scheme == "https":
        return 443
    return 80


CONFIG = load_config()
