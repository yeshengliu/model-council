from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class RuntimePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_env = {
            "MODEL_COUNCIL_DATA_DIR": os.environ.get("MODEL_COUNCIL_DATA_DIR"),
            "MODEL_COUNCIL_FRONTEND_DIST": os.environ.get("MODEL_COUNCIL_FRONTEND_DIST"),
            "MODEL_COUNCIL_DESKTOP_MODE": os.environ.get("MODEL_COUNCIL_DESKTOP_MODE"),
        }
        os.environ["MODEL_COUNCIL_DATA_DIR"] = self.tempdir.name
        os.environ["MODEL_COUNCIL_FRONTEND_DIST"] = str(Path(self.tempdir.name) / "frontend-dist")
        os.environ["MODEL_COUNCIL_DESKTOP_MODE"] = "1"

        import backend.runtime as runtime
        import backend.settings as settings
        import backend.storage as storage

        self.runtime = importlib.reload(runtime)
        self.settings = importlib.reload(settings)
        self.storage = importlib.reload(storage)

    def tearDown(self) -> None:
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tempdir.cleanup()

    def test_runtime_uses_overridden_data_dir(self) -> None:
        root = Path(self.tempdir.name).resolve()
        self.assertEqual(self.runtime.data_dir(), root)
        self.assertEqual(self.runtime.settings_path(), root / "settings.json")
        self.assertEqual(self.runtime.conversations_dir(), root / "conversations")
        self.assertEqual(self.runtime.debug_dir(), root / "debug")
        self.assertTrue(self.runtime.desktop_mode())

    def test_settings_save_writes_into_overridden_location(self) -> None:
        saved = self.settings.save(self.settings.DEFAULT_SETTINGS, self.settings.DEFAULT_APP_SETTINGS)
        self.assertTrue((Path(self.tempdir.name).resolve() / "settings.json").exists())
        self.assertEqual(saved["claude"]["default_model"], "sonnet")

        payload = json.loads((Path(self.tempdir.name).resolve() / "settings.json").read_text())
        self.assertIn("app", payload)
        self.assertTrue(payload["app"]["research_enabled"])

    def test_storage_persists_threads_into_overridden_location(self) -> None:
        conversation = {
            "id": "conv-1",
            "thread_id": "thread-1",
            "question": "hello",
            "created_at": "2026-04-16T00:00:00+00:00",
            "turn_index": 0,
        }
        path = self.storage.save(conversation)
        self.assertEqual(path.parent, Path(self.tempdir.name).resolve() / "conversations")
        self.assertEqual(self.storage.load("conv-1")["thread_id"], "thread-1")
        self.assertEqual(len(self.storage.list_summaries()), 1)


if __name__ == "__main__":
    unittest.main()
