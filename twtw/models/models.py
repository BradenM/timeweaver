from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from itertools import chain
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from uuid import UUID

import git
from mako.template import Template
from pydantic import BaseModel, Field, validator
from rich.table import Table
from taskw import TaskWarrior
from tinydb.queries import Query, QueryLike

from twtw.models.abc import RawEntry
from twtw.models.timewarrior import TimeRange

from .base import TableModel

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult

TWTaskStatus: TypeAlias = Literal["pending", "completed"]

logger = logging.getLogger(__name__)


class TaskWarriorTask(BaseModel):
    id: int
    description: str
    entry: datetime
    modified: datetime
    project: str | None
    status: TWTaskStatus
    tags: list[str]
    uuid: UUID
    urgency: float

    @classmethod
    def iter_active(cls) -> Iterator[TaskWarriorTask]:
        tw = TaskWarrior(marshal=True)
        _tasks = tw.load_tasks(command="pending")
        yield from (TaskWarriorTask(**t) for t in _tasks["pending"] if "logged" not in t["tags"])


class ProjectRepository(TableModel):
    path: Path
    name: str | None

    def __lt__(self, other):
        return self.name < other.name

    @validator("path", pre=True, always=True)
    def validate_path(cls, v: str | Path) -> Path:
        try:
            git.Repo(v)
        except git.InvalidGitRepositoryError as e:
            raise TypeError(f"ProjectRepository->path must be a valid git repository: {v}") from e
        return Path(v)

    @validator("name", pre=True, always=True)
    def validate_name(cls, v: str | None, values: dict[str, Any]) -> str:
        if v:
            return v
        _path: Path = values.get("path")
        return _path.name

    @property
    def git_repo(self) -> git.Repo:
        return git.Repo(self.path)

    @classmethod
    def from_git_repo(cls, git_repo: git.Repo) -> ProjectRepository:
        path = Path(git_repo.working_dir).absolute()
        query = Query().path == path
        if res := cls.table_of().get(query):
            return cls(**res)
        raise ValueError(f"No ProjectRepository found at working dir: {path}")

    def iter_commits_by_author(
        self, author_email: str, *, unlogged_only: bool = True, unlogged_context: int = 5
    ) -> Iterator[CommitEntry]:
        context_consumed = 0
        for commit in self.git_repo.iter_commits(max_count=350):
            if commit.author.email == author_email:
                commit = CommitEntry.parse_commit(commit)
                yield commit
                if commit.logged:
                    if context_consumed >= unlogged_context:
                        break
                    context_consumed += 1

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other: ProjectRepository):
        return getattr(self, "path", None) == getattr(other, "path", None)

    def __str__(self):
        return self.name


class TeamworkProject(TableModel):
    name: str
    project_id: int | None = None

    def __rich_console__(self, *args):
        yield f"[b bright_white]Teamwork:[/b bright_white][bright_white] {self.name}[/][bright_black] ({self.project_id})"


class TeamworkTimeEntry(BaseModel):
    description: str
    person_id: str = Field(..., alias="person-id")
    date: str
    time: str
    hours: str
    minutes: str
    billable: bool = Field(False, alias="isbillable")
    tags: str | None = None

    class Config:
        allow_population_by_field_name = True


class TeamworkTimeEntryRequest(BaseModel):
    time_entry: TeamworkTimeEntry = Field(..., alias="time-entry")

    class Config:
        allow_population_by_field_name = True

    @classmethod
    def from_entry(cls, *, entry: LogEntry, person_id: str):
        # DATE_FORMAT = "%Y%m%d"
        # TIME_FORMAT = "%H:%M"
        start_date = f"{entry.time_entry.start:%Y%m%d}"
        start_time = f"{entry.time_entry.start:%H:%M}"
        tags = ",".join(entry.project.resolve_tags())
        body = TeamworkTimeEntry(
            description=entry.description,
            person_id=str(person_id),
            date=start_date,
            time=start_time,
            hours=str(entry.time_entry.interval.delta.hours),
            minutes=str(entry.time_entry.interval.delta.minutes),
            tags=tags if tags else None,
        )
        return cls(time_entry=body)


class TeamworkTimeEntryResponse(BaseModel):
    time_log_id: int = Field(..., alias="timeLogId")
    status: str = Field(..., alias="STATUS")


