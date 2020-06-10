#!/usr/bin/env python3

"""TimeWarrior Teamwork Plugin

Plugin for TimeWarrior for integration with Teamwork.
Publishes any entries w/o a 'logged' tag, then tags them
as logged.

"""

import sys
import json
from pprint import pprint
from enum import Enum
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from collections import namedtuple
import requests
import subprocess as sp
from pathlib import Path
import os
from dotenv import load_dotenv

ROSS_ID = os.getenv('TEAMWORK_ID')

DATE_FORMAT = "%Y%m%d"
TIME_FORMAT = "%H:%M"


class Project(Enum):
    ARROYODEV = ***REMOVED***
    ***REMOVED*** = ***REMOVED***
    ***REMOVED*** = ***REMOVED***


class Task(Enum):
    ***REMOVED*** = ***REMOVED***
    ***REMOVED*** = ***REMOVED***


class Tag(Enum):
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"


EntryMeta = namedtuple("EntryMeta", ["project", "task", "tags"])

META_MAP = {
    "***REMOVED***": EntryMeta(
        Project.ARROYODEV.value, Task.***REMOVED***.value, [Tag.***REMOVED***.value]
    ),
    "PATIENTCONNECT": EntryMeta(
        Project.***REMOVED***.value,
        None,
        [Tag.***REMOVED***.value, Tag.***REMOVED***.value, Tag.***REMOVED***.value],
    ),
    "***REMOVED***STOCK": EntryMeta(Project.ARROYODEV.value, None, [Tag.***REMOVED***.value]),
    "***REMOVED***": EntryMeta(Project.***REMOVED***.value, Task.***REMOVED***.value, []),
    "ARROYODEV": EntryMeta(Project.ARROYODEV.value, None, [Tag.***REMOVED***.value]),
}


def parse_input():
    lines = sys.stdin.readlines()
    gap = lines.index("\n")
    config = lines[:gap]
    data = json.loads("".join(lines[gap:]))
    return config, data


def get_description(title, annotation):
    print("Get Description")
    default_text = f"# {title}\n{annotation}"
    return default_text


def create_teamwork_entry(data):
    annotation = data.get("annotation", "no annotation found!")
    tags = ", ".join(data["tags"])
    desc = get_description(tags, annotation)
    meta_name = data["tags"][0].upper()
    project = Project.__dict__.get(meta_name, Project.ARROYODEV).value
    meta = META_MAP.get(meta_name, EntryMeta(project, None, []))
    start = dateparser.isoparse(data["start"]).astimezone()
    end = dateparser.isoparse(data["end"]).astimezone()
    delta = relativedelta(end, start)

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
            "tags": ",".join((str(s) for s in meta.tags)),
        },
    }


def post_teamwork_entry(entry):
    endpoint = entry.pop("endpoint")
    entry_id = entry.pop("entry-id")
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
    headers = {
        "Authorization": f"Basic {os.getenv('TEAMWORK_TOKEN')}"
    }
    print("\nPublishing entry:")
    pprint(entry, indent=4)
    print(endpoint, headers, entry)
    resp = requests.post(endpoint, headers=headers, json=entry)
    resp.raise_for_status()
    tag_timew_entry(entry_id, "logged")


def tag_timew_entry(entry_id, tag):
    bin = "/usr/bin/timew"
    cmd = [bin, "tag", f"@{entry_id}", tag]
    print(f"Tagging entry @{entry_id} as logged!")
    sp.run(cmd).check_returncode()


_, data = parse_input()

unlogged_entries = [d for d in data if "logged" not in d["tags"]]
entries = [create_teamwork_entry(d) for d in unlogged_entries]


for entry in entries:
    post_teamwork_entry(entry)
