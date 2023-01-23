from __future__ import annotations

import itertools
from typing import Iterator, Tuple

import attrs
import typer
from loguru import logger
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from transitions import EventData, Machine

from twtw.models.abc import EntriesSource
from twtw.models.intervals import IntervalAggregator
from twtw.models.models import CommitEntry, Project, ProjectRepository
from twtw.models.timewarrior import TimeWarriorLoader
from twtw.state.entry import BaseCreateEntryFlow, EntryContext, EntryFlowModel, FlowModifier
from twtw.utils import group_by


@attrs.define(slots=False)
class TimeWarriorCreateEntryFlow(BaseCreateEntryFlow):

    git_author: str = attrs.field(default=None)
    proj: Project = attrs.field(default=None)

    chosen_repos: list[ProjectRepository] = attrs.field(init=False, factory=list)

    chosen_commits: dict[ProjectRepository, list[CommitEntry]] = attrs.field(
        init=False, factory=dict
    )

    @property
    def project(self) -> Project:
        return self.proj

    def load_context(self, event: EventData) -> None:
        source = EntriesSource.from_loader(
            TimeWarriorLoader,
            filters=[
                lambda v: self.proj.name.lower() not in v["tags"],
                lambda v: "logged" in v["tags"],
            ],
            project_tags=[self.proj.name],
        )
        self.context: EntryContext = EntryContext(source=source)
        self.entry_machine = Machine(
            model=None,
            states=["init", "invalid", "skipped", "draft", "published", "complete"],
            send_event=True,
            initial="init",
            transitions=[
                {"trigger": "skip", "source": "*", "dest": "skipped"},
                {"trigger": "next", "source": "skipped", "dest": "="},
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
        if any(self.active_repos):
            self.context.flags |= FlowModifier.HAS_REPOS

    @property
    def active_models(self) -> Iterator[EntryFlowModel]:
        for mod in self.entry_machine.models:
            if not mod.is_invalid() and not mod.is_skipped():
                yield mod

    @property
    def active_repos(self) -> Iterator[ProjectRepository]:
        repo_names = set()
        all_repos = itertools.chain.from_iterable([e.project.repos for e in self.active_models])
        for r in all_repos:
            if r.name not in repo_names:
                yield r
            repo_names.add(r.name)

    @property
    def active_commits(self) -> Iterator[Tuple[ProjectRepository, CommitEntry]]:
        for repo in self.chosen_repos:
            for commit in repo.iter_commits_by_author(self.git_author):
                yield repo, commit

    @property
    def active_commits_by_repo(self) -> dict[ProjectRepository, CommitEntry]:
        commits = list(self.active_commits)
        return {k: [c[1] for c in v] for k, v in group_by(commits, lambda i: i[0]).items()}

    def choose_repos(self, event: EventData):
        results: list[ProjectRepository] = self.reporter.prompt.multiselect(
            self.active_repos,
            title="Choose Repositories",
            key=lambda e: str(e),
        )
        if any(results):
            self.context.flags |= FlowModifier.REPOS_SELECTED
            self.context.flags |= FlowModifier.HAS_COMMITS
        self.chosen_repos = results

    def choose_commits(self, event: EventData):
        for repo, commits in self.active_commits_by_repo.items():
            results: list[CommitEntry] = self.reporter.prompt.multiselect(
                commits,
                title="Choose Commits",
                key=lambda e: str(e),
            )
            if results and any(results):
                self.context.flags |= FlowModifier.COMMITS_SELECTED
                self.chosen_commits[repo] = results

    def create_drafts(self, event: EventData):  # noqa
        self.entry_machine.dispatch("next")
        for mod in self.entry_machine.models:
            logger.debug("model (@{}) is ({})", mod.raw_entry.id, mod.state)
        for mod in self.active_models:
            mod.log_entry.commits = self.chosen_commits
            changelog = mod.log_entry.generate_changelog(
                commits=self.chosen_commits, project=self.project, header=str(mod.raw_entry)
            )
            changelog: str | None = typer.edit(text=changelog, require_save=True)
            if changelog is None:
                raise typer.Abort
            lines = changelog.splitlines(keepends=True)
            changelog = "".join(
                itertools.filterfalse(
                    lambda l: l.strip().startswith("//") or not len(l.strip()), lines
                )
            )
            mod.log_entry.description = changelog
            logger.debug("drafted model log entry: {}", mod.log_entry)

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
                getattr(model.log_entry, "description", None)
                or model.raw_entry.truncated_annotation(table_width // 3),
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
