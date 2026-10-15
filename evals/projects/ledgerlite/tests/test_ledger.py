import unittest

from ledgerlite import Ledger


class LedgerTests(unittest.TestCase):
    def test_transfer_preserves_total(self):
        ledger = Ledger()
        ledger.open("cash")
        ledger.open("bank")
        ledger.transfer("cash", "bank", "12.50")
        self.assertEqual(ledger.total(), 0)
        self.assertEqual(str(ledger.balance("bank")), "12.50")

    def test_rejects_non_positive_amount(self):
        ledger = Ledger()
        ledger.open("a")
        ledger.open("b")
        with self.assertRaises(ValueError):
            ledger.transfer("a", "b", "0")


if __name__ == "__main__":
    unittest.main()
