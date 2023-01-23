from __future__ import annotations

from pathlib import Path

import attrs
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from transitions import EventData, Machine

from twtw.models.abc import EntriesSource
from twtw.models.csv_file import CSVEntryLoader
from twtw.models.intervals import IntervalAggregator
from twtw.models.models import Project
from twtw.state.entry import BaseCreateEntryFlow, EntryContext, EntryFlowModel, FlowModifier


@attrs.define(slots=False)
class CSVCreateEntryFlow(BaseCreateEntryFlow):
    project: Project = attrs.field(default=None)
    path: Path = attrs.field(default=None)

    def load_context(self, event: EventData) -> None:  # noqa
        source = EntriesSource.from_loader(CSVEntryLoader, self.path)
        self.context: EntryContext = EntryContext(source=source)
        self.entry_machine = Machine(
            model=None,
            states=["init", "invalid", "skipped", "draft", "published", "complete"],
            send_event=True,
            initial="init",
            transitions=[
                {
                    "trigger": "validate",
                    "source": "*",
                    "dest": "invalid",
                    "unless": "has_project",
                },
                {
                    "trigger": "validate",
                    "source": "*",
                    "dest": "=",
                    "conditions": "has_project",
                },
                {"trigger": "skip", "source": "*", "dest": "skipped"},
                {"trigger": "next", "source": "skipped", "dest": "="},
                {
                    "trigger": "next",
                    "source": "init",
                    "dest": "invalid",
                    "unless": "has_project",
                },
                {
                    "trigger": "next",
                    "source": "invalid",
                    "dest": "=",
                    "unless": "has_project",
                },
                {
                    "trigger": "next",
                    "source": "init",
                    "dest": "draft",
                    "after": "create_entry_handler",
                },
                {
                    "trigger": "next",
                    "source": "draft",
                    "dest": "published",
                    "unless": ["dry_run"],
                    "after": "commit_entry_handler",
                },
                {
                    "trigger": "next",
                    "source": "draft",
                    "dest": "complete",
                    "conditions": ["dry_run"],
                },
                {
                    "trigger": "next",
                    "source": "published",
                    "dest": "complete",
                    "after": "save_entry_handler",
                },
            ],
        )

    def choose_entries(self, event: EventData):  # noqa
        disabled_help = "No Project Found!"
        results: list[EntryFlowModel] = self.reporter.prompt.multiselect(
            self.context.models,
            title="Choose Time Entries.",
            key=lambda e: str(e.raw_entry),
            disabled=lambda e: disabled_help if e.is_invalid() else None,
        )
        if not any(results):
            return self.cancel("no entries.")
        self.reporter.console.clear()
        for mod in self.entry_machine.models:
            if not mod.is_invalid() and mod not in results:
                mod.skip()
        self.context.flags |= FlowModifier.ENTRIES_SELECTED

    def create_drafts(self, event: EventData):  # noqa
        pass

    def review_drafts(self, event: EventData):  # noqa
        table_width = round(self.reporter.console.width // 1.15)
        table = Table(
            show_footer=True,
            show_header=True,
            header_style="bold bright_white",
            box=box.SIMPLE_HEAD,
            width=table_width,
            title="Overview",
        )
        table.add_column("ID")
        table.add_column("Project", no_wrap=True)
        table.add_column("Date", no_wrap=True)
        table.add_column("Description", no_wrap=True)
        table.add_column(
            "Time", Text.from_markup("[b]Log Total", justify="right"), no_wrap=True, justify="right"
        )
        table.add_column("Duration", no_wrap=True, justify="right")

        time_aggr = IntervalAggregator()
        for model in self.context.models:
            proj_tags = ",".join(model.raw_entry.tags)
            project_name = (
                f"[bold]Unknown:[/b] {proj_tags}" if not model.has_project else model.project.name
            )
            style = "bright_green"
            match model.state:
                case "invalid":
                    style = "red italic"
                case "skipped":
                    style = "bright_black italic"
                case _:
                    time_aggr = time_aggr.add(model.raw_entry.interval)
            table.add_row(
                str(model.raw_entry.id),
                project_name,
                model.raw_entry.interval.day,
                model.raw_entry.truncated_annotation(table_width // 3),
                model.raw_entry.interval.span,
                model.raw_entry.interval.padded_duration,
                style=style,
            )
        table.columns[5].footer = Text.from_markup(
            f"[u bright_green]{time_aggr.duration}", justify="right"
        )

        self.reporter.console.print(
            Align.center(
                Panel(
                    table,
                    padding=(
                        1,
                        3,
                    ),
                )
            )
        )
