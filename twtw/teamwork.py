#!/usr/bin/env python3

"""TimeWarrior Teamwork Plugin

Plugin for TimeWarrior for integration with Teamwork.
Publishes any entries w/o a 'logged' tag, then tags them
as logged.

"""

import json
import subprocess as sp
import sys
from collections import namedtuple
from enum import Enum
from pathlib import Path
from time import sleep
import click

import dpath.util
import requests
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table, box
from rich.progress import track

ROSS_ID = os.getenv('TEAMWORK_ID')

DATE_FORMAT = "%Y%m%d"
TIME_FORMAT = "%H:%M"


class Project(Enum):
    ARROYODEV = ***REMOVED***
    ***REMOVED*** = ***REMOVED***
    ***REMOVED*** = ***REMOVED***
    ***REMOVED*** = ***REMOVED***


class Task(Enum):
    ***REMOVED*** = ***REMOVED***
    ***REMOVED***_MEETING = ***REMOVED***
    ***REMOVED*** = ***REMOVED***


class Tag(Enum):
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"


EntryMeta = namedtuple("EntryMeta", ["project", "task", "tags"])

META_MAP = {
    "***REMOVED***": EntryMeta(Project.***REMOVED***.value, None, []),
    "***REMOVED***": {
        "***REMOVED***": EntryMeta(
            Project.***REMOVED***.value, Task.***REMOVED***.value, []
        )
    },
    "***REMOVED***": {
        "GENERAL": EntryMeta(
            Project.ARROYODEV.value,
            Task.***REMOVED***_MEETING.value,
            [Tag.***REMOVED***.value],
        ),
        "WEB": EntryMeta(
            Project.ARROYODEV.value, Task.***REMOVED***.value, [Tag.***REMOVED***.value]
        ),
        "API": EntryMeta(
            Project.ARROYODEV.value, Task.***REMOVED***.value, [Tag.***REMOVED***.value]
        ),
    },
    "***REMOVED***": {
        "GENERAL": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value]),
        "API": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value]),
        "APP": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value]),
    },
    "ARROYODEV": {"GENERAL": EntryMeta(Project.ARROYODEV.value, None, [])},
    "***REMOVED***": {"GENERAL": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value])},
    "***REMOVED***": {
        "GENERAL": EntryMeta(Project.ARROYODEV.value, None, [Tag.***REMOVED***.value]),
        "APP": EntryMeta(Project.ARROYODEV.value, None, [Tag.***REMOVED***.value]),
    },
    "***REMOVED***": EntryMeta(Project.ARROYODEV.value, None, []),
}


def parse_input():
    proc = sp.run(["/usr/bin/timew", "export"], stdout=sp.PIPE, text=True)
    lines = proc.stdout
    data = json.loads(lines)
    # gap = lines.index("\n")
    # config = lines[:gap]
    # data = json.loads("".join(lines[gap:]))
    return {}, data


def get_description(title, annotation):
    title_parts = [t.capitalize() for t in title.split(".")]
    formatted = " ".join(title_parts)
    default_text = f"# {formatted}\n{annotation}"
    return default_text


def get_meta_from_tags(tags):
    project = tags.pop(0).upper().split(".")
    meta = dpath.util.get(META_MAP, project)
    extra_tags = [Tag.__dict__.get(t.upper(), None) for t in tags]
    meta.tags.extend(set([t.value for t in extra_tags if t is not None]))
    return meta


def create_teamwork_entry(data):
    tags = data["tags"][1:]
    task_desc = tags.pop(0)
    annotation = data.get("annotation", task_desc)
    desc = get_description(tags[0], annotation)
    meta = get_meta_from_tags(tags)
    start = dateparser.isoparse(data["start"]).astimezone()
    end = dateparser.isoparse(data["end"]).astimezone()
    delta = relativedelta(end, start)
    # add extra tags
    extra_tags = [Tag.__dict__.get(t.upper(), None) for t in data["tags"][1:]]
    meta.tags.extend([t.value for t in extra_tags if t is not None])
    base_uri = "***REMOVED***"
    endpoint = f"/projects/{meta.project}/time_entries.json"
    if meta.task:
        endpoint = f"/tasks/{meta.task}/time_entries.json"
    return {
        "endpoint": base_uri + endpoint,
        "entry-id": data.get("id", -1),
        "time-entry": {
            "description": desc,
            "person-id": str(USER_ID),
            "date": start.date().strftime(DATE_FORMAT),
            "time": start.time().strftime(TIME_FORMAT),
            "hours": str(delta.hours),
            "minutes": str(delta.minutes),
            "isbillable": False,
            "tags": ",".join(set((str(s) for s in meta.tags))),
        },
    }


def post_teamwork_entry(entry, con):
    endpoint = entry.pop("endpoint")
    entry_id = entry.pop("entry-id")
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
    headers = {
        "Authorization": f"Basic dHdwX09FWmlzaHNiMUpCZ3F2emxDcmhlblliRzJJVUQ6IA=="
    }
    resp = requests.post(endpoint, headers=headers, json=entry)
    resp.raise_for_status()
    data = resp.json()
    con.print(data)
    assert data["STATUS"] == "OK", "Failed to create entry!"
    sleep(1)
    tag_timew_entry(entry_id, "logged", con)
    tag_timew_entry(entry_id, f"twtw:id:{data['timeLogId']}", con)


def tag_timew_entry(entry_id, tag, con):
    bin = "/usr/bin/timew"
    cmd = [bin, "tag", f"@{entry_id}", tag]
    con.print(f"[bold bright_white]Tagging entry @{entry_id} with:[/] [italic]{tag}!")
    sp.run(cmd, stdout=sp.PIPE).check_returncode()


def load_entries(commit=False):
    con = Console()
    _, data = parse_input()

    unlogged_entries = [
        d for d in data if "logged" not in d["tags"] and "@work" in d["tags"]
    ]
    con.print(unlogged_entries)
    entries = [create_teamwork_entry(d) for d in unlogged_entries]

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
            tag_timew_entry(entry["entry-id"], "logged", con)
            tag_timew_entry(entry["entry-id"], "twtw:invalid", con)
            continue
        if commit:
            post_teamwork_entry(entry, con)
        else:
            con.print(entry)

    con.print(table)

    hours, minutes = totals
    hours += minutes // 60  # Get extra hours from minutes
    minutes = minutes % 60  # Get remainder minutes
    con.print(f"\n[white][bold]Total Time:[/bold] {hours}hrs {minutes}mins[/white]\n")
