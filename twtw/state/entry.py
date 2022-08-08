from __future__ import annotations

import abc
import enum
import inspect
from enum import auto, unique
from functools import partialmethod
from inspect import Parameter
from pathlib import Path
from typing import Callable, Iterator, ParamSpec, TypeVar

import attrs
import questionary
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from transitions import EventData, Machine

from twtw.api import Reporter
from twtw.api.teamwork import TeamworkApi
from twtw.db import TableState
from twtw.models.abc import EntriesSource, RawEntry
from twtw.models.csv_file import CSVEntryLoader
from twtw.models.intervals import IntervalAggregator
from twtw.models.models import (
    LogEntry,
    Project,
    TeamworkTimeEntryRequest,
    TeamworkTimeEntryResponse,
)

T = TypeVar("T")
P = ParamSpec("P")


@unique
class CreateFlowState(enum.Enum):
    INIT = auto()
    ENTRIES = auto()
    REPOS = auto()
    COMMITS = auto()
    DRAFT = auto()
    SAVE = auto()
    CANCEL = auto()


class FlowModifier(enum.Flag):
    ENTRIES_AVAILABLE = auto()
    ENTRIES_SELECTED = auto()
    REPOS_AVAILABLE = auto()
    REPOS_SELECTED = auto()
    COMMITS_AVAILABLE = auto()
    COMMITS_SELECTED = auto()

    DRY_RUN = auto()

    HAS_ENTRIES = ENTRIES_AVAILABLE | ENTRIES_SELECTED
    HAS_REPOS = REPOS_AVAILABLE | REPOS_SELECTED
    HAS_COMMITS = COMMITS_AVAILABLE | COMMITS_SELECTED


def _union_model_context_flags(
    instance: EntryFlowModel, attrib: attrs.Attribute, new_value: FlowModifier
):
    return instance.context.flags | new_value


@attrs.define
class EntryContext:
    source: EntriesSource
    flags: FlowModifier = attrs.field(default=FlowModifier.ENTRIES_AVAILABLE)
    models: list[EntryFlowModel] = attrs.field(factory=list)

    @property
    def projects(self) -> list[Project]:
        entries = TableState.db.table(Project.__name__).all()
        return [Project.parse_obj(e).load() for e in entries]

    def create_model(self, raw_entry: RawEntry, flags: FlowModifier = None) -> EntryFlowModel:
        model = EntryFlowModel(
            context=self, raw_entry=raw_entry, model_flags=self.flags | (flags or self.flags)
        )
        self.models.append(model)
        return model


def _unwrap_event(inst: type, event: EventData, *, f: Callable[P, T]) -> T:
    event_kwargs = event.kwargs
    sig = inspect.signature(f)
    params = sig.parameters.copy()
    params.pop("self")
    if not len(params):
        return f(inst)
    f_kwargs = {
        name: event_kwargs.get(name, None)
        for name, p in params.items()
        if p.kind == Parameter.KEYWORD_ONLY
    }
    return f(inst, **f_kwargs)


@attrs.define(slots=False)
class EntryFlowModel:
    context: EntryContext
    raw_entry: RawEntry
    description: str = attrs.field()
    model_flags: FlowModifier = attrs.field(
        default=FlowModifier.HAS_ENTRIES, on_setattr=_union_model_context_flags
    )
    log_entry: LogEntry = attrs.field(default=None)
    teamw_api: TeamworkApi = attrs.field(factory=TeamworkApi)
    teamw_response: TeamworkTimeEntryResponse = attrs.field(default=None)

    @description.default
    def _description(self):
        return self.raw_entry.description

    @property
    def project(self) -> Project | None:
        return next((p for p in self.context.projects if self.raw_entry.is_project(p) if p), None)

    @property
    def has_project(self) -> bool:
        return self.project is not None

    @property
    def flags(self) -> FlowModifier:
        return self.context.flags | self.model_flags

    @property
    def dry_run(self) -> bool:
        return bool(self.flags & FlowModifier.DRY_RUN)

    def create_entry(self, *args, **kwargs) -> EntryFlowModel:
        entry = LogEntry(
            time_entry=self.raw_entry,
            project=self.project,
            description=str(self.description or self.raw_entry.description),
        )
        self.log_entry = entry
        return self

    def create_payload(self) -> TeamworkTimeEntryRequest:
        payload = TeamworkTimeEntryRequest.from_entry(
            entry=self.log_entry, person_id=self.teamw_api.person_id
        )
        return payload

    def commit_entry(self, *args, **kwargs):
        payload = self.create_payload()
        response = self.teamw_api.create_time_entry(
            self.project.resolve_teamwork_project().project_id, payload
        )
        if not response.status == "OK":
            raise RuntimeError(
                f"Failed to post entry, teamwork responsed with: {response.status} ({response})"
            )
        self.teamw_response = response

    def save_entry(self, *args, **kwargs):
        if self.teamw_response:
            self.log_entry.teamwork_id = self.teamw_response.time_log_id
        self.log_entry.save()

    bound_unwrap = partialmethod(_unwrap_event)
    create_entry_handler = partialmethod(bound_unwrap, f=create_entry)
    commit_entry_handler = partialmethod(bound_unwrap, f=commit_entry)
    save_entry_handler = partialmethod(bound_unwrap, f=save_entry)


