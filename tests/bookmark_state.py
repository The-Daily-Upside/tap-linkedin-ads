"""Bookmark values are timestamps, or a map of account id to timestamp."""

from datetime import datetime as dt
from datetime import timedelta

import dateutil.parser


def rewind_bookmark(value, days, hours, minutes, bookmark_format):
    """Move a bookmark backward. A per-account map is rewound one cursor at a time."""
    if isinstance(value, dict):
        return {
            str(account_id): rewind_bookmark(cursor, days, hours, minutes, bookmark_format)
            for account_id, cursor in value.items()
        }
    parsed = dateutil.parser.parse(value)
    rewound = parsed - timedelta(days=days, hours=hours, minutes=minutes)
    return dt.strftime(rewound, bookmark_format)


def bookmark_for_record(bookmark_value, record):
    """Return the cursor that applies to this record."""
    if isinstance(bookmark_value, dict):
        account_id = record.get("account_id")
        if account_id is None:
            return None
        return bookmark_value.get(str(account_id), bookmark_value.get(account_id))
    return bookmark_value
