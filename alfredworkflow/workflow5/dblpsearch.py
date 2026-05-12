#!/usr/bin/env python3

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import settings


REQUEST_TIMEOUT = 20


def print_items(items):
    print(json.dumps({"items": items}, ensure_ascii=False))


def message_item(title, subtitle="", valid=False):
    return {
        "title": title,
        "subtitle": subtitle,
        "valid": valid,
    }


def query_server(server, token, user_query):
    params = urllib.parse.urlencode({"q": user_query, "limit": "10"})
    request = urllib.request.Request(f"{server.rstrip('/')}/query?{params}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    user_query = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if len(user_query) < 2:
        print_items([message_item("Finding papers on DBLP", "Please type at least 2 characters")])
        return

    server = os.environ.get("DBLP_SERVER", settings.DBLP_SERVER)
    token = os.environ.get("DBLP_TOKEN", settings.DBLP_TOKEN)
    if not server:
        print_items(
            [
                message_item(
                    "DBLP server is not configured",
                    "Set DBLP_SERVER and DBLP_TOKEN in Alfred workflow configuration",
                )
            ]
        )
        return

    try:
        payload = query_server(server, token, user_query)
        if "error" in payload:
            print_items([message_item(f"DBLP server error: {payload['error']}", "Try again later")])
            return
        print_items(payload.get("items", []))
    except urllib.error.HTTPError as exc:
        print_items([message_item(f"DBLP server error: HTTP {exc.code}", exc.reason)])
    except Exception as exc:
        print_items([message_item(f"DBLP server error: {exc}", "Check DBLP_SERVER and DBLP_TOKEN")])


if __name__ == "__main__":
    main()
