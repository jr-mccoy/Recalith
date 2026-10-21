"""Task oracles: they judge final artifacts and the action log, never memory text (ACCEPTANCE_TESTS §6).

``evals/oracles`` is the plan's ``evals/oracles.py`` (IMPLEMENTATION_PLAN Task 18) as a package, so the
Task 1 smoke oracles keep their path (``evals/oracles/smoke.py``) and later suites can add modules beside them.
"""

from evals.oracles.smoke import CHECKS, judge

__all__ = ["CHECKS", "judge"]
