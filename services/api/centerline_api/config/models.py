"""Request bodies for the Configuration page (camelCase on the wire)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

HOST = re.compile(r"^[A-Za-z0-9.\-]+$|^\[[0-9A-Fa-f:]+\]$")


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False)


class HistorianIn(_Camel):
    base_url: str = Field(description="e.g. http://10.156.116.179:4516")
    dataset: str = Field(min_length=1, max_length=200)
    timeout_s: int = Field(60, ge=5, le=300)
    verify_tls: bool = True
    auth_type: Literal["none", "bearer", "basic"] = "none"
    username: str = ""
    token: str | None = Field(None, description="Write-only. Empty keeps the saved token")
    password: str | None = Field(None, description="Write-only. Empty keeps the saved password")
    reason: str = ""

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https?://[^\s/]+", v):
            raise ValueError("Use http://host:port or https://host:port")
        return v


class MqttIn(_Camel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(8883, ge=1, le=65535)
    protocol: Literal["5", "3.1.1"] = "5"
    tls_enabled: bool = True
    verify_hostname: bool = True
    ca_pem: str | None = Field(None, description="Write-only PEM text of the broker's CA certificate")
    clear_ca: bool = False
    username: str = ""
    password: str | None = Field(None, description="Write-only. Empty keeps the saved password")
    clear_password: bool = False
    client_id: str = Field("", max_length=64)
    keepalive_s: int = Field(5, ge=2, le=60)
    subscriptions: list[str] = Field(min_length=1, max_length=10)
    freshness_s: dict[str, int] = Field(default_factory=dict)
    reason: str = ""

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip()
        if "://" in v or not HOST.match(v):
            raise ValueError("Enter a host name or IP address only, without mqtt:// or a port")
        return v

    @field_validator("freshness_s")
    @classmethod
    def _freshness(cls, v: dict[str, int]) -> dict[str, int]:
        for area, seconds in v.items():
            if not 5 <= seconds <= 600:
                raise ValueError(f"Freshness for {area} must be 5–600 s")
        return v


class MqttTestIn(MqttIn):
    seconds: float = Field(10, ge=3, le=30)


class TagsIn(_Camel):
    tags: list[str] = Field(max_length=100)


class ZoneIn(_Camel):
    id: str
    name: str
    setpoint: str | None = None
    actual: str | None = None


class ParameterIn(_Camel):
    base_version: str
    status: Literal["active", "analytics_only", "awaiting_tag"]
    zones: list[ZoneIn] = Field(max_length=24)
    reason: str


# -- monitoring rules (ADR-0012) ---------------------------------------------------

BriefChangeMode = Literal["do_not_record", "lightweight", "cleared_before_trigger"]
Delay = Field(None, ge=0, le=3600)
Offset = Field(None, ge=0)


def _aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("Include the time zone, e.g. 2026-10-01T06:00:00+08:00")
    return v


class RuleIn(_Camel):
    """One scope: a zone, or every zone of the parameter (null). Empty fields are inherited."""

    parameter_id: str
    zone_id: str | None = None
    target: float | None = None
    warn_low: float | None = Offset
    warn_high: float | None = Offset
    crit_low: float | None = Offset
    crit_high: float | None = Offset
    mismatch_delay_s: int | None = Delay
    warning_delay_s: int | None = Delay
    critical_delay_s: int | None = Delay
    recovery_delay_s: int | None = Delay
    brief_change_mode: BriefChangeMode | None = None
    warning_notifications: bool | None = None


class PauseIn(_Camel):
    """Actual rules pause while the machine is stopped, plus a warm-up after long stops (ADR-0010)."""

    enabled: bool = True
    long_stop_min: int = Field(10, ge=1, le=240)
    warmup_min: int = Field(30, ge=0, le=240)


class DefaultsIn(_Camel):
    mismatch_delay_s: int = Field(ge=0, le=3600)
    warning_delay_s: int = Field(ge=0, le=3600)  # also Critical → Warning (ACT-02)
    critical_delay_s: int = Field(ge=0, le=3600)
    recovery_delay_s: int = Field(15, ge=0, le=3600)  # ACT-02 default
    brief_change_mode: BriefChangeMode = "lightweight"  # HMI-05 default
    warning_notifications: bool = True  # ACT-03: Warnings can be switched off, Criticals can't


class RulesSettingsIn(_Camel):
    pause_when_stopped: PauseIn = Field(default_factory=PauseIn)
    defaults: DefaultsIn


class RulesVersionIn(_Camel):
    expected_latest: int | None = Field(description="The newest version when the editor opened (optimistic lock)")
    based_on: int | None = None
    settings: RulesSettingsIn
    rules: list[RuleIn] = Field(max_length=2000)
    reason: str = ""
    activate: Literal["no", "now", "at"] = "no"
    activate_at: datetime | None = None

    _tz = field_validator("activate_at")(_aware)


class ActivateIn(_Camel):
    expected_active: int | None = Field(description="The version in effect when the page loaded (optimistic lock)")
    at: datetime | None = Field(None, description="Empty: now")
    reason: str = ""

    _tz = field_validator("at")(_aware)


class CancelIn(_Camel):
    reason: str = ""



# -- Analytics-valid ranges (ANA-10/11, ADR-0029) ------------------------------------


class RangesFileIn(_Camel):
    """The CSV as uploaded, base64, so the bytes kept are the file's own (ANA-11)."""

    source: str = Field("", max_length=200, description="The file's name, e.g. analytics-ranges.csv")
    content_base64: str = Field(max_length=100_000)


