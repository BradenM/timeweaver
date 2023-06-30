"""TWTW CSV parsing."""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import dpath.util
from dateutil import parser as dateparser
from dateutil import relativedelta
from rich.console import Console
from rich.progress import track
from rich.table import Table, box

from twtw.teamwork import DATE_FORMAT, META_MAP, TIME_FORMAT, EntryMeta, post_teamwork_entry

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

    def _get_project_meta(self, activity: str) -> EntryMeta | None:
        with_gen = activity + ".GENERAL"
        meta = dpath.util.get(META_MAP, with_gen, separator=".", default=None)
        if not meta:
            meta = dpath.util.get(META_MAP, activity, separator=".", default=None)
        return meta

    @property
    def project_meta(self) -> EntryMeta:
        meta_norm = self.activity.upper().strip()
        meta_activity = "".join(p.upper().strip() for p in self.activity.split() if p)
        meta_opts = [
            self._get_project_meta(v)
            for v in (
                meta_activity,
                meta_norm,
            )
        ]
        meta = next((i for i in meta_opts if i), None)
        print(self.activity, meta_opts, meta)
        if not meta:
            raise RuntimeError(f"No meta could be found for activity: {self.activity}")
        return meta

    @classmethod
    def from_row(cls, data: dict[str, str | float]) -> Optional["CSVData"]:
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


def parse_csv(file_path: Path) -> list[CSVData]:
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
            "tags": ",".join({str(s) for s in meta.tags}),
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
        table.add_row(str(entry["entry-id"]), date, time, t_entry["description"], t_entry["tags"])
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
