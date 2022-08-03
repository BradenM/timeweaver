from __future__ import annotations
import time
from collections import ChainMap
from datetime import timedelta, datetime
from typing import Callable, Iterator, Optional, TypeVar, List
from enum import Enum

import attr
import httpx
import questionary
import typer
from pydantic import BaseModel
import itertools
from rich import print
from rich.pretty import pprint, Pretty
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Group, group, RichCast
from tinydb import Query

from twtw.db import TableState
from twtw.models.config import config
from twtw.models.models import (
    CommitEntry,
    LogEntry,
    Project,
    ProjectRepository,
    TeamworkTimeEntryRequest,
    TeamworkTimeEntryResponse,
)
from twtw.models.timewarrior import TimeRange, TimeWarriorEntry

ModelT = TypeVar("ModelT", bound=BaseModel)
T = TypeVar("T")


class CommitMode(str, Enum):
    replicate = "replicate"
    distribute = "distribute"


@attr.s(auto_attribs=True, collect_by_mro=True, kw_only=True)
class QRichPrompt:
    question: "questionary.Question"

    def __rich__(self):
        self.question.ask()


@attr.s(auto_attribs=True, collect_by_mro=True, kw_only=True)
class EntryBuilder:
    """
    - Load project
    - Resolve related time entries
    - Select from resolved entries.
    - Select repos to log from.
    - Select commits from repos.
    - Create entry log.
    """

    project: Project
    entries: list[TimeWarriorEntry] = attr.ib()
    repos: list[ProjectRepository] = attr.ib()
    repo_commits: ChainMap[ProjectRepository, list[CommitEntry]] = attr.ib(factory=ChainMap)
    log_entries: list[LogEntry] = attr.ib(factory=list)
    description: Optional[str] = attr.ib(None)

    dry_run: bool = attr.ib(default=False)
    mode: CommitMode = attr.ib(default=CommitMode.replicate)

    # layout: Layout = attr.ib(init=False, factory=lambda: Layout.split_row(Layout(name="left", ratio=2), Layout(name="right")))

    def _copy(self, **kwargs) -> "EntryBuilder":
        _attrs = {
            "project": self.project,
            "entries": self.entries,
            "repos": self.repos,
            "repo_commits": self.repo_commits,
            "log_entries": self.log_entries,
            "description": self.description,
            "dry_run": self.dry_run
            # "layout": self.layout
        }
        _attrs.update(kwargs)
        return EntryBuilder(**_attrs)

    @entries.default
    def resolve_entries(self) -> list[TimeWarriorEntry]:
        return list(reversed(list(TimeWarriorEntry.unlogged_by_project(self.project.name))))

    @repos.default
    def resolve_repos(self) -> list[ProjectRepository]:
        return self.project.repos

    def iter_choices(
            self, objs: list[T], key: Optional[Callable[[T], str]] = None
    ) -> Iterator[questionary.Choice]:
        get_key = key or str
        for e in objs:
            yield questionary.Choice(title=get_key(e), value=e)

    def choose_entries(self) -> "EntryBuilder":
        choices = list(self.iter_choices(self.entries))
        _entries = questionary.checkbox(f"Choose Time Entries", choices=choices).ask()
        if _entries is None:
            raise typer.Abort
        return self._copy(entries=_entries)

    def choose_repos(self) -> "EntryBuilder":
        if not any(self.repos):
            return self
        choices = list(self.iter_choices(self.repos))
        _repos = questionary.checkbox(f"Choose Repos", choices=choices).ask()
        if _repos is None:
            raise typer.Abort
        return self._copy(repos=_repos)

    def _create_commits_prompt(self, project_repo: ProjectRepository) -> "questionary.checkbox":
        repo = project_repo.git_repo
        commits = [
            CommitEntry.parse_commit(c)
            for c in repo.iter_commits(max_count=350)
            if c.author.email == config.GIT_USER
        ]

        def is_within_range(timestamp: datetime, delta_buffers: list[timedelta]) -> bool:
            for entry in self.entries:
                for delta in delta_buffers:
                    if entry.interval.contains_datetime(timestamp, buffer=delta):
                        return True
            return False


        def get_likely_commits(c: CommitEntry):
            if c is None:
                print(c)
                return str(c)
            auth_xs = is_within_range(c.commit.authored_datetime,
                                      [timedelta(hours=3), timedelta(hours=-3)])

            com_xs = is_within_range(c.commit.committed_datetime,
                                      [timedelta(hours=3), timedelta(hours=-3)])
            if auth_xs:
                print("got auth xs:", auth_xs)
                return f"**{str(c)}"
            if com_xs:
                print("got comm xs:", com_xs)
                return f"**c{str(c)}"
            return str(c)

        if any(commits):
            choices = list(self.iter_choices(commits, key=get_likely_commits))
            prompt = questionary.checkbox(
                f"Choose commits from {project_repo.name}", choices=choices
            )
            return prompt

    def _distribute_commit_entries(self, project_repo: ProjectRepository):
        repo = project_repo.git_repo
        commits = [
            CommitEntry.parse_commit(c)
            for c in repo.iter_commits(max_count=350)
            if c.author.email == config.GIT_USER
        ]
        entry_commits = dict()
        commits = [c for c in commits if c is not None and not c.logged]
        commits = list(reversed(sorted(commits, key=lambda c: c.authored_datetime)))
        total_seconds = sum(e.interval.timedelta.total_seconds() for e in self.entries)
        total_commits = len(commits)
        commits_per_second = total_commits / total_seconds

        lines = [
            f"Total Commits: {total_commits}",
            f"Total Seconds: {total_seconds}",
            f"Commits/Second: {commits_per_second}",
        ]
        print('\n'.join(lines))

        commits_iter = iter(commits)
        total_used = 0
        for entry in self.entries:
            share = (entry.interval.timedelta.total_seconds()/total_seconds)
            commit_share = round(share*total_commits)
            commit_share = commit_share if commit_share > 0 else 1
            commits = list(itertools.islice(commits_iter, commit_share))
            total_used += len(commits)
            print(f"{str(entry)} - Commit Share: {share} - Num Commits: {len(commits)}")
            entry_commits[entry] = commits

        print(f"Distributed {total_used} of {total_commits} commits.")

        for missed_commit in commits_iter:
            nearest_entry = next((i for i in self.entries if i.interval.contains_datetime(missed_commit.authored_datetime)), self.entries[0])
            print(f"Allocating missed commit ({missed_commit}) to entry: ({nearest_entry})")
            entry_commits[nearest_entry].append(missed_commit)

        # print(entry_commits)
        return entry_commits


    def distribute_commits(self) -> iter["EntryBuilder"]:
        if not any(self.repos):
            return [self]
        entry_commits = dict()
        for r in self.repos:
            repo_distr = self._distribute_commit_entries(r)
            entry_commits[r.name] = repo_distr

        # print(entry_commits)
        for repo, entry_commits in entry_commits.items():
            for entry, commits in entry_commits.items():
                print(f"\nEntry {str(entry)} -> {len(commits)} commits:")
                rep_commits = [f"   {str(c)}" for c in commits]
                print('\n'.join(rep_commits))
                repo_commits = ChainMap(*[{self.project.repos_by_name[repo]: commits}])
                yield self._copy(entries=[entry], repo_commits=repo_commits)

    def choose_commits(self) -> "EntryBuilder":
        if not any(self.repos):
            return self
        prompts = {}
        for r in self.repos:
            if _prompt := self._create_commits_prompt(r):
                prompts[r.name] = _prompt
        if not any(prompts):
            print("No commits to choose from!")
            return self
        answers = questionary.form(**prompts).ask()
        if answers is None:
            typer.confirm("Do not use any commits?", abort=True)
            print("No commits to chosen!")
            return self
        print(answers)
        repo_commits = ChainMap(*[{self.project.repos_by_name[k]: v for k, v in answers.items()}])
        print(repo_commits.maps)
        return self._copy(repo_commits=repo_commits)

    def create_description(self) -> "EntryBuilder":
        _header = None
        _header_pts = set()
        for e in self.entries:
            _header_pts.add(str(e))
        print("header pts:", _header_pts)
        if any(_header_pts):
            _header = "\n".join(list(_header_pts))
        changelog = LogEntry.generate_changelog(
            commits=dict(self.repo_commits), project=self.project, header=_header
        )
        description = typer.edit(text=changelog, require_save=True)
        if description is None:
            raise typer.Abort
        print(description)
        return self._copy(description=description)

    def _create_entry(self, time_entry: TimeWarriorEntry) -> LogEntry:
        print(dict(self.repo_commits))
        entry = LogEntry(
            time_entry=time_entry,
            project=self.project,
            commits=dict(self.repo_commits),
            description=self.description,
        )
        # if not self.description:
        #     base_log = entry.generate_changelog()
        #     self.description = typer.edit(text=base_log, require_save=True)
        #     print(self.description)
        # entry.description = self.description
        return entry

    def create_all(self) -> "EntryBuilder":
        log_entries = [self._create_entry(e) for e in self.entries]
        return self._copy(log_entries=log_entries)

    def _commit_entry(self, entry: LogEntry) -> "EntryBuilder":
        assert config.TEAMWORK_HOST
        assert config.TEAMWORK_UID
        assert config.API_KEY
        tw_project = self.project.resolve_teamwork_project()
        tw_request = TeamworkTimeEntryRequest.from_entry(entry=entry, person_id=config.TEAMWORK_UID)
        print()
        # print(tw_request)
        payload = tw_request.json(by_alias=True)
        print("Request data:")
        print(payload)
        print("Target TW Project:", tw_project)
        endpoint = "{base_url}/projects/{project_id}/time_entries.json".format(
            base_url=config.TEAMWORK_HOST, project_id=tw_project.project_id
        )
        print("Target URL:", endpoint)
        headers = {"Authorization": f"Basic {config.API_KEY}", "Content-Type": "application/json"}
        print("Headers:", headers)
        if self.dry_run:
            print("[b bright_black]DRY RUN: Skipping save due to dry run flag.")
            type.confirm("Pausing due to dry run, continue?", abort=True)
            return self
        # typer.confirm("Commit entry?", abort=True)
        response = httpx.post(endpoint, headers=headers, content=payload)
        response.raise_for_status()
        response_data = TeamworkTimeEntryResponse.parse_obj(response.json())
        print(response_data)
        if response_data and response_data.status == "OK":
            entry.teamwork_id = response_data.time_log_id
            entry.save()
            twtw_tag = f"twtw:id:{response_data.time_log_id}"
            entry.time_entry.add_tags("logged", twtw_tag)
        return self

    def commit_all(self):
        for log_entry in self.log_entries:
            self._commit_entry(log_entry)
            time.sleep(0.1)

    @group()
    def iter_entry_panels(self):
        for e in self.log_entries:
            yield Panel(Pretty(e), title=f"@{e.time_entry.id} ({e.taskw_uuid})")


