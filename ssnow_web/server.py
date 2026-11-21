"""ssnow-web server entry point."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from ssnow_core.config import config_dir
from ssnow_core.logging_config import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ssnow-web", description="Solar System Now Web API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--data-dir", help="Override SSNOW_DATA_DIR")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["SSNOW_DATA_DIR"] = args.data_dir

    setup_logging(log_dir=config_dir() / "logs", level=os.environ.get("SSNOW_LOG_LEVEL", "INFO"))
    uvicorn.run("ssnow_web.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
