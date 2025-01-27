from __future__ import annotations

import abc
import enum
import inspect
from collections.abc import Callable, Iterator
from enum import auto, unique
from functools import partialmethod
from inspect import Parameter
from typing import ClassVar, ParamSpec, Protocol, TypeVar

import attrs
import questionary
from sqlmodel import Session, select
from transitions import EventData, Machine

from twtw.api import Reporter
from twtw.api.teamwork import TeamworkApi
from twtw.data import DataAccess
from twtw.models.abc import EntriesSource, RawEntry
from twtw.models.models import LogEntry, Project, TeamworkTimeEntryResponse

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

    DISTRIBUTE_COMMITS = auto()
    DRY_RUN = auto()
    DRAFT_LOGS = auto()

    HAS_ENTRIES = ENTRIES_AVAILABLE | ENTRIES_SELECTED
    HAS_REPOS = REPOS_AVAILABLE | REPOS_SELECTED
    HAS_COMMITS = COMMITS_AVAILABLE | COMMITS_SELECTED


def _union_model_context_flags(
    instance: EntryFlowModel, attrib: attrs.Attribute, new_value: FlowModifier
):
    return instance.context.flags | new_value


@attrs.define(slots=False)
class EntryContext:
    source: EntriesSource
    db: DataAccess
    flags: FlowModifier = attrs.field(default=FlowModifier.ENTRIES_AVAILABLE)
    models: list[EntryFlowModel] = attrs.field(factory=list)
    projects: list[Project] = attrs.field(factory=list)

    def create_model(
        self, raw_entry: RawEntry, flags: FlowModifier | None = None
    ) -> EntryFlowModel:
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

    @property
    def draft_logs(self) -> bool:
        return bool(self.flags & FlowModifier.DRAFT_LOGS)

    def create_entry(self, *args, **kwargs) -> EntryFlowModel:
        twtw_id_tag = next(
            (
                int(t.split("twtw:id:drafted:")[-1])
                for t in self.raw_entry.tags
                if t.startswith("twtw:id:drafted")
            ),
            None,
        )
        if twtw_id_tag:
            print("Loading entry from tw id:", twtw_id_tag)
            session = Session.object_session(self.project)
            entry = session.execute(
                select(LogEntry).where(LogEntry.teamwork_id == twtw_id_tag)
            ).scalar()
            print("Found entry from tw id:", entry, twtw_id_tag)
        else:
            entry = LogEntry(
                time_entry=self.raw_entry,
                project=self.project,
                description=str(self.description or self.raw_entry.description),
            )
            entry.time_entry = self.raw_entry
        self.log_entry = entry
        return self

    # def create_payload(self) -> TeamworkTimeEntryRequest:
    #     payload = TeamworkTimeEntryRequest.from_entry(
    #         entry=self.log_entry, person_id=self.teamw_api.person_id
    #     )
    #     return payload

    def commit_entry(self, *args, **kwargs):
        # payload = self.create_payload()
        tw_project = self.project.resolve_teamwork_project()
        if not tw_project:
            raise RuntimeError(f"Missing teamwork project for project: {self.project.name}")
        if self.log_entry.teamwork_id:
            response = self.teamw_api.update_time_entry(
                log_entry=self.log_entry,
            )
        else:
            response = self.teamw_api.create_time_entry(
                log_entry=self.log_entry, project_id=tw_project.project_id
            )
        self.teamw_response = response

    def save_entry(self, *args, **kwargs):
        was_drafted = "drafted" in self.log_entry.time_entry.tags
        log_state = "drafted" if self.draft_logs and not was_drafted else "logged"
        if self.teamw_response:
            self.log_entry.teamwork_id = self.teamw_response.time_log_id
            self.log_entry.time_entry = self.log_entry.time_entry.add_tags(
                f"twtw:id:{log_state}:{self.teamw_response.time_log_id}"
            )
        print("setting tag:", self.log_entry.time_entry, log_state)
        print(self.log_entry)
        self.log_entry.time_entry = self.log_entry.time_entry.add_tags(log_state)
        for entry in self.log_entry.commit_entries:
            entry.logged = True
        self.context.db.add(self.log_entry)
        self.context.db.commit()

    bound_unwrap = partialmethod(_unwrap_event)
    create_entry_handler = partialmethod(bound_unwrap, f=create_entry)
    commit_entry_handler = partialmethod(bound_unwrap, f=commit_entry)
    save_entry_handler = partialmethod(bound_unwrap, f=save_entry)