app = typer.Typer()


@app.command(name="create")
def do_create(name: str, dry_run: bool = False, mode: CommitMode = CommitMode.replicate):
    proj = Project(name=name).load()
    layout = Layout()
    layout.split_row(Layout(name="left", ratio=2), Layout(name="right"))

    builds_to_commit = []

    build = EntryBuilder(project=proj, dry_run=dry_run)
    build_root = build.choose_entries().choose_repos()
    if mode == CommitMode.replicate:
        build = build_root.choose_commits().create_description().create_all()
        builds_to_commit.append(build)
    elif mode == CommitMode.distribute:
        builds = list(build_root.distribute_commits())
        for b in builds:
            b = b.create_description().create_all()
            builds_to_commit.append(b)
    else:
        raise typer.Abort()

    # build = build.choose_entries().choose_repos().choose_commits().create_description().create_all()

    for b in builds_to_commit:
        print(Panel(b.iter_entry_panels()))


    do_commit = typer.confirm("Commit all entries?", default=False)

    for b in builds_to_commit:
        if do_commit is True:
            b.commit_all()

    # repo_commits: dict[ProjectRepository, dict[str, list[CommitEntry]]] = {k: v for k, v in
    #                                                                        build.iter_scoped_repo_commits()}
    # print(repo_commits)

    # time_entries = [
    #     questionary.Choice(title=f"@{e.id}: {' '.join(e.tags)} - {e.annotation}", value=e)
    #     for e in TimeWarriorEntry.unlogged_entries()
    # ]
    # time_answers = questionary.checkbox(f"Choose Time Entries", choices=time_entries).ask()
    # print(time_answers)
    #
    # prompts = {}
    # for proj_repo in proj.repos:
    #     repo = proj_repo.git_repo
    #     commits = repo.iter_commits(max_count=20)
    #     choices = [questionary.Choice(title=c.summary, value=c) for c in commits]
    #     prompts[proj_repo.name] = questionary.checkbox(
    #         f"Choose commits from {proj_repo.name}", choices=choices
    #     )
    # answers = questionary.form(**prompts).ask()
    # for repo_name, commits in answers.items():
    #     proj_repo = next((i for i in proj.repos if i.name == repo_name))


@app.command(name="pending")
def do_pending(project_name: str = None):
    if project_name:
        proj = Project(name=project_name).load()
        entries = list(reversed(list(TimeWarriorEntry.unlogged_by_project(proj.name))))
        for i in entries:
            print(i)
        return
    tbl = TableState.db.table(Project.__name__).all()
    _projects = [Project(name=item["name"]).load() for item in tbl]
    # root_projects: set[Project] = {p for p in _projects if p.is_root}
    _pending: List["TimeWarriorEntry"] = []
    for proj in _projects:
        _proj_entries = list(TimeWarriorEntry.unlogged_by_project(proj.name))
        _pending += _proj_entries
    _pending = list(reversed(sorted(_pending, key=lambda e: e.start)))
    for i in _pending:
        print(i)


@app.command(name="list")
def do_list(project_name: str = None, synced: bool = None):
    bquery = Query().teamwork_id.exists()
    if synced is False:
        bquery = ~bquery
    if synced is None:
        bquery = Query().noop()
    if project_name:
        bquery &= Query().project.name == Project(name=project_name).load().name

    tbl = TableState.db.table(LogEntry.__name__)
    items = tbl.search(bquery)
    print(items)
