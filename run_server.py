#!/usr/bin/env python3

import subprocess
import sys
import time


RESTART_DELAY_SECONDS = 5


def main() -> int:
    command = [sys.executable, "server.py", *sys.argv[1:]]
    while True:
        started = time.time()
        process = subprocess.run(command)
        elapsed = time.time() - started
        print(
            f"server exited with code {process.returncode}; restarting in {RESTART_DELAY_SECONDS}s",
            file=sys.stderr,
            flush=True,
        )
        if elapsed < 1:
            time.sleep(RESTART_DELAY_SECONDS)
        else:
            time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
