import os
import tempfile
import unittest

from identity import IdentityStore
from portfolio import PortfolioManager


class TestLocalIdentityIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = IdentityStore(
            os.path.join(self.temp_dir.name, "accounts.sqlite3")
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_registration_login_session_revoke_and_password_policy(self):
        with self.assertRaises(ValueError):
            self.store.register("trader@example.com", "short")

        registered = self.store.register(
            "Trader@example.com",
            "correct horse battery staple",
        )
        self.assertEqual(registered["role"], "user")
        self.assertEqual(
            self.store.authenticate(registered["token"])["email"],
            "trader@example.com",
        )
        login = self.store.login(
            "TRADER@example.com",
            "correct horse battery staple",
        )
        self.assertNotEqual(login["token"], registered["token"])
        self.store.revoke(login["token"])
        self.assertIsNone(self.store.authenticate(login["token"]))

    def test_distinct_users_have_persisted_separate_account_state(self):
        first = self.store.register(
            "first@example.com",
            "first secure password",
        )
        second = self.store.register(
            "second@example.com",
            "second secure password",
        )
        first_portfolio = PortfolioManager()
        first_portfolio.cash -= 125
        self.store.save_account_state(
            first["user_id"],
            first_portfolio.export_state(),
            {"mode": "assisted"},
        )

        first_saved, first_settings = self.store.read_account_state(
            first["user_id"]
        )
        second_saved, second_settings = self.store.read_account_state(
            second["user_id"]
        )
        self.assertEqual(first_saved["cash"], 9875)
        self.assertEqual(first_settings["mode"], "assisted")
        self.assertEqual(second_saved, {})
        self.assertEqual(second_settings, {})

    def test_order_idempotency_reservation_survives_store_reopen(self):
        user = self.store.register(
            "orders@example.com",
            "valid order password",
        )
        first = self.store.begin_paper_order(user["user_id"], "retry-1")
        self.assertTrue(first["new"])

        reopened = IdentityStore(self.store.path)
        retry = reopened.begin_paper_order(user["user_id"], "retry-1")
        self.assertFalse(retry["new"])
        self.assertEqual(retry["status"], "pending")
        self.assertIsNone(retry["result"])


if __name__ == "__main__":
    unittest.main()
