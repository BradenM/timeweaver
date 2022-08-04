from __future__ import annotations

import abc
import enum

# Set up logging; The basic log level will be DEBUG
import logging
from enum import auto, unique
from pathlib import Path
from typing import Callable, Iterator, TypeVar

import attrs
import questionary
from transitions import EventData, Machine

from twtw.api.teamwork import TeamworkApi
from twtw.models.abc import EntriesSource, RawEntry
from twtw.models.csv_file import CSVEntryLoader
from twtw.models.models import LogEntry, Project, TeamworkTimeEntryRequest

logging.basicConfig(level=logging.INFO)
# Set transitions' log level to INFO; DEBUG messages will be omitted
logging.getLogger("transitions").setLevel(logging.INFO)

T = TypeVar("T")


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

    def create_model(self, raw_entry: RawEntry, flags: FlowModifier = None) -> EntryContext:
        model = EntryFlowModel(
            context=self, raw_entry=raw_entry, flags=flags if flags is None else self.flags | flags
        )
        self.models.append(model)
        return self


@attrs.define
class EntryFlowModel:
    context: EntryContext
    raw_entry: RawEntry
    flags: FlowModifier = attrs.field(
        default=FlowModifier.HAS_ENTRIES, on_setattr=_union_model_context_flags
    )
    description: str = attrs.field()
    log_entry: LogEntry = attrs.field(default=None)

    @description.default
    def _description(self):
        return self.raw_entry.annotation

    def create_entry(self, *, project: Project) -> EntryFlowModel:
        entry = LogEntry(
            time_entry=self.raw_entry,
            project=project,
            description=str(self.description or self.raw_entry.annotation),
        )
        self.log_entry = entry
        return self


@attrs.define
class AbstractEntryFlow(abc.ABC):
    machine: Machine = attrs.field()
    context: EntryContext = attrs.field(default=None)

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
        machine = Machine(
            model=inst, states=CreateFlowState, initial=CreateFlowState.INIT, send_event=True
        )
        machine = cls.create_transitions(machine)  # flow = cls(=context, machine=machine)
        # flow.machine.add_model(model=flow, initial=CreateFlowState.INIT)
        return machine


@attrs.define(slots=False)
class AbstractCreateEntryFlow(AbstractEntryFlow):
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
            after="commit_drafts",
        )
        return machine

    @abc.abstractmethod
    def load_context(self, event: EventData) -> None:
        ...

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

    def cancel(self, event: EventData):
        print("exiting!")
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

    def prepare_entries(self, event: EventData):
        targets = self.context.source.unlogged_by_project(
            self.project.resolve_teamwork_project().name
        )
        choices = self.iter_choices(targets)
        results = self.invoke_prompt(choices, "Choose Time Entries")
        if any(results):
            for raw_entry in results:
                self.context.create_model(raw_entry, FlowModifier.ENTRIES_SELECTED)
            self.context.flags |= FlowModifier.ENTRIES_SELECTED

    def create_drafts(self, event: EventData):
        for model in self.context.models:
            model.create_entry(project=self.project)
        print(self.context.models)

    def commit_drafts(self, event: EventData):
        teamw = TeamworkApi()
        for model in self.context.models:
            payload = TeamworkTimeEntryRequest.from_entry(
                entry=model.log_entry, person_id=teamw.person_id
            )
            teamw.create_time_entry(self.project.resolve_teamwork_project().project_id, payload)
