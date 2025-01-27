from collections import defaultdict
from contextlib import nullcontext
from typing import Any, Protocol, cast

import arrow
import attrs
import typer
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sqlmodel import Session

from twtw.api.ui import Reporter
from twtw.models.abc import EntriesSource
from twtw.models.intervals import IntervalAggregator
from twtw.models.models import Project
from twtw.models.timewarrior import TimeWarriorEntry, TimeWarriorLoader
from twtw.session import engine


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
class DateRangeFilter(EntriesFilter):
    start: arrow.Arrow
    end: arrow.Arrow

    @classmethod
    def from_string(cls, start: str, end: str) -> "DateRangeFilter":
        return cls(start=arrow.get(start), end=arrow.get(end))

    def __call__(self, v: dict[str, Any]) -> bool:
        start_date = arrow.get(v["start"])
        if "end" not in v:
            return True
        end_date = arrow.get(v.get("end", arrow.now()))
        return not (self.start <= start_date <= self.end or self.start <= end_date <= self.end)


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

    def get_aggregrates(
        self, by_root: bool = False, session: Session | None = None
    ) -> defaultdict[str, IntervalAggregator]:
        aggregates: defaultdict[str, IntervalAggregator] = defaultdict(IntervalAggregator)
        for entry in self.entries:
            if not entry.interval:
                continue
            tags = set(entry.tags)
            tags -= {"@work", "logged", entry.annotation}
            if twtw_id := next((i for i in tags if "twtw" in i), None):
                tags -= {twtw_id}
            session_cm = nullcontext(session) if session else Session(engine)
            with session_cm as session:
                projects_from_tags = [
                    (Project.get_by_name(n, session), n) for n in tags if "." in n or " " not in n
                ]
                project = next((i[0] for i in projects_from_tags if i[0]), None)

            if not project:
                print("Could not determine project from tags:", projects_from_tags)
                continue
            if by_root:
                aggr_name = project.root.name.lower().strip()
            else:
                aggr_name = project.name.lower().strip()
            aggr = aggregates[aggr_name]
            aggregates[aggr_name] = aggr.add(entry.interval)
        return aggregates


app = typer.Typer(no_args_is_help=True)


@app.callback()
def recent():
    """View and aggregate recent time entries."""


def build_filters(
    *,
    date: str | None = None,
    days: int | None = None,
    end_date: str | None = None,
    unlogged: bool = False,
):
    filters = [TagFilter("@work")]
    if days is not None and not (date or end_date):
        filters.append(DaysFilter(days))
    if unlogged:
        filters.append(TagFilter("logged", exclude=True))
    if date:
        date_filter = (
            DateRangeFilter.from_string(date)
            if end_date is None
            else DateRangeFilter.from_string(date, end_date)
        )
        filters.append(date_filter)
    print(f"Filters: {filters}")
    return filters


@app.command(name="view")
def get_recent(
    days: int | None = None,
    unlogged: bool = False,
    date: str | None = None,
    end_date: str | None = None,
):
    """Get recent entries."""
    filters = build_filters(date=date, days=days, end_date=end_date, unlogged=unlogged)
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
def do_aggregate(
    days: int | None = None,
    unlogged: bool = False,
    date: str | None = None,
    end_date: str | None = None,
    by_root: bool = False,
):
    """Aggregate recent entries by project."""
    filters = [
        TagFilter("@work"),
    ]
    if days is not None:
        filters.append(DaysFilter(days))
    filters = build_filters(date=date, days=days, end_date=end_date, unlogged=unlogged)
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
    with Session(engine) as session:
        project_aggrs = aggregator.get_aggregrates(by_root=by_root, session=session)
        total = IntervalAggregator()
        for aggr in project_aggrs.values():
            for interval in aggr.intervals:
                total = total.add(interval)

        for project, aggr in sorted(
            project_aggrs.items(), key=lambda x: x[1].total_seconds, reverse=True
        ):
            share = (aggr.total_seconds / total.total_seconds) * 100
            table.add_row(project, f"{aggr.duration} ({share:.2f}%)", style="bright_white")
            for interval in aggr.intervals:
                total = total.add(interval)
        table.add_row("", "")
        table.add_row(
            "[b bright_white]Total",
            Text.from_markup(f"[u bright_green]{total.duration}", justify="right"),
        )

        min_day = min(i.start.date() for i in total.intervals)
        max_day = max(i.start.date() for i in total.intervals)
        _days = (max_day - min_day).days + 1

        # average per day
        avg_hours = total.total_seconds / (60 * 60 * _days)
        table.add_row(
            "[b bright_white]Daily",
            Text.from_markup(f"[u bright_green]{avg_hours:.2f}h/day", justify="right"),
        )
        # average per work week
        avg_hours_per_week = avg_hours * 7
        table.add_row(
            "[b bright_white]Weekly",
            Text.from_markup(f"[u bright_green]{avg_hours_per_week:.2f}h/week", justify="right"),
        )
        # average bi-weekly
        avg_hours_per_biweek = avg_hours_per_week * 2
        table.add_row(
            "[b bright_white]Bi-Weekly",
            Text.from_markup(
                f"[u bright_green]{avg_hours_per_biweek:.2f}h/bi-week", justify="right"
            ),
        )
        reporter.console.print(Align.center(Panel(table, padding=(1, 3))))
