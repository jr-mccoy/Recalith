"""``python -m recalith``: the guarded command-line transport (DATA_CONTRACTS §12; Task 12a).

The project launcher ``.recalith/bin/recalith`` runs exactly this module on
the project's pinned runtime with ``--project`` supplied. Everything lives in
:mod:`recalith.cli.main`; this module only hands over the process.
"""

from __future__ import annotations

import sys

from recalith.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
