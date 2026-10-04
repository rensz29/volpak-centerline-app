"""Request model for POST /api/v1/analytics/query (SDD §10 example, ANA-04…07, ANA-16, ANA-18)."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# ISO 8601 durations → seconds. Each interval divides the next, so results nest (SDD §8).
BUCKETS: dict[str, int] = {"PT10S": 10, "PT30S": 30, "PT1M": 60, "PT5M": 300, "PT15M": 900, "PT1H": 3600}
BUCKET_LABELS = {"PT10S": "10 seconds", "PT30S": "30 seconds", "PT1M": "1 minute",
                 "PT5M": "5 minutes", "PT15M": "15 minutes", "PT1H": "1 hour"}

Bucket = Literal["PT10S", "PT30S", "PT1M", "PT5M", "PT15M", "PT1H"]
Aggregation = Literal["AVG", "MIN", "MAX"]
Shift = Literal["ALL", "A", "B", "C"]
GroupBy = Literal["NONE", "SHIFT", "PRODUCTION_DATE"]


class AnalyticsQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sku: str | None = Field(None, description="SKU filter; rejected while the register has no SKU tag (ADR-0008)")
    shift: Shift = "ALL"
    from_: AwareDatetime = Field(alias="from", description="UTC, e.g. 2026-09-28T00:00:00Z")
    to: AwareDatetime
    x: str = Field(description="Analytics variable channel, e.g. P02.V1.actual or P02.V1.setpoint (ADR-0009)")
    y: str
    bucket: Bucket = "PT1M"
    aggregation: Aggregation = "AVG"
    group_by: GroupBy = Field("NONE", alias="groupBy")
    group_stats: bool = Field(False, alias="groupStats")
