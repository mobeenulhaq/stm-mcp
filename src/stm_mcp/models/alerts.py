from enum import Enum

from pydantic import BaseModel, ConfigDict


class Language(str, Enum):
    """Language codes used in i3 API responses."""

    FR = "fr"
    EN = "en"


class LocalizedText(BaseModel):
    """A text string with its language identifier."""

    model_config = ConfigDict(extra="ignore")

    language: Language
    text: str


class ActivePeriod(BaseModel):
    """Time period when an alert is active.

    Note: This is a single object in the i3 API, not a list.
    """

    model_config = ConfigDict(extra="ignore")

    start: int | None = None
    end: int | None = None


class InformedEntity(BaseModel):
    """Entity affected by an alert (route, direction, or stop).

    Each field is optional as entities can specify any combination.
    """

    model_config = ConfigDict(extra="ignore")

    route_short_name: str | None = None
    direction_id: str | None = None
    stop_code: str | None = None


class Alert(BaseModel):
    """A single service alert from the i3 API."""

    model_config = ConfigDict(extra="ignore")

    active_periods: ActivePeriod | None = None
    cause: str | None = None
    effect: str | None = None
    informed_entities: list[InformedEntity] = []
    header_texts: list[LocalizedText] = []
    description_texts: list[LocalizedText] = []


class I3Header(BaseModel):
    """Header from the i3 API response."""

    model_config = ConfigDict(extra="ignore")

    timestamp: int


class I3Response(BaseModel):
    """Top-level response from the i3 etatservice endpoint."""

    model_config = ConfigDict(extra="ignore")

    header: I3Header
    alerts: list[Alert] = []
