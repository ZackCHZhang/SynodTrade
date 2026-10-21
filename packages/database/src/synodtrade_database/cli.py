"""`synodtrade-db` command: database migrations.

    synodtrade-db upgrade [--url URL] [--revision head]
    synodtrade-db downgrade [--url URL] [--revision -1]
    synodtrade-db current [--url URL]
    synodtrade-db revision -m "add x" [--url URL]      # autogenerate from the ORM models

Without --url, SYNODTRADE_DATABASE_URL is used.
"""

from __future__ import annotations

import argparse

from synodtrade_database import migrate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="synodtrade-db", description="database migrations")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("upgrade", "downgrade", "current", "revision"):
        p = sub.add_parser(name)
        p.add_argument(
            "--url", default=None, help="database URL (default: $SYNODTRADE_DATABASE_URL)"
        )
        if name in ("upgrade", "downgrade"):
            p.add_argument("--revision", default="head" if name == "upgrade" else "-1")
        if name == "revision":
            p.add_argument("-m", "--message", required=True)
    args = parser.parse_args(argv)

    if args.command == "upgrade":
        migrate.upgrade(args.url, args.revision)
    elif args.command == "downgrade":
        migrate.downgrade(args.url, args.revision)
    elif args.command == "current":
        migrate.current(args.url)
    else:
        migrate.revision(args.message, args.url)


if __name__ == "__main__":  # pragma: no cover
    main()
