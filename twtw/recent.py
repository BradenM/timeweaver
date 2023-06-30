from collections import defaultdict
from datetime import timedelta
from typing import cast

import arrow
import dateutil.tz as tz
import dateutil.utils as dutil
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from twtw.api.ui import Reporter
from twtw.models.abc import EntriesSource
from twtw.models.intervals import IntervalAggregator
from twtw.models.timewarrior import TimeWarriorLoader

from . import _taskw as taskw
from . import tw

# DATE_FORMAT = "%Y-%m-%d"
DATE_FORMAT = "%b %d (%a)"
INTERVAL_FORMAT = "%H:%M"
TIME_FORMAT = "%-I:%M%p"


def get_project_aggregates(days: int | None = None):
    filters = [
        lambda v: "@work" not in v["tags"],
    ]
    if days is not None:
        min_date = arrow.now().shift(days=-days)
        filters.append(lambda v: arrow.get(v.get("end", min_date.shift(days=-1))) <= min_date)

    source = EntriesSource.from_loader(TimeWarriorLoader, filters=filters)
    loader: TimeWarriorLoader = cast(TimeWarriorLoader, source.loader)

    project_aggrs: defaultdict[str, IntervalAggregator] = defaultdict(IntervalAggregator)

    for entry in loader.entries:
        if not entry.interval:
            continue
        proj_tags = ",".join(entry.tags)
        tags = set(entry.tags)
        tags -= {"@work", "logged", entry.annotation}
        if twtw_id := next((i for i in tags if "twtw" in i), None):
            tags -= {twtw_id}
        proj_name = next(
            (
                i
                for i in tags
                if len([part for part in i.split(".") if part.strip()]) <= 2 and len(i.split()) == 1
            ),
            None,
        )
        if not proj_name:
            print("Could not determine project from tags:", proj_tags)
            continue
        aggr_name = proj_name.lower().strip()
        aggr = project_aggrs[aggr_name]
        project_aggrs[aggr_name] = aggr.add(entry.interval)

    print(project_aggrs)
    return project_aggrs


def get_recent_v2(days: int, unlogged: bool = False):
    min_date = arrow.now().shift(days=-days)
    filters = [
        lambda v: "@work" not in v["tags"],
        lambda v: arrow.get(v.get("end", min_date.shift(days=-1))) <= min_date,
        lambda v: "logged" in v["tags"] if unlogged else False,
    ]
    source = EntriesSource.from_loader(TimeWarriorLoader, filters=filters)
    loader: TimeWarriorLoader = cast(TimeWarriorLoader, source.loader)

    reporter = Reporter()

    table_width = round(reporter.console.width // 1.15)
    table = Table(
        show_footer=True,
        show_header=True,
        header_style="bold bright_white",
        box=box.SIMPLE_HEAD,
        width=table_width,
        title="Overview",
    )
    table.add_column("ID")
    table.add_column("Log")
    table.add_column("Project", no_wrap=True)
    table.add_column("Description", no_wrap=True, overflow="fold", max_width=table_width // 3)
    table.add_column("Date", no_wrap=True)
    table.add_column(
        "Time", Text.from_markup("[b]Log Total", justify="right"), no_wrap=True, justify="right"
    )
    table.add_column("Duration", no_wrap=True, justify="right")

    time_aggr = IntervalAggregator()

    for entry in loader.entries:
        if not entry.interval:
            continue
        proj_tags = ",".join(entry.tags)
        tags = set(entry.tags)
        tags -= {"@work", "logged", entry.annotation}
        if twtw_id := next((i for i in tags if "twtw" in tags), None):
            tags -= {twtw_id}
        project_name = next(iter(tags), f"[bold]Unknown:[/b] {proj_tags}")
        time_aggr = time_aggr.add(entry.interval)
        logged = "✓" if "logged" in entry.tags else "✘"
        table.add_row(
            str(entry.id),
            logged,
            project_name,
            entry.truncated_annotation(table_width // 3),
            entry.interval.day,
            entry.interval.span,
            entry.interval.padded_duration,
            style="bright_white",
        )
    table.columns[5].footer = Text.from_markup(
        f"[u bright_green]{time_aggr.duration}", justify="right"
    )
    reporter.console.print(Align.center(Panel(table, padding=(1, 3))))


def get_recent_entries(days=3, unlogged=False):
    _, data = tw.parse_timewarrior(process=True)
    task_data = taskw.TaskWarriorData()
    for entry in data:
        is_logged = "logged" in entry["tags"]
        if unlogged and is_logged:
            continue
        if unlogged is True or dutil.within_delta(
            dutil.datetime.now(tz=tz.tzlocal()),
            entry["end"],
            timedelta(hours=24 * days),
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


def get_recent(*args, **kwargs):
    get_recent_v2(*args, **kwargs)
    # con = Console()
    #
    # table = Table(
    #     "ID",
    #     "Date",
    #     "Project",
    #     "Time",
    #     "Range",
    #     Column("Log", justify="center"),
    #     "Description",
    #     title="Recent Entries",
    #     expand=True,
    #     box=box.SQUARE,
    #     show_lines=True,
    # )
    # totals = (0, 0)
    # for hours, minutes, e in get_recent_entries(*args, **kwargs):
    #     totals = (
    #         totals[0] + hours,
    #         totals[1] + minutes,
    #     )
    #     table.add_row(*[str(a) for a in e])
    #
    # hours, minutes = totals
    # hours += minutes // 60
    # minutes = minutes % 60
    #
    # # days_range = days=kwargs.get('days', 3)
    # # delta_since = timedelta(days=-days_range)
    #
    # con.print(table)
    # con.print(f"\n[white][bold]Total Time:[/bold] {hours}hrs {minutes}mins[/white]\n")
