# -*- coding: utf-8 -*-

"""TWTW CSV parsing."""

import csv
from pathlib import Path
from dataclasses import dataclass
from dateutil import parser as dateparser, relativedelta
from typing import Union, Dict, Optional, List
import dpath.util
from twtw.teamwork import (
    META_MAP,
    EntryMeta,
    DATE_FORMAT,
    TIME_FORMAT,
    post_teamwork_entry,
)
from twtw import config

from rich.console import Console
from rich.table import Table, box
from rich.progress import track


ROSS_ID = os.getenv('TEAMWORK_ID')


@dataclass
class CSVData:
    activity: str
    duration: float
    time_from: str
    time_to: str
    comment: str

    @property
    def start(self):
        return dateparser.parse(self.time_from).astimezone()

    @property
    def end(self):
        return dateparser.parse(self.time_to).astimezone()

    @property
    def project_meta(self) -> EntryMeta:
        meta_activity = self.activity.upper().strip()
        meta_general = meta_activity + ".GENERAL"
        meta = dpath.util.get(META_MAP, meta_general, separator=".", default=None)
        print(self.activity, meta_general)
        if not meta:
            meta = dpath.util.get(META_MAP, meta_activity, separator=".", default=None)
        if not meta:
            raise RuntimeError(f"No meta could be found for activity: {self.activity}")
        return meta

    @classmethod
    def from_row(cls, data: Dict[str, Union[str, float]]) -> Optional["CSVData"]:
        time_to = data.get("To", None)
        if time_to:
            activity = data["Activity type"]
            duration = data["Duration"]
            time_from = data["From"]
            comment = data["Comment"]
            return cls(
                activity=activity,
                duration=duration,
                time_from=time_from,
                time_to=time_to,
                comment=comment,
            )


def parse_csv(file_path: Path) -> List[CSVData]:
    entries = []
    with file_path.open(newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            entry = CSVData.from_row(row)
            if entry:
                entries.append(entry)
    return entries


def create_teamwork_entry(entry: CSVData):
    meta = entry.project_meta
    base_uri = "***REMOVED***"
    endpoint = f"/projects/{meta.project}/time_entries.json"
    delta = relativedelta.relativedelta(entry.end, entry.start)
    return {
        "endpoint": base_uri + endpoint,
        "entry-id": -1,
        "time-entry": {
            "description": entry.comment,
            "person-id": str(ROSS_ID),
            "date": entry.start.date().strftime(DATE_FORMAT),
            "time": entry.start.time().strftime(TIME_FORMAT),
            "hours": str(delta.hours),
            "minutes": str(delta.minutes),
            "isbillable": False,
            "tags": ",".join(set((str(s) for s in meta.tags))),
        },
    }


def load_entries(csv_path: Path, commit=False):
    con = Console()
    entries = parse_csv(csv_path)

    entries = [create_teamwork_entry(d) for d in entries]

    table = Table(
        "Entry",
        "Date",
        "Time",
        "Description",
        "Tags",
        title="Teamwork Entries",
        show_lines=True,
        box=box.HEAVY_EDGE,
    )

    totals = (0, 0)
    for entry in track(
        reversed(entries), description="Processing...", total=len(entries), console=con
    ):
        t_entry = entry["time-entry"]
        date = f'{t_entry["date"]} {t_entry["time"]}'
        time = ":".join((t_entry["hours"], t_entry["minutes"]))
        totals = (
            totals[0] + int(t_entry["hours"]),
            totals[1] + int(t_entry["minutes"]),
        )
        table.add_row(
            str(entry["entry-id"]), date, time, t_entry["description"], t_entry["tags"]
        )
        if t_entry["hours"] == "0" and t_entry["minutes"] == "0":
            con.print(entry)
            con.print(
                f'[bold red]Skipping entry: [/][bold bright_white]{entry["entry-id"]}[/][bold red] because it contains no time to log!'
            )
            continue
        if commit:
            post_teamwork_entry(entry, con, is_timewarrior=False)
        else:
            con.print(entry)

    con.print(table)

    hours, minutes = totals
    hours += minutes // 60  # Get extra hours from minutes
    minutes = minutes % 60  # Get remainder minutes
    con.print(f"\n[white][bold]Total Time:[/bold] {hours}hrs {minutes}mins[/white]\n")
