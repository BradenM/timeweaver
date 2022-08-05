from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Iterator, Optional

import attrs
import sh
from dateutil import parser as dparser
from pydantic import BaseModel

from twtw.models import TimeRange
from twtw.models.abc import EntryLoader, RawEntry


@attrs.define
class TimeWarriorRawEntry(RawEntry):
    @property
    def is_logged(self) -> bool:
        return "logged" in self.tags

    def add_tag(self, value: str) -> TimeWarriorRawEntry:
        tw: sh.Command = sh.Command("timew")
        tw.tag(f"@{self.id}", value)
        self.tags.append(value)
        return self


@attrs.define
class TimeWarriorLoader(EntryLoader):
    def load(self, *args, **kwargs) -> Iterator[dict[str, str]]:
        tw: sh.Command = sh.Command("timew")
        data_raw = tw.export().stdout.decode()
        _data = json.loads(data_raw)
        for item in _data:
            if "@work" not in item["tags"]:
                continue
            yield item

    def process(self, data: dict[str, str], *args, **kwargs) -> TimeWarriorRawEntry | None:
        start = dparser.isoparse(data["start"]).astimezone()
        end = None
        if end := data.pop("end", False):
            end = dparser.isoparse(end).astimezone()
        return TimeWarriorRawEntry(**data, start=start, end=end)


class TimeWarriorEntry(BaseModel):
    id: int
    start: datetime
    end: Optional[datetime] = None
    tags: list[str]
    annotation: Optional[str]

    @classmethod
    def load_entries(cls, *filters: Callable[[dict], bool]) -> Iterator["TimeWarriorEntry"]:
        tw: sh.Command = sh.Command("timew")
        data_raw = tw.export().stdout.decode()
        _data = json.loads(data_raw)
        for item in _data:
            if "@work" not in item["tags"]:
                continue
            if any((filt(item)) for filt in filters):
                continue
            start = dparser.isoparse(item.pop("start")).astimezone()
            end = None
            if "end" in item:
                end = dparser.isoparse(item.pop("end")).astimezone()
            yield cls(**item, start=start, end=end)

    @classmethod
    def unlogged_entries(cls) -> Iterator["TimeWarriorEntry"]:
        return cls.load_entries(lambda t: "logged" in t["tags"])

    @classmethod
    def unlogged_by_project(cls, project_name: str) -> Iterator["TimeWarriorEntry"]:
        _name = project_name.lower()
        return cls.load_entries(
            lambda t: "logged" in t["tags"],
            lambda t: _name not in t["tags"],
            lambda t: "end" not in t,
        )

    @property
    def is_active(self) -> bool:
        return self.start is not None and not self.end

    @property
    def interval(self) -> Optional[TimeRange]:
        if not self.is_active:
            return TimeRange(start=self.start, end=self.end)

    @property
    def description(self) -> str:
        _tags = ",".join(self.tags)
        return f"{_tags}: {self.annotation}"

    def add_tags(self, *tags: str) -> "TimeWarriorEntry":
        tw: sh.Command = sh.Command("timew")
        tw.tag(f"@{self.id}", *tags)
        _new_tags = {*self.tags, *tags}
        self.tags = list(_new_tags)
        return self

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, TimeWarriorEntry) and self.id == other.id

    def __str__(self):
        _tags = set(self.tags)
        _tags -= {"@work"}
        _annotation = ""
        if self.annotation:
            _annotation = f"- '{self.annotation}'"
        _tags = ", ".join(_tags)
        return "@{s.id} ({s.interval.day}, {s.interval.duration}, {s.interval.span}): {tags} {annot}".format(
            s=self, tags=_tags, annot=_annotation
        )
