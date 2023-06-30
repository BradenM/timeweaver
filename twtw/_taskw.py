# -*- coding: utf-8 -*-

"""Taskwarrior module."""

import json
import subprocess as sp
from dataclasses import dataclass
from typing import List


@dataclass
class TaskWarriorEntry:
    id: int
    description: str
    project: str
    tags: List[str]
    uuid: str


@dataclass
class TaskWarriorData:
    entries: List[TaskWarriorEntry]

    def __init__(self):
        proc = sp.run(["/usr/bin/task", "export"], stdout=sp.PIPE, text=True)
        lines = proc.stdout
        data = json.loads(lines)
        entries = []
        for raw_e in data:
            _fields = {k: raw_e.get(k) for k in TaskWarriorEntry.__dataclass_fields__}
            entries.append(TaskWarriorEntry(**_fields))
        self.entries = entries

    @property
    def projects(self):
        return set([e.project for e in self.entries if e.project])
