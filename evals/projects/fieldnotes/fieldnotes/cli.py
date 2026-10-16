"""Command-line entry point: `python -m fieldnotes.cli add TEXT` or `list`."""

from __future__ import annotations

import sys

from . import store


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: fieldnotes add TEXT | list", file=sys.stderr)
        return 2
    if args[0] == "add" and len(args) == 2:
        note = store.add(args[1])
        print(f"added: {note['text']}")
        return 0
    if args[0] == "list":
        for note in store.load():
            print(f"{note['created']}  {note['text']}")
        return 0
    print("usage: fieldnotes add TEXT | list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
