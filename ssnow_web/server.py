"""ssnow-web server entry point."""

from __future__ import annotations

import argparse
import sys

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ssnow-web", description="Solar System Now Web API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--data-dir", help="Override SSNOW_DATA_DIR")
    args = parser.parse_args(argv)

    if args.data_dir:
        import os

        os.environ["SSNOW_DATA_DIR"] = args.data_dir

    uvicorn.run("ssnow_web.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
