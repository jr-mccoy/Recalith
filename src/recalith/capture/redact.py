"""Moved to :mod:`recalith.fast.redact` in Task 3b (decision 0005).

The synchronous hook path may import only the standard library and
``recalith.fast``, so the stdlib implementation lives there. This name stays
importable and is the *same module object*: arming a failpoint, patching an
attribute or reading module state through either name behaves identically.
"""

import sys

from recalith.fast import redact as _impl

sys.modules[__name__] = _impl
