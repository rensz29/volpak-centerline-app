"""Compatibility shim: the register loader lives in services/common/centerline_common/register.py,
shared with the api service. The tools keep importing `register` from here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "common"))

from centerline_common.register import (  # noqa: E402,F401
    ANALYTICS_STATUSES,
    DEFAULT_PATH,
    REPO,
    AnalyticsVariable,
    HmiMatch,
    Register,
    Zone,
    load,
)
