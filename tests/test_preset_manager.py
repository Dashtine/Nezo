import os
import sqlite3
import tempfile
import unittest

import preset_manager


class PresetManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = preset_manager.DB_PATH
        preset_manager.DB_PATH = os.path.join(self.tmpdir.name, "presets.db")

    def tearDown(self):
        preset_manager.DB_PATH = self.original_db_path
        self.tmpdir.cleanup()

    def test_save_preset_does_not_persist_auth_secrets(self):
        preset_manager.save_preset(
            "scalping",
            {
                "contracts": 2,
                "symbolInput": "MNQ",
                "apiKey": "super-secret-key",
                "token": "super-secret-token",
                "token_expiry": "tomorrow",
            },
        )

        loaded = preset_manager.load_preset("scalping")

        self.assertEqual(loaded["contracts"], 2)
        self.assertEqual(loaded["symbolInput"], "MNQ")
        self.assertNotIn("apiKey", loaded)
        self.assertNotIn("token", loaded)
        self.assertNotIn("token_expiry", loaded)

        conn = sqlite3.connect(preset_manager.DB_PATH)
        stored_json = conn.execute(
            "SELECT data FROM presets WHERE name = ?", ("scalping",)
        ).fetchone()[0]
        conn.close()

        self.assertNotIn("super-secret-key", stored_json)
        self.assertNotIn("super-secret-token", stored_json)

    def test_load_sanitizes_legacy_rows(self):
        preset_manager.init_db()
        conn = sqlite3.connect(preset_manager.DB_PATH)
        conn.execute(
            "INSERT INTO presets (name, data) VALUES (?, ?)",
            (
                "legacy",
                '{"contracts": 1, "apiKey": "old-key", "token": "old-token"}',
            ),
        )
        conn.commit()
        conn.close()

        loaded = preset_manager.load_preset("legacy")

        self.assertEqual(loaded["contracts"], 1)
        self.assertNotIn("apiKey", loaded)
        self.assertNotIn("token", loaded)


if __name__ == "__main__":
    unittest.main()
