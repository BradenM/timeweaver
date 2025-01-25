from __future__ import annotations

import abc
from collections.abc import Iterable
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, TypeVar

import attrs
from dateutil.parser import parse as date_parse

from twtw.models import TimeRange
from twtw.utils import truncate

if TYPE_CHECKING:
    from twtw.models.models import Project

RawEntryData = TypeVar("RawEntryData", bound=dict)


@attrs.define(frozen=True)
class RawEntry(abc.ABC):
    id: int
    tags: frozenset[str] = attrs.field(converter=frozenset)
    start: datetime = attrs.field(
        converter=lambda v: v if isinstance(v, datetime) else date_parse(v)
    )
    end: datetime | None = attrs.field(
        default=None,
        converter=lambda v: v if v is None else (v if isinstance(v, datetime) else date_parse(v)),
    )
    annotation: str = attrs.field(default="")

    def __str__(self) -> str:
        _tags = set(self.tags)
        _tags -= {"@work"}
        _annot = f"- '{self.truncated_annotation()}'" if self.annotation else ""
        _tags = ", ".join(_tags)
        return "@{s.id} ({s.interval.day}, {s.interval.duration}, {s.interval.span}): {tags} {annot}".format(
            s=self, tags=_tags, annot=_annot
        )

    def truncated_annotation(self, length: int = 20) -> str:
        return truncate(self.annotation, length=length)

    @property
    def is_active(self) -> bool:
        return self.start is not None and not self.end

    @property
    def interval(self) -> TimeRange | None:
        if not self.is_active:
            return TimeRange(start=self.start, end=self.end)
        return None

    @property
    def description(self) -> str:
        _tags = ",".join(self.tags)
        return f"{_tags}: {self.annotation}"

    @property
    @abc.abstractmethod
    def is_logged(self) -> bool:
        ...

    @property
    def is_drafted(self) -> bool:
        return False

    @abc.abstractmethod
    def is_project(self, project: Project) -> bool:
        ...

    @abc.abstractmethod
    def add_tag(self, value: str) -> RawEntry:
        ...

    @abc.abstractmethod
    def remove_tag(self, value: str) -> RawEntry:
        raise NotImplementedError

    def add_tags(self, *values: str) -> RawEntry:
        new = self
        for v in values:
            new = self.add_tag(v)
        return new


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

    @cached_property
    def unlogged_entries(self) -> list[RawEntry]:
        return [e for e in self.loader.entries if not e.is_logged and not e.is_active]

    def unlogged_by_project(self, project: Project):
        return [e for e in self.unlogged_entries if e.is_project(project)]
