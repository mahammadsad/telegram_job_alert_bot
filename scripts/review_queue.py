#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.db import connect  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage notice review items")
    result.add_argument("command", choices=["list", "show", "approve", "reject", "retry"])
    result.add_argument("id", nargs="?", type=int)
    result.add_argument("--reason", default="")
    result.add_argument("--database", default=str(ROOT / "jobs.db"))
    return result


def main() -> None:
    args = parser().parse_args()
    conn = connect(args.database)
    try:
        if args.command == "list":
            rows = conn.execute(
                """SELECT q.id, q.status, n.category, n.title, q.reason, q.created_at
                   FROM review_queue q JOIN notices n ON n.id=q.notice_id
                   WHERE q.status='PENDING' ORDER BY q.id"""
            ).fetchall()
            for row in rows:
                print(f"#{row['id']} [{row['category']}] {row['title']} — {row['reason']}")
            if not rows:
                print("No pending review items.")
            return
        if args.id is None:
            raise SystemExit("An item id is required for this command.")
        row = conn.execute(
            """SELECT q.*, n.* FROM review_queue q JOIN notices n ON n.id=q.notice_id
               WHERE q.id=?""",
            (args.id,),
        ).fetchone()
        if not row:
            raise SystemExit(f"Review item #{args.id} does not exist.")
        if args.command == "show":
            print(json.dumps(dict(row), ensure_ascii=False, indent=2))
            return
        if args.command == "approve":
            conn.execute(
                "UPDATE review_queue SET status='APPROVED', updated_at=datetime('now') WHERE id=?",
                (args.id,),
            )
            conn.execute(
                """UPDATE notices SET manually_approved=1, verification_status='UNDER_VERIFICATION'
                   WHERE id=?""",
                (row["notice_id"],),
            )
        elif args.command == "reject":
            if not args.reason:
                raise SystemExit("reject requires --reason")
            conn.execute(
                """UPDATE review_queue SET status='REJECTED', reviewer_note=?, updated_at=datetime('now')
                   WHERE id=?""",
                (args.reason, args.id),
            )
            conn.execute(
                "UPDATE notices SET verification_status='REJECTED', conflict_reason=? WHERE id=?",
                (args.reason, row["notice_id"]),
            )
        elif args.command == "retry":
            conn.execute(
                "UPDATE review_queue SET status='RETRY', updated_at=datetime('now') WHERE id=?",
                (args.id,),
            )
            conn.execute(
                "UPDATE notices SET verification_status='DISCOVERED' WHERE id=?",
                (row["notice_id"],),
            )
        conn.commit()
        print(f"Review item #{args.id}: {args.command} recorded.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