class Project(TableModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    repos: list[ProjectRepository] = Field(default_factory=list)
    teamwork_project: TeamworkProject | None = None

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other: Project):
        return getattr(self, "name", None) == getattr(other, "name", None)

    @property
    @lru_cache  # to prevent early parent invocation.  # noqa: B019
    def is_root(self) -> bool:
        return self.parent is None

    @property
    @lru_cache  # to prevent early parent invocation.  # noqa: B019
    def nickname(self):
        if self.is_root:
            return self.name
        return self.name.split(".")[-1]

    @property
    @lru_cache  # noqa: B019
    def parent(self) -> Project | None:
        if "." not in self.name:
            return None
        parent_name = ".".join(self.name.split(".")[:-1])
        parent = Project(name=parent_name).load()
        if not parent.is_loaded:
            logger.debug("parent is not loaded: %r (loaded: %s)", parent, parent.is_loaded)
            parent.save()
        return parent

    def query(self) -> QueryLike:
        return Query().name == self.name

    @validator("name", pre=True, always=True)
    def _validate_name(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def repos_by_name(self) -> dict[str, ProjectRepository]:
        return {r.name: r for r in self.repos}

    def resolve_teamwork_project(self) -> TeamworkProject | None:
        if self.teamwork_project:
            return self.teamwork_project
        if self.parent:
            return self.parent.resolve_teamwork_project()
        return None

    def resolve_tags(self) -> Iterator[str]:
        yield from iter(self.tags)
        if self.parent:
            yield from self.parent.resolve_tags()


class CommitEntry(TableModel):
    commit: git.Commit
    commit_type: str | None
    scope: str | None
    title: str | None
    logged: bool | None = False

    class Config:
        copy_on_model_validation = False

    @property
    def sha(self) -> str:
        return str(self.commit.hexsha)

    def query(self) -> QueryLike:
        return Query().sha == self.sha

    def save(self) -> None:
        _data = self.dict(exclude={"commit"})
        _data.setdefault("sha", self.sha)
        self.table.upsert(_data, cond=self.query())

    def load(self) -> CommitEntry:
        data = self.table.get(self.query())
        if data:
            data.pop("sha", None)
            return CommitEntry(commit=self.commit, **data)
        return self

    @classmethod
    def parse_commit(cls, commit: git.Commit) -> CommitEntry:
        matcher: Pattern = re.compile(
            r"^(?P<commit_type>(\w+))(\((?P<scope>.+)\))?: (?P<title>.+$)"
        )
        default_title = {"title": commit.summary}
        groups = matcher.match(commit.summary)
        if groups:
            groups = groups.groupdict()
        else:
            return None
        default_title.update(groups)
        return cls(commit=commit, **default_title).load()

    @property
    def authored_date(self) -> str:
        return f"{self.commit.authored_datetime:%b %d}"

    @property
    def authored_datetime(self) -> datetime:
        return self.commit.authored_datetime

    @property
    def committed_datetime(self) -> datetime:
        return self.commit.committed_datetime

    def __str__(self):
        _logged = "[LOGGED] " if self.logged else ""
        _dtime = TimeRange.as_day_and_time(self.commit.authored_datetime)
        _dtime_com = TimeRange.as_day_and_time(self.commit.committed_datetime)
        return "{logged}({dt}, com:{dtc}) {c.commit.summary}".format(
            logged=_logged, c=self, dt=_dtime, dtc=_dtime_com
        )


class LogEntry(TableModel):
    time_entry: RawEntry
    project: Project
    taskw_uuid: UUID | None
    teamwork_id: int | None
    commits: dict[ProjectRepository, list[CommitEntry]] = Field(default_factory=dict)
    description: str | None

    @property
    def field_defaults(self) -> dict[str, Any]:
        return {"exclude": {"commits"}}

    def query(self) -> QueryLike:
        return Query().teamwork_id == self.teamwork_id

    @staticmethod
    def group_by_type_scope(commits: list[CommitEntry]) -> dict[str, dict[str, list[CommitEntry]]]:
        _commits = defaultdict(lambda: defaultdict(list))
        for commit in commits:
            _commits[commit.scope][commit.commit_type].append(commit)
        return _commits

    @staticmethod
    def iter_scoped_repo_commits(
        commits: dict[ProjectRepository, list[CommitEntry]],
    ) -> Iterator[tuple[ProjectRepository, dict[str, dict[str, list[CommitEntry]]]]]:
        for repo, commit_entries in commits.items():
            yield repo, LogEntry.group_by_type_scope(commit_entries)

    @staticmethod
    def generate_changelog(
        commits: dict[ProjectRepository, list[CommitEntry]],
        project: Project,
        header: str | None = None,
        lb="\n",
    ):
        repo_commits: dict[ProjectRepository, dict[str, list[CommitEntry]]] = dict(
            LogEntry.iter_scoped_repo_commits(commits)
        )
        tmpl_path = Path(__file__).parent / "entry.mako"
        tmpl = Template(filename=str(tmpl_path))
        return tmpl.render(repo_commits=repo_commits, project=project, header=header)

    def save(self):
        commits = chain.from_iterable([v for k, v in self.commits.items()])
        for commit in commits:
            commit.logged = True
            commit.save()
        super().save()

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield f"[b]Log Entry:[/b] #{self.time_entry.id} [bright_white i]({self.project.name})[/]"
        table = Table("Attribute", "Value")
        intv = self.time_entry.interval
        table.add_row("Date", intv.day)
        table.add_row("Time", intv.span)
        table.add_row("Duration", intv.duration)
        table.add_row("Description", self.description)
        table.add_row(
            "Tags",
            ", ".join(
                list(set(self.time_entry.tags) - {self.project.resolve_teamwork_project().name})
            ),
        )
        if self.teamwork_id:
            tw_proj = self.project.resolve_teamwork_project()
            table.add_row("[bright_green bold]Teamwork Project[/]", tw_proj.name)
            table.add_row("[bright_green bold]Teamwork Log ID[/]", str(self.teamwork_id))
        yield table


Project.update_forward_refs()
