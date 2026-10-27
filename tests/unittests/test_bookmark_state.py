import importlib.util
import os
import unittest

PATH = os.path.join(os.path.dirname(__file__), "..", "bookmark_state.py")
SPEC = importlib.util.spec_from_file_location("bookmark_state", PATH)
bookmark_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bookmark_state)

FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class TestBookmarkState(unittest.TestCase):

    def test_scalar_bookmark_still_rewinds(self):
        rewound = bookmark_state.rewind_bookmark(
            "2024-06-01T00:00:00.000000Z", 0, 0, 1, FORMAT)
        self.assertEqual(rewound, "2024-05-31T23:59:00.000000Z")

    def test_per_account_bookmark_rewinds_each_cursor(self):
        rewound = bookmark_state.rewind_bookmark({
            "111": "2024-06-01T00:00:00.000000Z",
            "222": "2024-02-01T00:00:00.000000Z",
        }, 0, 0, 1, FORMAT)
        self.assertEqual(rewound, {
            "111": "2024-05-31T23:59:00.000000Z",
            "222": "2024-01-31T23:59:00.000000Z",
        })

    def test_record_uses_its_own_account_cursor(self):
        bookmark = {
            "111": "2024-06-01T00:00:00.000000Z",
            "222": "2024-02-01T00:00:00.000000Z",
        }
        self.assertEqual(
            bookmark_state.bookmark_for_record(bookmark, {"account_id": 222}),
            "2024-02-01T00:00:00.000000Z",
        )
        self.assertEqual(
            bookmark_state.bookmark_for_record("2024-06-01T00:00:00.000000Z", {"id": 1}),
            "2024-06-01T00:00:00.000000Z",
        )
