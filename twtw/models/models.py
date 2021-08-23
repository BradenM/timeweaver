from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union
from uuid import UUID

import git
from pydantic import BaseModel, Field, validator
from tinydb.queries import Query, QueryLike
from typing_extensions import Literal, TypeAlias

from taskw import TaskWarrior

from .base import TableModel

TWTaskStatus: TypeAlias = Literal["pending", "completed"]


class TWTask(BaseModel):
    id: int
    description: str
    entry: datetime
    modified: datetime
    project: Optional[str]
    status: TWTaskStatus
    tags: list[str]
    uuid: UUID
    urgency: float

    @classmethod
    def iter_active(cls) -> Iterator[TWTask]:
        tw = TaskWarrior(marshal=True)
        _tasks = tw.load_tasks(command="pending")
        yield from (TWTask(**t) for t in _tasks["pending"])


class ProjectRepository(TableModel):
    path: Path
    name: Optional[str]

    @validator("path", pre=True, always=True)
    def validate_path(cls, v: Union[str, Path]) -> Path:
        try:
            git.Repo(v)
        except git.InvalidGitRepositoryError as e:
            raise TypeError(
                "ProjectRepository->path must be a valid git repository: {}".format(v)
            ) from e
        return Path(v)

    @validator("name", pre=True, always=True)
    def validate_name(cls, v: Optional[str], values: dict[str, Any]) -> str:
        if v:
            return v
        _path: Path = values.get("path")
        return _path.name

    @property
    def git_repo(self) -> git.Repo:
        return git.Repo(self.path)


class Project(TableModel):
    name: str
    parent: Optional[Project] = None
    tags: list[str] = Field(default_factory=list)
    repos: list[ProjectRepository] = Field(default_factory=list)
    teamwork_id: Optional[int] = None

    @property
    def field_defaults(self) -> dict[str, Any]:
        return {"exclude": {"parent"}}

    def query(self) -> QueryLike:
        return Query().name == self.name

    @validator("name", always=True)
    def _validate_name(cls, v: str) -> str:
        return v.strip().upper()

    @validator("parent", pre=True, always=True)
    def _validate_parent(cls, v: Optional[Project], values: dict[str, any]) -> Project | None:
        if v:
            return v
        _name: str = values.get("name")
        _name_parts = _name.split(".")
        _name_parts.pop()
        if any(_name_parts):
            parent_name = ".".join(_name_parts)
            parent_obj = Project(name=parent_name).load()
            parent_obj.save()
            return parent_obj
        return None


class LogEntry(TableModel):
    parent: Project
    taskw_uuid: UUID
    teamwork_id: Optional[int]
    repo: ProjectRepository
    commits: List[git.Commit]


Project.update_forward_refs()
