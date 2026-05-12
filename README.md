# DBLP Mirror Search

DBLP Mirror Search is a private DBLP search service with a lightweight local client and an Alfred workflow.

The intended setup is:

- A private server keeps a daily updated DBLP SQLite index.
- Local clients query a local index first.
- If no local index exists, the client falls back to the private server.
- Local clients can run `make update` to download the completed server index.
- Alfred uses the same client/server protocol and copies BibTeX to the clipboard.

## Configuration

Edit `settings.py`:

```python
DBLP_SERVER = "https://dblp.example.com"
DBLP_TOKEN = "change-me"
DBLP_UPDATE_HOUR = 3
DB_PATH = ROOT_DIR
```

Settings:

- `DBLP_SERVER`: Base URL of your private DBLP search server.
- `DBLP_TOKEN`: Shared bearer token for protected server endpoints.
- `DBLP_UPDATE_HOUR`: Local server hour for the daily DBLP update.
- `DB_PATH`: Directory containing `dblp.xml.gz` and `dblp.xml.gz.idx.sqlite3`. By default, this is the directory containing `settings.py`.

For machine-specific values, create an ignored `settings_local.py` with the same variables, or set environment variables such as `DBLP_SERVER` and `DBLP_TOKEN`.

The derived database files are:

- XML mirror: `<DB_PATH>/dblp.xml.gz`
- SQLite index: `<DB_PATH>/dblp.xml.gz.idx.sqlite3`

## Server

Start the server:

```bash
make server
```

`make server` runs `server.py` through `run_server.py`, a small foreground supervisor that restarts the server if it exits.
If the SQLite index is missing at startup, the server starts one background update immediately. Until that update finishes, `/health` reports `ok: false` and `/query` returns HTTP 503 with the missing index path.

Server endpoints:

- `GET /health`: health and index metadata.
- `GET /query?q=<title>&limit=10`: query publications and return Alfred-compatible JSON items.
- `POST /update`: manually trigger a DBLP mirror update.
- `GET /index/metadata`: metadata for the downloadable SQLite index.
- `GET /index.gz`: stream the completed SQLite index as gzip.

The scheduled update downloads DBLP XML to a temporary file, builds a temporary SQLite index, and atomically replaces the live XML/index only after the full build succeeds.

## Client

Query from the command line:

```bash
./dblp query "Attention is All you Need"
```

Pull the completed database from the configured server:

```bash
make update
```

`make update` runs `./dblp pull`. It downloads `/index.gz`, decompresses it, verifies SQLite `PRAGMA quick_check`, checks the schema version, and atomically replaces the local index.

Query behavior:

1. Try the local SQLite index under `DB_PATH`.
2. If the local index is missing or unusable, query `DBLP_SERVER`.
3. Print Alfred Script Filter JSON. Each result's `arg` is the BibTeX entry.

## Alfred Workflow

Build and install the workflow:

```bash
make workflow
make install
```

The source workflow is in `alfredworkflow/workflow5`. The packaged workflow is:

```text
alfredworkflow/dblp-search.alfredworkflow
```

During development, `alfredworkflow/workflow5/settings.py` is a symlink to the repository root `settings.py`. The packaged workflow includes the current settings file content.

Alfred workflow variables can override the bundled settings:

- `DBLP_SERVER`
- `DBLP_TOKEN`

In Alfred, type `dblp <query>`, choose a result, and press Enter to copy BibTeX.

## Make Targets

```bash
make server    # start supervised DBLP server
make update    # pull completed SQLite index from the server
make workflow  # package the Alfred workflow
make install   # package and install the Alfred workflow
make clean     # remove generated workflow artifacts
```

## Notes

- The local index is large, currently around several GB.
- Server-side daily updates can take minutes because DBLP is large.
- Query latency is designed to stay below one second with a fresh local/server index.
