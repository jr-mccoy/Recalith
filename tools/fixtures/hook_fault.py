"""A fresh hook process with one failpoint armed, then the real entry (fault-injection latency trials only).

    python -I tools/fixtures/hook_fault.py MODE ARGS...   (ARGS are recalith.fast.entry's own)

``slow_fsync`` adds 30 ms to every spool fsync; ``transient_rename`` raises one
sharing violation (``winerror`` 32) on the spool rename. Failpoints have no
environment or configuration switch: only a process that imports and arms
them in its own memory, like this measurement fixture, is affected.
"""

import errno
import sys
import time

from recalith.fast import entry, failpoints


def main() -> int:
    mode, rest = sys.argv[1], sys.argv[2:]
    if mode == "slow_fsync":
        failpoints.arm(failpoints.SPOOL_FSYNC, lambda name: time.sleep(0.03), times=10**6)
    elif mode == "transient_rename":
        failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EACCES, winerror=32), times=1)
    else:
        return 2
    return entry.main(rest)


if __name__ == "__main__":
    sys.exit(main())
