from pydantic.v1 import BaseModel
from pydantic.v1 import Field as PyField

from twtw.models.models import LogEntry


class TeamworkTimeEntry(BaseModel):
    description: str
    person_id: str = PyField(..., alias="person-id")
    date: str
    time: str
    hours: str
    minutes: str
    billable: bool = PyField(False, alias="isbillable")
    tags: str | None = None

    class Config:
        allow_population_by_field_name = True


class TeamworkTimeEntryRequest(BaseModel):
    time_entry: TeamworkTimeEntry = PyField(..., alias="time-entry")

    class Config:
        allow_population_by_field_name = True

    @classmethod
    def from_entry(cls, *, entry: "LogEntry", person_id: str):
        # DATE_FORMAT = "%Y%m%d"
        # TIME_FORMAT = "%H:%M"
        start_date = f"{entry.time_entry.start:%Y%m%d}"
        start_time = f"{entry.time_entry.start:%H:%M}"
        tags = ",".join(entry.project.resolve_tags())
        body = TeamworkTimeEntry(
            description=entry.description,
            person_id=str(person_id),
            date=start_date,
            time=start_time,
            hours=str(entry.time_entry.interval.delta.hours),
            minutes=str(entry.time_entry.interval.delta.minutes),
            tags=tags if tags else None,
        )
        return cls(time_entry=body)


class TeamworkTimeEntryResponse(BaseModel):
    time_log_id: int | None = PyField(None, alias="timeLogId")
    status: str = PyField(..., alias="STATUS")
