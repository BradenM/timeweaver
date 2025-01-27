import logging
import re
from collections import defaultdict
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING, Any, Literal, Optional, TypeAlias
from uuid import UUID

import git
from mako.template import Template
from pydantic import BaseModel
from pydantic import Field as PyField
from pydantic import validator
from rich.table import Table
from sqlmodel import JSON, Column, Field, Relationship, Session, SQLModel, select
from taskw import TaskWarrior

from twtw.models.abc import RawEntry
from twtw.models.data_types import PathType, SQLGitCommit, SQLRawEntry
from twtw.models.timewarrior import TimeRange
from twtw.utils import get_or_create

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
    def iter_active(cls) -> Iterator["TaskWarriorTask"]:
        tw = TaskWarrior(marshal=True)
        _tasks = tw.load_tasks(command="pending")
        yield from (TaskWarriorTask(**t) for t in _tasks["pending"] if "logged" not in t["tags"])


class TeamworkProject(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    project_id: int | None = Field(default=None, index=True)

    projects: list["Project"] = Relationship(back_populates="teamwork_project")

    def __rich_console__(self, *args):
        yield f"[b bright_white]Teamwork:[/b bright_white][bright_white] {self.name}[/][bright_black] ({self.project_id})"


class TeamworkTimeEntry(BaseModel):
    description: str
    person_id: str = PyField(..., alias="person-id")
    date: str
    time: str
    hours: str
    minutes: str
    billable: bool = PyField(False, alias="isbillable")
    tags: str | None = None

    class Config:
        allow_population_by_field_name = True


class TeamworkTimeEntryRequest(BaseModel):
    time_entry: TeamworkTimeEntry = PyField(..., alias="time-entry")

    class Config:
        allow_population_by_field_name = True

    @classmethod
    def from_entry(cls, *, entry: "LogEntry", person_id: str):
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
    time_log_id: int | None = PyField(None, alias="timeLogId")
    status: str = PyField(..., alias="STATUS")


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    repos: list["ProjectRepository"] = Relationship(back_populates="project")

    teamwork_project_id: int | None = Field(default=None, foreign_key="teamworkproject.id")
    teamwork_project: TeamworkProject | None = Relationship(back_populates="projects")

    log_entries: list["LogEntry"] = Relationship(back_populates="project")

    parent_id: int | None = Field(default=None, foreign_key="project.id")
    parent: Optional["Project"] = Relationship(
        back_populates="children", sa_relationship_kwargs={"remote_side": "Project.id"}
    )

    children: list["Project"] = Relationship(back_populates="parent")

    @classmethod
    def get_by_name(cls, name: str, session: Session) -> Optional["Project"]:
        """Get a project by name."""
        return session.exec(select(Project).where(Project.name == name.upper())).first()

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other: "Project"):
        return getattr(self, "name", None) == getattr(other, "name", None)

    @property
    def is_root(self) -> bool:
        return self.parent is None

    @property
    def nickname(self):
        if self.is_root:
            return self.name
        return self.name.split(".")[-1]

    @property
    def root(self) -> "Project":
        """Get the root project."""
        if self.is_root:
            return self
        return self.parent.root

    def validate_parent(self, session: Session | None = None) -> Optional["Project"]:
        """Validate the project hierarchy."""
        if "." not in self.name:
            # ensure root proects have no parent
            if self.parent or self.parent_id:
                self.parent = None
                self.parent_id = None
                session.add(self)
                session.commit()
                session.refresh(self)
            return None
        # try to find existing parent
        parent_name = ".".join(self.name.split(".")[:-1])
        session = session or Session.object_session(self)
        parent = session.exec(select(Project).where(Project.name == parent_name.upper())).first()
        logger.debug(
            "resolved parent (self=%s, parent=%s, parent_name=%s)",
            self,
            parent,
            parent_name.upper(),
        )
        if parent:
            self.parent_id = parent.id
            # default to parents teamwork project
            if not self.teamwork_project and parent.teamwork_project:
                self.teamwork_project_id = parent.teamwork_project_id
            return parent
        else:
            # create parent if it doesn't exist
            parent = Project(
                name=parent_name.upper(), tags=[], teamwork_project=self.teamwork_project
            )
            session.expunge(self)
            session.add(parent)
            session.commit()
            session.refresh(parent)
            self.parent_id = parent.id
            session.add(self)
            session.commit()
            parent.validate_parent(session)
            return parent

    @validator("name", pre=True, always=True)
    def _validate_name(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def repos_by_name(self) -> dict[str, "ProjectRepository"]:
        return {r.name: r for r in self.repos}

    def resolve_teamwork_project(self) -> TeamworkProject | None:
        """Resolve the teamwork project for this project."""
        if self.teamwork_project:
            return self.teamwork_project
        if self.parent:
            return self.parent.resolve_teamwork_project()
        return None

    def resolve_tags(self) -> Iterator[str]:
        """Resolve tags from project hierarchy."""
        yield from iter(self.tags)
        if self.parent:
            yield from self.parent.resolve_tags()


class ProjectRepository(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    path: Path = Field(sa_column=Column(PathType))
    name: str | None

    project_id: int | None = Field(default=None, foreign_key="project.id")
    project: Optional["Project"] = Relationship(back_populates="repos")

    commits: list["CommitEntry"] = Relationship(back_populates="repo")

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

    def iter_commits_by_author(
        self, author_email: str, *, unlogged_context: int = 50, batch_size: int = 50
    ) -> Iterator["CommitEntry"]:
        context_consumed = 0
        skip_count = 0

        seen_shas = set()

        while True:
            commits = self.git_repo.iter_commits(
                max_count=batch_size, grep=author_email, all=False, skip=skip_count, rev="HEAD"
            )
            fetched_commits = 0

            for raw_commit in commits:
                logger.info("Commit: %s | %s", raw_commit.hexsha, raw_commit.summary)
                # sanity checks
                if raw_commit.hexsha in seen_shas:
                    logger.debug("already seen commit (sha=%s)", raw_commit.hexsha)
                    continue
                if not raw_commit.author.email == author_email:
                    continue
                fetched_commits += 1
                commit = CommitEntry.parse_commit(raw_commit, session=Session.object_session(self))
                yield commit

                # if we run into more already logged commits than unlogged_context, break early
                is_logged = getattr(commit, "logged", False)
                if is_logged:
                    context_consumed += 1
                    if context_consumed >= unlogged_context:
                        return

            # if we didn't fetch any commits, we're done
            if not fetched_commits:
                break

            skip_count += batch_size

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other: "ProjectRepository"):
        return getattr(self, "path", None) == getattr(other, "path", None)

    def __str__(self):
        return self.name


class CommitEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    commit: git.Commit = Field(sa_column=Column(SQLGitCommit))
    commit_type: str | None
    scope: str | None
    title: str | None
    logged: bool | None = False

    log_entry_id: int | None = Field(default=None, foreign_key="logentry.id")
    log_entry: Optional["LogEntry"] = Relationship(back_populates="commit_entries")

    repo_id: int | None = Field(default=None, foreign_key="projectrepository.id")
    repo: Optional["ProjectRepository"] = Relationship(back_populates="commits")

    class Config:
        copy_on_model_validation = False
        arbitrary_types_allowed = True

    @property
    def sha(self) -> str:
        return str(self.commit.hexsha)

    @classmethod
    def parse_commit(
        cls, commit: git.Commit, session: Session | None = None
    ) -> Optional["CommitEntry"]:
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
        from twtw.session_local import SessionLocal

        session_cm = nullcontext(session) if session is not None else SessionLocal()
        with session_cm as session:
            inst, _ = get_or_create(session, cls, commit=commit, **default_title)
            return inst

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


class LogEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    time_entry: RawEntry = Field(sa_column=Column(SQLRawEntry))
    taskw_uuid: UUID | None
    teamwork_id: int | None
    description: str | None

    project_id: int | None = Field(default=None, foreign_key="project.id")
    project: Optional["Project"] = Relationship(back_populates="log_entries")

    commit_entries: list["CommitEntry"] = Relationship(back_populates="log_entry")

    class Config:
        arbitrary_types_allowed = True

    @property
    def commits(self) -> dict[ProjectRepository, list["CommitEntry"]]:
        _commits = defaultdict(list)
        for commit in self.commit_entries:
            if commit.repo:
                _commits[commit.repo].append(commit)
        return _commits

    def add_commits(self, value: dict[ProjectRepository, list["CommitEntry"]]):
        logger.debug("Adding commits: %s", value)
        for repo, commits in value.items():
            for commit in commits:
                commit.repo_id = repo.id
                commit.repo = repo
                if commit not in self.commit_entries:
                    self.commit_entries.append(commit)

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

    def __rich_console__(self, console: "Console", options: "ConsoleOptions") -> "RenderResult":
        table = Table("Attribute", "Value")
        if self.time_entry:
            yield f"[b]Log Entry:[/b] #{self.time_entry.id} [bright_white i]({self.project.name})[/]"
            intv = self.time_entry.interval
            table.add_row("Date", intv.day)
            table.add_row("Time", intv.span)
            table.add_row("Duration", intv.duration)
        table.add_row("Description", self.description)
        if self.time_entry:
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
