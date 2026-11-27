"""`tracemelt app.py [args]` or `tracemelt -m package.module [args]`.

Starts telemetry, turns on every OpenTelemetry instrumentation that is installed,
then runs the program as if it had been started with python.
"""

from __future__ import annotations

import runpy
import sys

USAGE = "usage: tracemelt script.py [args...]\n       tracemelt -m module [args...]\n"


def _auto_instrument() -> None:
    try:
        from importlib.metadata import entry_points
        for entry in entry_points(group="opentelemetry_instrumentor"):
            try:
                entry.load()().instrument()
            except Exception:
                pass          # one broken instrumentation must not stop the program
    except Exception:
        pass


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        sys.stderr.write(USAGE)
        return 0 if args else 2
    try:
        import tracemelt
        if tracemelt.init():
            _auto_instrument()
    except Exception:
        pass                  # the program runs with or without telemetry

    if args[0] == "-m":
        if len(args) < 2:
            sys.stderr.write(USAGE)
            return 2
        sys.argv = args[1:]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = args
        runpy.run_path(args[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
