#!/usr/bin/env python3

import argparse
from datetime import datetime, timedelta
import gzip
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

import settings


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DBLP_SCRIPT = os.path.join(ROOT_DIR, "dblp")
XML_FILENAME = "dblp.xml.gz"


def load_dblp_module() -> Any:
    loader = importlib.machinery.SourceFileLoader("dblp_core", DBLP_SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Unable to load {DBLP_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


dblp = load_dblp_module()


class DblpService:
    def __init__(
        self,
        *,
        xml_path: str,
        index_path: str,
        token: str,
        update_hour: int,
    ) -> None:
        self.xml_path = xml_path
        self.index_path = index_path
        self.token = token
        self.update_hour = update_hour
        self.lock = threading.RLock()
        self.last_update: Optional[Dict[str, Any]] = None
        self.update_in_progress = False

    def query(self, title: str, limit: int) -> List[Dict[str, Any]]:
        with self.lock:
            if not os.path.exists(self.index_path):
                raise FileNotFoundError(f"DBLP index not found: {self.index_path}")
            connection = dblp.connect_index(self.index_path, readonly=True)
            try:
                metadata = dblp.read_index_metadata(connection)
                if metadata.get("schema_version") != str(dblp.INDEX_SCHEMA_VERSION):
                    raise RuntimeError("index schema is stale")
                citekeys = dblp.find_match_keys_in_index(connection, title)[:limit]
                records = dblp.cached_records(connection, citekeys)
                bibtex_by_key = dblp.indexed_bibtex(connection, citekeys)
            finally:
                connection.close()

        items = []
        for citekey in citekeys:
            record = records.get(citekey)
            bibtex = bibtex_by_key.get(citekey)
            if record is None or bibtex is None:
                continue

            authors = record.get("author", [])
            if isinstance(authors, str):
                author_text = authors
            elif isinstance(authors, list):
                author_text = ", ".join(str(author) for author in authors[:8])
                if len(authors) > 8:
                    author_text += ", ..."
            else:
                author_text = ""

            year = record.get("year")
            subtitle_parts = [part for part in (author_text, str(year) if year else "") if part]
            items.append(
                {
                    "title": str(record.get("title", citekey)),
                    "subtitle": " | ".join(subtitle_parts),
                    "citekey": citekey,
                    "bibtex": bibtex,
                    "arg": bibtex,
                }
            )

        return items

    def health(self) -> Dict[str, Any]:
        with self.lock:
            exists = os.path.exists(self.index_path)
            response: Dict[str, Any] = {
                "ok": exists,
                "xml_path": self.xml_path,
                "index_path": self.index_path,
                "last_update": self.last_update,
            }
            if not exists:
                return response

            connection = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(self.index_path))}?mode=ro", uri=True)
            try:
                metadata = dblp.read_index_metadata(connection)
                record_count = connection.execute("SELECT count(*) FROM records").fetchone()[0]
            finally:
                connection.close()

            response.update(
                {
                    "metadata": metadata,
                    "record_count": record_count,
                }
            )
            return response

    def index_metadata(self) -> Dict[str, Any]:
        with self.lock:
            if not os.path.exists(self.index_path):
                raise FileNotFoundError(self.index_path)
            stat_result = os.stat(self.index_path)
            connection = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(self.index_path))}?mode=ro", uri=True)
            try:
                metadata = dblp.read_index_metadata(connection)
                record_count = connection.execute("SELECT count(*) FROM records").fetchone()[0]
            finally:
                connection.close()

            return {
                "index_path": self.index_path,
                "index_size": stat_result.st_size,
                "index_mtime_ns": stat_result.st_mtime_ns,
                "schema_version": dblp.INDEX_SCHEMA_VERSION,
                "metadata": metadata,
                "record_count": record_count,
            }

    def stream_compressed_index(self, output) -> None:
        with self.lock:
            source = open(self.index_path, "rb")
        with source, gzip.GzipFile(fileobj=output, mode="wb", compresslevel=6) as compressed:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                compressed.write(chunk)

    def update_once(self) -> Dict[str, Any]:
        started = datetime.now()
        result: Dict[str, Any] = {
            "started_at": started.isoformat(timespec="seconds"),
            "ok": False,
        }

        xml_dir = os.path.dirname(os.path.abspath(self.xml_path)) or "."
        index_dir = os.path.dirname(os.path.abspath(self.index_path)) or "."
        os.makedirs(xml_dir, exist_ok=True)
        os.makedirs(index_dir, exist_ok=True)

        xml_fd, tmp_xml = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.xml_path)}.",
            suffix=".tmp",
            dir=xml_dir,
        )
        index_fd, tmp_index = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.index_path)}.",
            suffix=".tmp",
            dir=index_dir,
        )
        os.close(xml_fd)
        os.close(index_fd)

        try:
            used_url = dblp.download_with_fallback(dblp.DEFAULT_XML_URLS, tmp_xml)
            connection = dblp.connect_index(tmp_index)
            try:
                dblp.initialize_index(connection)
                dblp.rebuild_index_with_metadata_path(connection, tmp_xml, self.xml_path)
            finally:
                connection.close()

            with self.lock:
                dblp.remove_sqlite_sidecars(self.index_path)
                os.replace(tmp_xml, self.xml_path)
                os.replace(tmp_index, self.index_path)

            finished = datetime.now()
            result.update(
                {
                    "ok": True,
                    "finished_at": finished.isoformat(timespec="seconds"),
                    "elapsed_seconds": round((finished - started).total_seconds(), 3),
                    "url": used_url,
                    "xml_size": os.path.getsize(self.xml_path),
                    "index_size": os.path.getsize(self.index_path),
                }
            )
            return result
        except Exception as exc:
            result.update(
                {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            return result
        finally:
            for path in (
                tmp_xml,
                tmp_index,
                f"{tmp_index}-wal",
                f"{tmp_index}-shm",
                f"{tmp_index}-journal",
            ):
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass

    def start_background_update(self) -> bool:
        with self.lock:
            if self.update_in_progress:
                return False
            self.update_in_progress = True
            self.last_update = {
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "ok": False,
                "status": "running",
            }

        def run() -> None:
            result = self.update_once()
            with self.lock:
                self.last_update = result
                self.update_in_progress = False

        threading.Thread(target=run, daemon=True).start()
        return True

    def run_update_loop(self) -> None:
        while True:
            now = datetime.now()
            next_run = now.replace(hour=self.update_hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            time.sleep((next_run - now).total_seconds())
            self.last_update = self.update_once()


def make_handler(service: DblpService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "dblp-search/1.0"

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if parsed.path == "/health":
                self.write_json(service.health())
                return

            if parsed.path == "/index/metadata":
                if not self.authorized(params):
                    self.write_json({"error": "unauthorized"}, status=401)
                    return
                try:
                    self.write_json(service.index_metadata())
                except Exception as exc:
                    self.write_json({"error": str(exc)}, status=500)
                return

            if parsed.path == "/index.gz":
                if not self.authorized(params):
                    self.write_json({"error": "unauthorized"}, status=401)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", 'attachment; filename="dblp.xml.gz.idx.sqlite3.gz"')
                self.end_headers()
                try:
                    service.stream_compressed_index(self.wfile)
                except BrokenPipeError:
                    pass
                return

            if parsed.path != "/query":
                self.write_json({"error": "not found"}, status=404)
                return

            if not self.authorized(params):
                self.write_json({"error": "unauthorized"}, status=401)
                return

            query = params.get("q", [""])[0].strip()
            if len(query) < 2:
                self.write_json({"items": []})
                return

            try:
                limit = int(params.get("limit", ["10"])[0])
            except ValueError:
                limit = 10
            limit = max(1, min(limit, 50))

            try:
                self.write_json({"items": service.query(query, limit)})
            except FileNotFoundError as exc:
                self.write_json({"error": str(exc)}, status=503)
            except Exception as exc:
                self.write_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/update":
                self.write_json({"error": "not found"}, status=404)
                return
            if not self.authorized(params):
                self.write_json({"error": "unauthorized"}, status=401)
                return
            service.last_update = service.update_once()
            self.write_json(service.last_update)

        def authorized(self, params: Dict[str, List[str]]) -> bool:
            if not service.token:
                return True
            expected = service.token
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {expected}":
                return True
            if self.headers.get("X-DBLP-Token") == expected:
                return True
            return params.get("token", [""])[0] == expected

        def write_json(self, payload: Dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}", file=sys.stderr)

    return Handler


def build_parser() -> argparse.ArgumentParser:
    db_path = os.environ.get("DB_PATH", settings.DB_PATH)
    parser = argparse.ArgumentParser(prog="server.py")
    parser.add_argument("--host", default=os.environ.get("DBLP_HOST", settings.DBLP_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DBLP_PORT", str(settings.DBLP_PORT))))
    parser.add_argument("--db-path", default=db_path)
    parser.add_argument("--token", default=os.environ.get("DBLP_TOKEN", settings.DBLP_TOKEN))
    parser.add_argument(
        "--update-hour",
        type=int,
        default=int(os.environ.get("DBLP_UPDATE_HOUR", str(settings.DBLP_UPDATE_HOUR))),
        help="Local hour of day for the daily DBLP update, 0-23",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Serve queries without starting the daily update thread",
    )
    parser.add_argument(
        "--no-initial-update",
        action="store_true",
        help="Do not start an immediate background update when the index is missing",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    xml_path = os.path.join(args.db_path, XML_FILENAME)
    index_path = dblp.default_index_path(xml_path)

    service = DblpService(
        xml_path=xml_path,
        index_path=index_path,
        token=args.token,
        update_hour=max(0, min(args.update_hour, 23)),
    )

    if not args.no_scheduler:
        updater = threading.Thread(target=service.run_update_loop, daemon=True)
        updater.start()

    if not args.no_scheduler and not args.no_initial_update and not os.path.exists(index_path):
        service.start_background_update()

    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(f"Serving DBLP search on http://{args.host}:{args.port}", file=sys.stderr)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
