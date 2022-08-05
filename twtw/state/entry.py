from __future__ import annotations

import abc
import enum
import inspect
import sys
from enum import auto, unique
from functools import partialmethod
from inspect import Parameter
from pathlib import Path
from typing import Callable, Iterator, ParamSpec, TypeVar

import attrs
import questionary
from rich.columns import Columns
from rich.panel import Panel
from transitions import EventData, Machine

from twtw.api import Reporter
from twtw.api.teamwork import TeamworkApi
from twtw.models.abc import EntriesSource, RawEntry
from twtw.models.csv_file import CSVEntryLoader
from twtw.models.models import (
    LogEntry,
    Project,
    TeamworkProject,
    TeamworkTimeEntryRequest,
    TeamworkTimeEntryResponse,
)

T = TypeVar("T")
P = ParamSpec("T")


@unique
class CreateFlowState(enum.Enum):
    INIT = auto()
    PROJECT = auto()
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

    def create_model(self, raw_entry: RawEntry, flags: FlowModifier = None) -> EntryFlowModel:
        model = EntryFlowModel(
            context=self, raw_entry=raw_entry, model_flags=self.flags | (flags or self.flags)
        )
        self.models.append(model)
        return model


def unwrap_event(inst: type, event: EventData, *, f: Callable[P, T]) -> T:
    event_kwargs: P.kwargs = event.kwargs
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
    model_flags: FlowModifier = attrs.field(
        default=FlowModifier.HAS_ENTRIES, on_setattr=_union_model_context_flags
    )
    description: str = attrs.field()
    log_entry: LogEntry = attrs.field(default=None)
    teamw_api: TeamworkApi = attrs.field(factory=TeamworkApi)
    teamw_response: TeamworkTimeEntryResponse = attrs.field(default=None)

    @description.default
    def _description(self):
        return self.raw_entry.description

    @property
    def flags(self) -> FlowModifier:
        return self.context.flags | self.model_flags

    @property
    def dry_run(self) -> bool:
        return bool(self.flags & FlowModifier.DRY_RUN)

    def create_entry(self, *, project: Project) -> EntryFlowModel:
        entry = LogEntry(
            time_entry=self.raw_entry,
            project=project,
            description=str(self.description or self.raw_entry.description),
        )
        self.log_entry = entry
        return self

    def create_payload(self, *, teamwork_project: TeamworkProject) -> TeamworkTimeEntryRequest:
        payload = TeamworkTimeEntryRequest.from_entry(
            entry=self.log_entry, person_id=self.teamw_api.person_id
        )
        return payload

    def commit_entry(self, *, teamwork_project: TeamworkProject):
        payload = self.create_payload(teamwork_project=teamwork_project)
        response = self.teamw_api.create_time_entry(teamwork_project.project_id, payload)
        if not response.status == "OK":
            raise RuntimeError(
                f"Failed to post entry, teamwork responsed with: {response.status} ({response})"
            )
        self.teamw_response = response

    def save_entry(self, *args, **kwargs):
        if self.teamw_response:
            self.log_entry.teamwork_id = self.teamw_response.time_log_id
        self.log_entry.save()

    bound_unwrap = partialmethod(unwrap_event)
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

    # @abc.abstractmethod
    # def after_state_change(self, event: EventData) -> Machine:
    #     ...

    @classmethod
    def create_machine(cls, inst: AbstractEntryFlow) -> Machine:
        machine = Machine(states=CreateFlowState, initial=CreateFlowState.INIT, send_event=True)
        machine = cls.create_transitions(machine)  # flow = cls(=context, machine=machine)
        machine.add_model(inst)
        # flow.machine.add_model(model=flow, initial=CreateFlowState.INIT)
        return machine


@attrs.define(slots=False)
class AbstractCreateEntryFlow(AbstractEntryFlow):
    selected_entries: list[RawEntry] = attrs.field(factory=list)
    entry_machine: Machine = attrs.field(default=None)

    @classmethod
    def create_transitions(cls, machine: Machine) -> Machine:
        machine.add_transition(
            trigger="start",
            source=CreateFlowState.INIT,
            dest=CreateFlowState.PROJECT,
            before="load_context",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.PROJECT,
            dest=CreateFlowState.ENTRIES,
            before="prepare_entries",
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
            after="create_drafts",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.DRAFT,
            dest=CreateFlowState.SAVE,
            before="review_drafts",
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
        print("exiting!")
        print(event)
        raise RuntimeError("something")

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

    def load_context(self, event: EventData) -> None:
        print(event)
        source = EntriesSource.from_loader(CSVEntryLoader, self.path)
        self.context: EntryContext = EntryContext(source=source)
        self.entry_machine = Machine(
            model=None,
            states=["init", "draft", "published", "complete"],
            send_event=True,
            initial="init",
            transitions=[
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

    def prepare_entries(self, event: EventData):
        targets = self.context.source.unlogged_by_project(
            self.project.resolve_teamwork_project().name
        )
        results = self.reporter.prompt.multiselect(targets, title="Choose Time Entries.")
        if not any(results):
            return self.cancel("no entries.")
        self.selected_entries = results
        self.context.flags |= FlowModifier.ENTRIES_SELECTED
        for raw_entry in results:
            model = self.context.create_model(raw_entry=raw_entry)
            self.entry_machine.add_model(model)

    def create_drafts(self, event: EventData):
        self.entry_machine.dispatch(
            "next", project=self.project, teamwork_project=self.project.resolve_teamwork_project()
        )

    def review_drafts(self, event: EventData):
        cols = Columns([Panel(m.log_entry) for m in self.context.models], equal=True, expand=True)
        self.reporter.console.print(cols)

    def commit_drafts(self, event: EventData):
        self.entry_machine.dispatch(
            "next", project=self.project, teamwork_project=self.project.resolve_teamwork_project()
        )
        try:
            self.entry_machine.dispatch(
                "next",
                project=self.project,
                teamwork_project=self.project.resolve_teamwork_project(),
            )
        except Exception:
            # todo: do properly
            if not self.dry_run:
                raise
            self.reporter.console.print(
                "[bright_black][bold](DRY RUN)[/bold] Pass [bright_white bold]--commit[/bright_white bold] to submit logs."
            )
            sys.exit(0)
        else:
            self.reporter.console.rule("[bright_green bold]Submissions:[/]")
            self.review_drafts(event)
