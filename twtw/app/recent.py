from collections import defaultdict
from typing import Any, Optional, Protocol, cast

import arrow
import attrs
import typer
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from twtw.api.ui import Reporter
from twtw.models.abc import EntriesSource
from twtw.models.intervals import IntervalAggregator
from twtw.models.timewarrior import TimeWarriorEntry, TimeWarriorLoader


class EntriesFilter(Protocol):
    def __call__(self, v: dict[str, Any]) -> bool:
        ...


@attrs.define
class DaysFilter(EntriesFilter):
    days: int

    def __call__(self, v: dict[str, Any]) -> bool:
        min_date = arrow.now().shift(days=-self.days)
        return arrow.get(v.get("end", min_date.shift(days=-1))) <= min_date


@attrs.define
class DateFilter(EntriesFilter):
    date: arrow.Arrow

    @classmethod
    def from_string(cls, date: str) -> "DateFilter":
        return cls(arrow.get(date))

    def __call__(self, v: dict[str, Any]) -> bool:
        start_date = arrow.get(v["start"])
        end = v.get("end", None)
        if not end:
            return True
        if start_date.date() == self.date.date():
            print(f"({v['id']}) Start: ({start_date}) == {self.date}")
            return False
        return True


@attrs.define
class TagFilter(EntriesFilter):
    tag: str
    exclude: bool = False

    def __call__(self, v: dict[str, Any]) -> bool:
        if self.exclude:
            return self.tag in v["tags"]
        return self.tag not in v["tags"]


@attrs.define
class DataLoader:
    filters: list[EntriesFilter] = attrs.field(factory=list)

    def load_data(self) -> list[TimeWarriorEntry]:
        source = EntriesSource.from_loader(TimeWarriorLoader, filters=self.filters)
        loader: TimeWarriorLoader = cast(TimeWarriorLoader, source.loader)
        return cast(list[TimeWarriorEntry], loader.entries)


@attrs.define
class DataAggregator:
    entries: list[TimeWarriorEntry]

    def get_aggregrates(self) -> defaultdict[str, IntervalAggregator]:
        aggregates: defaultdict[str, IntervalAggregator] = defaultdict(IntervalAggregator)
        for entry in self.entries:
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
                    if len([part for part in i.split(".") if part.strip()]) <= 2
                    and len(i.split()) == 1
                ),
                None,
            )
            if not proj_name:
                print("Could not determine project from tags:", proj_tags)
                continue
            aggr_name = proj_name.lower().strip()
            aggr = aggregates[aggr_name]
            aggregates[aggr_name] = aggr.add(entry.interval)
        return aggregates


app = typer.Typer(no_args_is_help=True)


@app.callback()
def recent():
    """View and aggregate recent time entries."""


@app.command(name="view")
def get_recent(days: int = 1, unlogged: bool = False, date: str | None = None):
    """Get recent entries."""
    filters = [TagFilter("@work"), DaysFilter(days)]
    if unlogged:
        filters.append(TagFilter("logged", exclude=True))
    if date:
        filters = [TagFilter("@work"), DateFilter.from_string(date)]
    loader = DataLoader(filters=filters)
    entries = loader.load_data()
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
    for entry in entries:
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


@app.command(name="aggregate")
def do_aggregate(days: Optional[int] = None):  # noqa: UP007
    """Aggregate recent entries by project."""
    filters = [
        TagFilter("@work"),
    ]
    if days is not None:
        filters.append(DaysFilter(days))
    loader = DataLoader(filters=filters)
    entries = loader.load_data()
    aggregator = DataAggregator(entries=entries)
    reporter = Reporter()
    table_width = round(reporter.console.width // 1.15)
    table = Table(
        show_footer=True,
        show_header=True,
        header_style="bold bright_white",
        box=box.SIMPLE_HEAD,
        width=table_width,
        title="Project Aggregates",
    )
    table.add_column("Project", no_wrap=True)
    table.add_column("Total", no_wrap=True, justify="right")
    project_aggrs = aggregator.get_aggregrates()
    for project, aggr in project_aggrs.items():
        table.add_row(project, aggr.duration)
    reporter.console.print(Align.center(Panel(table, padding=(1, 3))))
