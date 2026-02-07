import os
import tempfile
import unittest

from core.graph.checkpoint import SQLiteCheckpointStore


class CheckpointStoreTests(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoints.db")
            store = SQLiteCheckpointStore(db_path=db_path)
            store.save_state("analysis", "thread-1", {"ok": True, "count": 3})
            loaded = store.load_state("analysis", "thread-1")
            self.assertEqual(loaded["ok"], True)
            self.assertEqual(loaded["count"], 3)


if __name__ == "__main__":
    unittest.main()
