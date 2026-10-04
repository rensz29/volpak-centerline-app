"""Compatibility shim: the Timebase client lives in services/common/centerline_common/historian.py,
shared with the api service. The tools keep importing `timebase` from here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "common"))

from centerline_common.historian import (  # noqa: E402,F401
    UNREADABLE_Q,
    BadResponse,
    Gap,
    Sample,
    TagNotFound,
    TimebaseClient,
    TimebaseError,
    iso_z,
    join_series,
    parse_ts,
    utc,
)
