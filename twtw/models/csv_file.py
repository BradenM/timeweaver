from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import attrs
from dateutil import parser as dparser

from twtw.models.abc import EntryLoader, RawEntry

if TYPE_CHECKING:
    from twtw.models.models import Project

CSVRawData = TypedDict(
    "CSVRawData",
    {"Activity type": str, "Duration": str, "From": str, "Comment": str, "id": str | None},
    total=False,
)


@attrs.define
class CSVRawEntry(RawEntry):
    @property
    def is_logged(self) -> bool:
        return False

    def is_project(self, project: Project) -> bool:
        if (teamw_project := project.resolve_teamwork_project()) is None:
            return False
        return teamw_project.name in self.tags

    def add_tag(self, *_) -> CSVRawEntry:
        return self


@attrs.define
class CSVEntryLoader(EntryLoader):
    def load(self, csv_path: str, *args, **kwargs) -> Iterator[CSVRawData]:
        if not csv_path:
            raise TypeError(
                f"CSVEntryLoader.load expected `csv_path` arg of type str, received: {type(csv_path)}."
            )
        csv_path = Path(csv_path).absolute()
        if not csv_path.exists() or not csv_path.is_file():
            raise FileNotFoundError(f"Path ({csv_path}) either does not exist or is not a file.")
        with csv_path.open(newline="") as rows:
            reader: Iterator[CSVRawData] = csv.DictReader(rows)
            for idx, row in enumerate(reader):
                if row.get("To", None) is not None and "Percent" not in row:
                    yield row | {"id": idx}

    def process(self, data: CSVRawData, *args, **kwargs) -> CSVRawEntry | None:
        start = dparser.parse(data["From"]).astimezone()
        end = dparser.parse(data["To"]).astimezone()
        return CSVRawEntry(
            id=data["id"],
            tags=[data["Activity type"].strip()],
            start=start,
            end=end,
            annotation=data["Comment"].strip(),
        )
