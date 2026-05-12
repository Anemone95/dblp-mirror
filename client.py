#!/usr/bin/env python3

import argparse
import gzip
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List

import settings


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DBLP_SCRIPT = os.path.join(ROOT_DIR, "dblp")
REQUEST_TIMEOUT = 20
XML_FILENAME = "dblp.xml.gz"


def load_dblp_module() -> Any:
    loader = importlib.machinery.SourceFileLoader("dblp_core_client", DBLP_SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Unable to load {DBLP_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


dblp = load_dblp_module()


def alfred_items(message: str, subtitle: str = "", *, valid: bool = False) -> Dict[str, Any]:
    return {
        "items": [
            {
                "title": message,
                "subtitle": subtitle,
                "valid": valid,
            }
        ]
    }


def request_url(server: str, path: str, token: str, query: Dict[str, str] | None = None) -> urllib.request.Request:
    url = f"{server.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return request


def query_server(server: str, token: str, query: str, limit: int) -> Dict[str, Any]:
    request = request_url(server, "/query", token, {"q": query, "limit": str(limit)})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def record_items(records: Dict[str, Dict[str, object]], bibtex_by_key: Dict[str, str], citekeys: Iterable[str]) -> List[Dict[str, Any]]:
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


def query_local(index_path: str, query: str, limit: int) -> Dict[str, Any]:
    connection = dblp.connect_index(index_path, readonly=True)
    try:
        metadata = dblp.read_index_metadata(connection)
        if metadata.get("schema_version") != str(dblp.INDEX_SCHEMA_VERSION):
            raise RuntimeError("local index schema is stale")
        citekeys = dblp.find_match_keys_in_index(connection, query)[:limit]
        records = dblp.cached_records(connection, citekeys)
        bibtex_by_key = dblp.indexed_bibtex(connection, citekeys)
    finally:
        connection.close()
    return {"items": record_items(records, bibtex_by_key, citekeys)}


def query_with_fallback(query: str, limit: int) -> Dict[str, Any]:
    db_path = os.environ.get("DB_PATH", settings.DB_PATH)
    index_path = dblp.default_index_path(os.path.join(db_path, XML_FILENAME))
    if index_path and os.path.exists(index_path):
        try:
            return query_local(index_path, query, limit)
        except Exception as exc:
            print(f"Local DBLP index failed, falling back to server: {exc}", file=sys.stderr)

    server = os.environ.get("DBLP_SERVER", settings.DBLP_SERVER).strip()
    token = os.environ.get("DBLP_TOKEN", settings.DBLP_TOKEN)
    if not server:
        return alfred_items("DBLP server is not configured", "Set DBLP_SERVER in settings.py")

    try:
        payload = query_server(server, token, query, limit)
    except urllib.error.HTTPError as exc:
        return alfred_items(f"DBLP server error: HTTP {exc.code}", exc.reason)
    except Exception as exc:
        return alfred_items(f"DBLP server error: {exc}", "Check settings.py")

    if "error" in payload and "items" not in payload:
        return alfred_items(f"DBLP server error: {payload['error']}", "Try again later")
    return {"items": payload.get("items", [])}


def pull_index() -> int:
    server = os.environ.get("DBLP_SERVER", settings.DBLP_SERVER).strip()
    token = os.environ.get("DBLP_TOKEN", settings.DBLP_TOKEN)
    db_path = os.environ.get("DB_PATH", settings.DB_PATH)
    index_path = dblp.default_index_path(os.path.join(db_path, XML_FILENAME))
    if not server:
        print("DBLP_SERVER is not configured in settings.py", file=sys.stderr)
        return 2
    if not index_path:
        print("DB_PATH is not configured in settings.py", file=sys.stderr)
        return 2

    index_dir = os.path.dirname(os.path.abspath(index_path)) or "."
    os.makedirs(index_dir, exist_ok=True)
    fd, tmp_index = tempfile.mkstemp(
        prefix=f".{os.path.basename(index_path)}.",
        suffix=".tmp",
        dir=index_dir,
    )
    os.close(fd)

    try:
        request = request_url(server, "/index.gz", token)
        with urllib.request.urlopen(request, timeout=None) as response, gzip.GzipFile(fileobj=response, mode="rb") as compressed, open(tmp_index, "wb") as output:
            while True:
                chunk = compressed.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)

        connection = sqlite3.connect(tmp_index)
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            if quick_check != "ok":
                raise RuntimeError(f"downloaded index failed quick_check: {quick_check}")
            metadata = dblp.read_index_metadata(connection)
            if metadata.get("schema_version") != str(dblp.INDEX_SCHEMA_VERSION):
                raise RuntimeError("downloaded index schema is stale")
        finally:
            connection.close()

        os.replace(tmp_index, index_path)
        print(f"Pulled DBLP index to {index_path} ({os.path.getsize(index_path)} bytes)")
        return 0
    except Exception as exc:
        print(f"Failed to pull DBLP index: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            os.unlink(tmp_index)
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="client.py")
    parser.add_argument("--raw", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("query", nargs="*", default=[])
    query_parser.add_argument("--limit", type=int, default=10)

    subparsers.add_parser("pull")
    return parser


def parse_args(argv: List[str]) -> argparse.Namespace:
    if len(argv) > 1 and argv[1] not in {"query", "pull", "--raw", "-h", "--help"}:
        argv = [argv[0], "query", *argv[1:]]
    return build_parser().parse_args(argv[1:])


def main(argv: List[str] | None = None) -> int:
    argv = argv or sys.argv
    args = parse_args(argv)

    if args.command == "pull":
        return pull_index()

    query = " ".join(getattr(args, "query", [])).strip()
    if not query or len(query) < 2:
        print(json.dumps(alfred_items("Finding papers on DBLP", "Please type at least 2 characters"), ensure_ascii=False))
        return 0

    limit = max(1, min(getattr(args, "limit", 10), 50))
    payload = query_with_fallback(query, limit)
    print(json.dumps(payload if args.raw else {"items": payload.get("items", [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
