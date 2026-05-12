import os
import urllib.parse


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def _server_port(server, fallback=8765):
    parsed = urllib.parse.urlparse(server)
    return parsed.port or fallback


DBLP_SERVER = "http://127.0.0.1:8765"
DBLP_HOST = "0.0.0.0"
DBLP_PORT = _server_port(DBLP_SERVER)
DBLP_TOKEN = ""
DBLP_UPDATE_HOUR = 3
DB_PATH = ROOT_DIR

try:
    import settings_local as _local_settings
except ImportError:
    _local_settings = None

if _local_settings is not None:
    DBLP_SERVER = getattr(_local_settings, "DBLP_SERVER", DBLP_SERVER)
    DBLP_HOST = getattr(_local_settings, "DBLP_HOST", DBLP_HOST)
    DBLP_PORT = getattr(_local_settings, "DBLP_PORT", _server_port(DBLP_SERVER, DBLP_PORT))
    DBLP_TOKEN = getattr(_local_settings, "DBLP_TOKEN", DBLP_TOKEN)
    DBLP_UPDATE_HOUR = getattr(_local_settings, "DBLP_UPDATE_HOUR", DBLP_UPDATE_HOUR)
    DB_PATH = getattr(_local_settings, "DB_PATH", DB_PATH)

DBLP_SERVER = os.environ.get("DBLP_SERVER", DBLP_SERVER)
DBLP_HOST = os.environ.get("DBLP_HOST", DBLP_HOST)
DBLP_PORT = int(os.environ.get("DBLP_PORT", str(_server_port(DBLP_SERVER, DBLP_PORT))))
DBLP_TOKEN = os.environ.get("DBLP_TOKEN", DBLP_TOKEN)
DBLP_UPDATE_HOUR = int(os.environ.get("DBLP_UPDATE_HOUR", str(DBLP_UPDATE_HOUR)))
DB_PATH = os.environ.get("DB_PATH", DB_PATH)
