#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.db import connect  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply idempotent SQLite migrations")
    parser.add_argument("--database", default=str(ROOT / "jobs.db"))
    args = parser.parse_args()
    connection = connect(args.database)
    connection.close()
    print(f"Migrations complete: {args.database}")


if __name__ == "__main__":
    main()

