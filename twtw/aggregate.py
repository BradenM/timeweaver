#!/usr/bin/env python3.8

from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from rich.console import Console
from rich.table import Column, Table

from . import tw


def get_aggregates():
    table = Table(
        Column("Project", style="bold"),
        Column("Entries", justify="right"),
        Column("Total Time", justify="right"),
        title="Total Hours",
        expand=True,
    )

    con = Console()

    _, data = tw.parse_timewarrior(process=False)
    table_data = {}

    for entry in data:
        try:
            proj = entry["tags"][2]
        except IndexError:
            continue
        if proj not in table_data:
            table_data[proj] = [0, relativedelta()]
        # add entry
        table_data[proj][0] += 1
        # add time
        start = dateparser.isoparse(entry["start"]).astimezone()
        end = dateparser.isoparse(entry["end"]).astimezone()
        delta = relativedelta(end, start)
        table_data[proj][1] += delta

    results = sorted(table_data.items(), key=lambda item: item[1][0], reverse=True)

    for proj, data in results:
        total_time = f"{data[1].hours}h {data[1].minutes}m"
        table.add_row(proj, str(data[0]), total_time)

    con.print(table, justify="center")
