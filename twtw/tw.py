import sys
import json
import subprocess as sp

from dateutil import parser as dparser
from dateutil.relativedelta import relativedelta


def parse_timewarrior(process=False):
    # lines = sys.stdin.readlines()
    proc = sp.run(["/usr/bin/timew", "export"], stdout=sp.PIPE, text=True)
    lines = proc.stdout
    data = json.loads(lines)
    # gap = lines.index("\n")
    # config = lines[:gap]
    # data = json.loads("".join(lines[gap:]))
    if process:
        data = [parse_entry(d) for d in data if "end" in d]
    return {}, data


def parse_taskwarrior():
    proc = sp.run(["/usr/bin/task", "export"], stdout=sp.PIPE, text=True)
    lines = proc.stdout
    data = json.loads(lines)
    return data


def iter_task_projects():
    data = parse_taskwarrior()
    for item in data:
        if proj := item.get('project'):
            yield proj


def get_entry_dates(entry):
    start = dparser.isoparse(entry["start"]).astimezone()
    end = dparser.isoparse(entry["end"]).astimezone()
    return start, end


def get_entry_interval(entry):
    start, end = get_entry_dates(entry)
    delta = relativedelta(end, start)
    return delta


def parse_entry(entry):
    start, end = get_entry_dates(entry)
    interval = get_entry_interval(entry)
    entry.update(dict(start=start, end=end, interval=interval))
    return entry


def timew(*args):
    """Execute TimeWarrior Command"""
    bin_path = "/usr/bin/timew"
    cmd_args = list(args)
    cmd_args.insert(0, bin_path)
    sp.run(cmd_args).check_returncode()


def annotate_entry(entry_id, annotation):
    """Annotates a time entry"""
    entry_id = str(entry_id)
    tw_id = entry_id if "@" in entry_id else f"@{entry_id}"
    return timew("annotate", tw_id, annotation)
