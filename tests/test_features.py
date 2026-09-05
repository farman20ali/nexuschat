import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.database import Database
from shared.constants import EVERYONE


class TestNexusChatFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database()
        cls.db.connect()
        with cls.db._cursor() as cur:
            cur.execute("DELETE FROM messages WHERE (sender = 'alice_test' AND recipient = 'bob_test') OR (sender = 'bob_test' AND recipient = 'alice_test')")
            cur.execute("DELETE FROM messages WHERE recipient = 'all'")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_01_soft_purge_dm(self):
        # Insert test message between alice_test and bob_test
        msg = self.db.save_message("alice_test", "bob_test", "Hello Bob from Alice")
        self.assertIsNotNone(msg)

        # Ensure both see the message in history
        alice_hist = [m for m in self.db.history_for("alice_test") if m.get("body") == "Hello Bob from Alice"]
        bob_hist = [m for m in self.db.history_for("bob_test") if m.get("body") == "Hello Bob from Alice"]
        self.assertEqual(len(alice_hist), 1)
        self.assertEqual(len(bob_hist), 1)

        # Alice purges DM history with bob_test
        purged_count = self.db.delete_history("alice_test", room="bob_test")
        self.assertGreaterEqual(purged_count, 1)

        # Alice should no longer see the message
        alice_hist_after = [m for m in self.db.history_for("alice_test") if m.get("body") == "Hello Bob from Alice"]
        self.assertEqual(len(alice_hist_after), 0)

        # Bob MUST STILL see the message!
        bob_hist_after = [m for m in self.db.history_for("bob_test") if m.get("body") == "Hello Bob from Alice"]
        self.assertEqual(len(bob_hist_after), 1)

    def test_02_general_purge_role_gating(self):
        # Insert message into #general
        self.db.save_message("alice_test", "all", "Hello Everyone in General")

        # Non-admin user tries to purge #general
        count_user = self.db.delete_history("alice_test", room="all", is_admin=False)
        self.assertEqual(count_user, 0)

        # Check message still exists in #general for everyone
        hist = [m for m in self.db.history_for("alice_test") if m.get("body") == "Hello Everyone in General"]
        self.assertEqual(len(hist), 1)

        # Admin purges #general
        count_admin = self.db.delete_history("admin", room="all", is_admin=True)
        self.assertGreaterEqual(count_admin, 1)

        # Check message is now deleted for everyone
        hist_after = [m for m in self.db.history_for("alice_test") if m.get("body") == "Hello Everyone in General"]
        self.assertEqual(len(hist_after), 0)

    def test_03_file_deletion_modes(self):
        # Save a test file uploaded by alice_test
        f_row = self.db.save_file("test_document.txt", "stored_test_doc.txt", 1024, "alice_test")
        file_id = f_row["id"]

        # Link to message for receiver bob_test
        self.db.save_message("alice_test", "bob_test", "Sending doc", msg_type="file", file_id=file_id)

        # Bob (receiver) hides file for himself
        self.db.hide_file_for_user(file_id, "bob_test")

        # Bob's file list should NOT show file
        bob_files = [f for f in self.db.list_files("bob_test") if f["id"] == file_id]
        self.assertEqual(len(bob_files), 0)

        # Alice's file list STILL shows file
        alice_files = [f for f in self.db.list_files("alice_test") if f["id"] == file_id]
        self.assertEqual(len(alice_files), 1)

        # Alice (uploader) deletes file for everyone
        deleted_stored = self.db.delete_file(file_id)
        self.assertEqual(deleted_stored, "stored_test_doc.txt")

        # Alice's file list is now empty too
        alice_files_after = [f for f in self.db.list_files("alice_test") if f["id"] == file_id]
        self.assertEqual(len(alice_files_after), 0)

    def test_04_jwt_auth_and_security_questions(self):
        from shared.auth import create_jwt_token, verify_jwt_token
        
        # Test JWT token signing and verification
        token = create_jwt_token({"sub": "admin", "role": "admin"})
        valid, payload = verify_jwt_token(token)
        self.assertTrue(valid)
        self.assertEqual(payload.get("sub"), "admin")
        self.assertEqual(payload.get("role"), "admin")

        # Ensure user exists for security questions test
        self.db.register("alice_test", "password123")

        # Test Security Questions setup and verification
        ok, err = self.db.set_security_questions("alice_test", "Pet?", "Fluffy", "City?", "London")
        self.assertTrue(ok)

        q1, q2, configured = self.db.get_security_questions("alice_test")
        self.assertTrue(configured)
        self.assertEqual(q1, "Pet?")
        self.assertEqual(q2, "City?")

        # Verify correct answers (case-insensitive & trimmed)
        ok_ver, _ = self.db.verify_security_answers("alice_test", " fluffy ", "LONDON")
        self.assertTrue(ok_ver)

        # Verify incorrect answer fails
        fail_ver, _ = self.db.verify_security_answers("alice_test", "Wrong", "London")
        self.assertFalse(fail_ver)

    def test_05_config_encryption(self):
        from shared.auth import encrypt_config_val, decrypt_config_val
        secret_pass = "super_secret_db_pass_123!"
        enc = encrypt_config_val(secret_pass)
        self.assertTrue(enc.startswith("enc:"))
        self.assertNotEqual(enc, secret_pass)

        dec = decrypt_config_val(enc)
        self.assertEqual(dec, secret_pass)

        # Plain text fallback test
        self.assertEqual(decrypt_config_val("plain_pass"), "plain_pass")


if __name__ == "__main__":
    unittest.main()