class EntryFlowProtocol(Protocol):
    start: Callable[[], None]
    choose: Callable[[], None]


@attrs.define
class AbstractEntryFlow(abc.ABC, EntryFlowProtocol):
    FlowModifier: ClassVar[FlowModifier] = FlowModifier

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

    @abc.abstractmethod
    def prepare_entries(self, event: EventData) -> None:
        ...

    @abc.abstractmethod
    def create_drafts(self, event: EventData) -> None:
        ...

    @abc.abstractmethod
    def review_drafts(self, event: EventData) -> None:
        ...

    @abc.abstractmethod
    def confirm_drafts(self, event: EventData) -> None:
        ...

    @abc.abstractmethod
    def commit_drafts(self, event: EventData) -> None:
        ...

    @classmethod
    def create_machine(cls, inst: AbstractEntryFlow) -> Machine:
        machine = Machine(states=CreateFlowState, initial=CreateFlowState.INIT, send_event=True)
        machine = cls.create_transitions(machine)
        machine.add_model(inst)
        return machine


@attrs.define(slots=False)
class BaseCreateEntryFlow(AbstractEntryFlow):
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
        # choose -> (no entries) -> cancel
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
            after="choose_repos",
            conditions="are_repos_available",
            unless="draft_logs",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.REPOS,
            dest=CreateFlowState.COMMITS,
            conditions=["are_commits_available"],
            before="choose_commits",
            unless="draft_logs",
        )
        # draft -> cancel (dry run)
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.DRAFT,
            dest=CreateFlowState.CANCEL,
            conditions=["dry_run"],
        )
        machine.add_transition(
            trigger="choose",
            source=[CreateFlowState.ENTRIES, CreateFlowState.REPOS, CreateFlowState.COMMITS],
            dest=CreateFlowState.DRAFT,
            prepare="proceed_entries",
            before="create_drafts",
            after="review_drafts",
        )
        machine.add_transition(
            trigger="choose",
            source=CreateFlowState.DRAFT,
            dest=CreateFlowState.SAVE,
            conditions=["confirm_drafts"],
            unless=["dry_run"],
            prepare="commit_drafts",
            before="proceed_entries",
            after="proceed_entries",
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
    def draft_logs(self) -> bool:
        return bool(self.context.flags & FlowModifier.DRAFT_LOGS)

    @draft_logs.setter
    def draft_logs(self, value: bool):
        if value:
            self.context.flags |= FlowModifier.DRAFT_LOGS
            return
        self.context.flags |= ~FlowModifier.DRAFT_LOGS

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

    @property
    def should_distribute(self) -> bool:
        return bool(self.context.flags & self.FlowModifier.DISTRIBUTE_COMMITS)

    @should_distribute.setter
    def should_distribute(self, value: bool):
        self.context.flags &= ~self.FlowModifier.DISTRIBUTE_COMMITS
        if value:
            self.context.flags |= self.FlowModifier.DISTRIBUTE_COMMITS

    def do_cancel(self, event: EventData):
        err_msg = "Cancelled!" if not event.args else ", ".join(event.args)
        self.reporter.console.print(f"[bold bright_red]{err_msg}")

    def iter_choices(
        self, objs: list[T], key: Callable[[T], str] | None = None
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

    def prepare_entries(self, event: EventData):
        targets = self.context.source.unlogged_entries
        for raw_entry in targets:
            model = self.context.create_model(raw_entry=raw_entry)
            self.entry_machine.add_model(model)
        self.entry_machine.dispatch("validate")

    def proceed_entries(self, event: EventData):
        self.entry_machine.dispatch("next")

    def distribute_commits(self, event: EventData):
        pass

    def confirm_drafts(self, event: EventData):
        if self.dry_run:
            self.reporter.console.print(
                "[bright_black][bold](DRY RUN)[/bold] Pass [bright_white bold]--commit[/bright_white bold] to submit logs."
            )
            return False
        action = "Draft" if self.draft_logs else "Commit"
        if not self.reporter.prompt.confirm(f"{action} valid entries?"):
            self.cancel("Canceled by user.")
            return False
        return True

    def commit_drafts(self, event: EventData):
        self.reporter.console.print(":stopwatch:  [bold bright_white]Committing Entries...")
