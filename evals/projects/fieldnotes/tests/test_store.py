import os
import tempfile
import unittest
from datetime import datetime, timezone

from fieldnotes import store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["NOTES_HOME"] = self.tmp.name

    def test_add_then_load(self):
        store.add("first", now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
        self.assertEqual([n["text"] for n in store.load()], ["first"])


if __name__ == "__main__":
    unittest.main()