class RangesVersionIn(RangesFileIn):
    expected_latest: int | None = Field(description="The newest version when the page loaded (optimistic lock)")
    reason: str = ""
    activate: Literal["no", "now", "at"] = "no"
    activate_at: datetime | None = None

    _tz = field_validator("activate_at")(_aware)


# -- tag mappings (ADR-0013) ---------------------------------------------------------


class MappingRowIn(_Camel):
    """Where one register tag arrives: a topic, and a JSON field of its message (empty: the whole payload)."""

    tag: str = Field(min_length=1, max_length=300)
    topic: str = Field(max_length=65535)
    field: str | None = Field(None, max_length=300)


class MappingVersionIn(_Camel):
    expected_latest: int | None = Field(description="The newest version when the editor opened (optimistic lock)")
    based_on: int | None = None
    rows: list[MappingRowIn] = Field(max_length=2000)
    source: str = Field("by hand", max_length=120)
    reason: str = ""
    activate: Literal["no", "now", "at"] = "no"
    activate_at: datetime | None = None

    _tz = field_validator("activate_at")(_aware)


class MappingImportIn(_Camel):
    format: Literal["topic-map", "csv"]
    content: str = Field(max_length=2_000_000)


class DiscoverIn(_Camel):
    seconds: float = Field(10, ge=3, le=30)


# -- notifications (ADR-0023) ---------------------------------------------------------------


class RoutingRuleIn(_Camel):
    name: str = Field("", max_length=200)
    types: list[str] = Field(default_factory=list, max_length=20)
    channel: str = Field("email", max_length=10)
    targets: list[str] = Field(default_factory=list, max_length=200)


class RoutingVersionIn(_Camel):
    expected_latest: int | None = Field(description="The newest version when the editor opened (optimistic lock)")
    based_on: int | None = None
    rules: list[RoutingRuleIn] = Field(max_length=100)
    reason: str = ""
    activate: Literal["no", "now", "at"] = "no"
    activate_at: datetime | None = None

    _tz = field_validator("activate_at")(_aware)


class NotificationsConnectionIn(_Camel):
    app_url: str = Field("", max_length=300, description="Where the messages' links point, e.g. https://centerline.plant.local")
    teams_url: str = Field("", max_length=4000, description="The flow's HTTP POST URL. Write-only: empty keeps the saved one")
    clear_teams: bool = False
    smtp_host: str = Field("", max_length=255)
    smtp_port: int = Field(25, ge=1, le=65535)
    smtp_security: Literal["none", "starttls", "tls"] = "none"
    smtp_username: str = Field("", max_length=200)
    smtp_password: str = Field("", max_length=500, description="Write-only: empty keeps the saved one")
    clear_smtp_password: bool = False
    email_sender: str = Field("", max_length=200, description="The From address, e.g. centerline@plant.local")
    reason: str = ""
