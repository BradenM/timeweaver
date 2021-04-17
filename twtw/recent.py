#!/usr/bin/env python3.8

import json
import sys
from datetime import timedelta

import dateutil.tz as tz
import dateutil.utils as dutil
from rich import box
from rich.console import Console
from rich.table import Column, Table

from . import taskw, tw

DATE_FORMAT = "%Y-%m-%d"
INTERVAL_FORMAT = "%H:%M"
TIME_FORMAT = "%-I:%M%p"


def get_recent_entries():
    _, data = tw.parse_timewarrior(process=True)
    task_data = taskw.TaskWarriorData()
    for entry in data:
        if dutil.within_delta(
            dutil.datetime.now(tz=tz.tzlocal()), entry["end"], timedelta(days=15)
        ):
            time = f"{entry['interval'].hours}h {entry['interval'].minutes}m"
            desc = entry.get("annotation", entry["tags"][1])
            logged = "✓" if "logged" in entry["tags"] else "✘"
            range_start = entry["start"].strftime(TIME_FORMAT)
            range_end = entry["end"].strftime(TIME_FORMAT)
            proj_tag_idx = entry["tags"].index(
                next((t for t in entry["tags"] if t in task_data.projects))
            )
            # proj_tag_idx = 2 if '@work' in entry["tags"] else 1
            # if len(desc) >= 20:
            #     desc = desc[:20] + "..."
            yield int(entry["interval"].hours), int(entry["interval"].minutes), [
                entry["id"],
                entry["start"].strftime(DATE_FORMAT),
                entry["tags"][proj_tag_idx],
                time,
                f"{range_start}-{range_end}",
                logged,
                desc,
            ]


def get_recent():
    con = Console()

    table = Table(
        "ID",
        "Date",
        "Project",
        "Time",
        "Range",
        Column("Log", justify="center"),
        "Description",
        title="Recent Entries",
        expand=True,
        box=box.SQUARE,
        show_lines=True,
    )
    totals = (0, 0)
    for hours, minutes, e in get_recent_entries():
        totals = (
            totals[0] + hours,
            totals[1] + minutes,
        )
        table.add_row(*[str(a) for a in e])
    hours, minutes = totals
    hours += minutes // 60
    minutes = minutes % 60
    con.print(table)
    con.print(f"\n[white][bold]Total Time:[/bold] {hours}hrs {minutes}mins[/white]\n")
