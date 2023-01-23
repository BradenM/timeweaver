from __future__ import annotations

import abc
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, TypeVar

import attrs

from twtw.models import TimeRange

if TYPE_CHECKING:
    from twtw.models.models import Project

RawEntryData = TypeVar("RawEntryData", bound=dict)


@attrs.define
class RawEntry(abc.ABC):
    id: int
    tags: list[str]
    start: datetime
    end: datetime | None = attrs.field(default=None)
    annotation: str = attrs.field(default="")

    def __str__(self):
        _tags = set(self.tags)
        _tags -= {"@work"}
        _annot = "- '{}'".format(self.truncated_annotation()) if self.annotation else ""
        _tags = ", ".join(_tags)
        return "@{s.id} ({s.interval.day}, {s.interval.duration}, {s.interval.span}): {tags} {annot}".format(
            s=self, tags=_tags, annot=_annot
        )

    def truncated_annotation(self, length: int = 20) -> str:
        return (
            "{:.<{elip}.{len}}".format(
                self.annotation,
                elip=length + 3 if len(self.annotation) >= length else len(self.annotation),
                len=length,
            )
            if self.annotation
            else ""
        )

    @property
    def is_active(self) -> bool:
        return self.start is not None and not self.end

    @property
    def interval(self) -> TimeRange | None:
        if not self.is_active:
            return TimeRange(start=self.start, end=self.end)

    @property
    def description(self) -> str:
        _tags = ",".join(self.tags)
        return f"{_tags}: {self.annotation}"

    @property
    @abc.abstractmethod
    def is_logged(self) -> bool:
        ...

    @abc.abstractmethod
    def is_project(self, project: Project) -> bool:
        ...

    @abc.abstractmethod
    def add_tag(self, value: str) -> RawEntry:
        ...

    def add_tags(self, *values: str) -> RawEntry:
        for v in values:
            self.add_tag(v)
        return self


@attrs.define
class EntryLoader(abc.ABC):
    entries: list[RawEntry] = attrs.field(factory=list)
    loaded: bool = attrs.field(default=False)

    @abc.abstractmethod
    def load(self, *args, **kwargs) -> Iterable[RawEntryData]:
        ...

    @abc.abstractmethod
    def process(self, data: RawEntryData, *args, **kwargs) -> RawEntry | None:
        ...

    def populate(self, *args, **kwargs) -> None:
        self.loaded = True
        datas = self.load(*args, **kwargs)
        self.entries.extend([self.process(d, *args, **kwargs) for d in datas if d])


@attrs.define(slots=False)
class EntriesSource:
    loader: EntryLoader

    @classmethod
    def from_loader(cls, loader: EntryLoader | type[EntryLoader], *args, **kwargs) -> EntriesSource:
        if not isinstance(loader, EntryLoader):
            loader: EntryLoader = loader()
        if not loader.loaded:
            loader.populate(*args, **kwargs)
        return cls(loader=loader)

    @property
    def unlogged_entries(self) -> list[RawEntry]:
        return [e for e in self.loader.entries if not e.is_logged and not e.is_active]

    def unlogged_by_project(self, project: Project):
        return [e for e in self.unlogged_entries if e.is_project(project)]
