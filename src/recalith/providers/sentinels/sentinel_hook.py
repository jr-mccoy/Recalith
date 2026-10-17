"""Harmless sentinel hook: records that it ran, then exits 0 with no output.

Invoked as: python -I sentinel_hook.py MARKER_FILE LABEL
It never prints context, so it cannot itself inject a sentinel into a model.
"""
import sys

marker, label = sys.argv[1], sys.argv[2]
try:
    sys.stdin.read(65536)
except Exception:
    pass
with open(marker, "a", encoding="utf-8") as fh:
    fh.write(label + "\n")