@attrs.define
class AbstractEntryFlow(abc.ABC):
    machine: Machine = attrs.field()
    context: EntryContext = attrs.field(default=None)
    reporter: Reporter = attrs.field(factory=Reporter)

    @machine.default
    def _machine(self) -> Machine:
        machine = self.__class__.create_machine(self)
        return machine

    @classmethod
    @abc.abstractmethod
    def create_transitions(cls, machine: Machine) -> Machine:
        ...

    @classmethod
    def create_machine(cls, inst: AbstractEntryFlow) -> Machine:
        machine = Machine(states=CreateFlowState, initial=CreateFlowState.INIT, send_event=True)
        machine = cls.create_transitions(machine)
        machine.add_model(inst)
        return machine


@attrs.define(slots=False)
class AbstractCreateEntryFlow(AbstractEntryFlow):
    entry_machine: Machine = attrs.field(default=None)

    @classmethod
    def create_transitions(cls, machine: Machine) -> Machine:
        machine.add_transition(
            trigger="start",
            source=CreateFlowState.INIT,
            dest=CreateFlowState.ENTRIES,
            prepare="load_context",
            before="prepare_entries",
            after="choose_entries",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.ENTRIES,
            dest=CreateFlowState.CANCEL,
            unless=["has_entries"],
            after="cancel",
        )
        machine.add_transition(
            trigger="cancel", source="*", dest=CreateFlowState.CANCEL, after="do_cancel"
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.ENTRIES,
            dest=CreateFlowState.REPOS,
            after="do_prompt",
            conditions="are_repos_available",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.REPOS,
            dest=CreateFlowState.COMMITS,
            after="do_prompt",
            conditions=["has_chosen_repos", "are_commits_available"],
        )
        machine.add_transition(
            trigger="choose",
            source=[CreateFlowState.ENTRIES, CreateFlowState.REPOS, CreateFlowState.COMMITS],
            dest=CreateFlowState.DRAFT,
            before="create_drafts",
            after="review_drafts",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.DRAFT,
            dest=CreateFlowState.SAVE,
            before="confirm_drafts",
            after="commit_drafts",
        )
        return machine

    @abc.abstractmethod
    def load_context(self, event: EventData) -> None:
        ...

    @property
    def dry_run(self) -> bool:
        return bool(self.context.flags & FlowModifier.DRY_RUN)

    @dry_run.setter
    def dry_run(self, value: bool):
        if value:
            self.context.flags |= FlowModifier.DRY_RUN
            return
        self.context.flags |= ~FlowModifier.DRY_RUN

    @property
    def has_entries(self) -> bool:
        return bool(self.context.flags & FlowModifier.HAS_ENTRIES)

    @property
    def has_repos(self) -> bool:
        return bool(self.context.flags & FlowModifier.HAS_REPOS)

    @property
    def has_commits(self) -> bool:
        return bool(self.context.flags & FlowModifier.HAS_COMMITS)

    @property
    def are_repos_available(self) -> bool:
        return bool(self.context.flags & FlowModifier.REPOS_AVAILABLE)

    @property
    def are_commits_available(self) -> bool:
        return bool(self.context.flags & FlowModifier.COMMITS_AVAILABLE)

    def do_cancel(self, event: EventData):
        err_msg = "Cancelled!" if not event.args else ", ".join(event.args)
        self.reporter.console.print(f"[bold bright_red]{err_msg}")

    def iter_choices(
        self, objs: list[T], key: Callable[[T], str] = None
    ) -> Iterator[questionary.Choice]:
        get_key = key or str
        for e in objs:
            yield questionary.Choice(title=get_key(e), value=e)

    def invoke_prompt(self, choices: Iterator[questionary.Choice], *args):
        results = questionary.checkbox(*args, choices=choices).ask()
        return results

    def do_prompt(self, event: EventData):
        choices = event.kwargs.get("choices")
        title = event.kwargs.get("title")
        results = self.invoke_prompt(choices, title)
        event.kwargs |= {"results": results}
        return event


@attrs.define(slots=False)
class CSVCreateEntryFlow(AbstractCreateEntryFlow):
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

    def prepare_entries(self, event: EventData):  # noqa
        targets = self.context.source.unlogged_entries
        for raw_entry in targets:
            model = self.context.create_model(raw_entry=raw_entry)
            self.entry_machine.add_model(model)
        self.entry_machine.dispatch("validate")

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
        self.entry_machine.dispatch("next")

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

    def confirm_drafts(self, event: EventData):
        if self.dry_run:
            return
        if not self.reporter.prompt.confirm("Commit valid entries?"):
            self.cancel("Canceled by user.")

    def commit_drafts(self, event: EventData):  # noqa
        self.entry_machine.dispatch("next")
        if self.dry_run:
            self.reporter.console.print(
                "[bright_black][bold](DRY RUN)[/bold] Pass [bright_white bold]--commit[/bright_white bold] to submit logs."
            )
            return
        self.reporter.console.print(":stopwatch:  [bold bright_white]Committing Entries...")
        self.entry_machine.dispatch("next")
