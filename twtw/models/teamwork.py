from typing import TYPE_CHECKING, Annotated

from pydantic.v1 import BaseModel, Extra, Field

if TYPE_CHECKING:
    from .models import LogEntry


class TeamworkTimeEntryInput(BaseModel):
    description: str
    person_id: str = Field(..., alias="person-id")
    date: str
    time: str
    hours: str
    minutes: str
    billable: bool = Field(False, alias="isbillable")
    tags: str | None = None

    class Config:
        allow_population_by_field_name = True


class TeamworkTimeEntryRequest(BaseModel):
    time_entry: TeamworkTimeEntryInput = Field(..., alias="time-entry")

    class Config:
        allow_population_by_field_name = True

    @classmethod
    def from_entry(cls, *, entry: "LogEntry", person_id: str):
        # DATE_FORMAT = "%Y%m%d"
        # TIME_FORMAT = "%H:%M"
        start_date = f"{entry.time_entry.start:%Y%m%d}"
        start_time = f"{entry.time_entry.start:%H:%M}"
        tags = ",".join(entry.project.resolve_tags())
        body = TeamworkTimeEntryInput(
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
    time_log_id: int | None = Field(None, alias="timeLogId")
    status: str = Field(..., alias="STATUS")


class TeamworkTag(BaseModel):
    class Config:
        extra = Extra.allow
        allow_population_by_field_name = True

    id: str | None = None
    name: str | None = None
    color: str | None = None
    project_id: Annotated[str | None, Field(alias="project-id")] = None


class TeamworkTimeEntry(BaseModel):
    class Config:
        extra = Extra.allow
        allow_population_by_field_name = True

    avatar_url: Annotated[str | None, Field(alias="avatarUrl")] = None
    can_edit: Annotated[bool | None, Field(alias="canEdit")] = None
    company_id: Annotated[str | None, Field(alias="company-id")] = None
    company_name: Annotated[str | None, Field(alias="company-name")] = None
    created_at: Annotated[str | None, Field(alias="createdAt")] = None
    date: str | None = None
    date_user_perspective: Annotated[str | None, Field(alias="dateUserPerspective")] = None
    description: str | None = None
    has_start_time: Annotated[str | None, Field(alias="has-start-time")] = None
    hours: str | None = None
    hours_decimal: Annotated[float | None, Field(alias="hoursDecimal")] = None
    id: str | None = None
    invoice_no: Annotated[str | None, Field(alias="invoiceNo")] = None
    invoice_status: Annotated[str | None, Field(alias="invoiceStatus")] = None
    isbillable: str | None = None
    isbilled: str | None = None
    minutes: str | None = None
    parent_task_id: Annotated[str | None, Field(alias="parentTaskId")] = None
    parent_task_name: Annotated[str | None, Field(alias="parentTaskName")] = None
    project_id: Annotated[str | None, Field(alias="project-id")] = None
    project_name: Annotated[str | None, Field(alias="project-name")] = None
    project_status: Annotated[str | None, Field(alias="project-status")] = None
    tags: list[TeamworkTag] | None = None
    task_estimated_time: Annotated[str | None, Field(alias="taskEstimatedTime")] = None
    todo_item_id: Annotated[str | None, Field(alias="todo-item-id")] = None
    task_is_private: Annotated[str | None, Field(alias="taskIsPrivate")] = None
    task_is_sub_task: Annotated[str | None, Field(alias="taskIsSubTask")] = None
    todo_item_name: Annotated[str | None, Field(alias="todo-item-name")] = None
    task_tags: Annotated[list | None, Field(alias="task-tags")] = None
    todo_list_id: Annotated[str | None, Field(alias="todo-list-id")] = None
    tasklist_id: Annotated[str | None, Field(alias="tasklistId")] = None
    todo_list_name: Annotated[str | None, Field(alias="todo-list-name")] = None
    ticket_id: Annotated[str | None, Field(alias="ticket-id")] = None
    updated_date: Annotated[str | None, Field(alias="updated-date")] = None
    user_deleted: Annotated[bool | None, Field(alias="userDeleted")] = None
    person_first_name: Annotated[str | None, Field(alias="person-first-name")] = None
    person_id: Annotated[str | None, Field(alias="person-id")] = None
    person_last_name: Annotated[str | None, Field(alias="person-last-name")] = None


class TeamworkTimeEntriesList(BaseModel):
    class Config:
        extra = Extra.allow
        allow_population_by_field_name = True

    status: Annotated[str | None, Field(alias="STATUS")] = None
    time_entries: Annotated[list[TeamworkTimeEntry] | None, Field(alias="time-entries")] = None
