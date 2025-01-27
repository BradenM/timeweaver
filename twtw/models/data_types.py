from pathlib import Path

import git
import orjson
from sqlalchemy import JSON, String, TypeDecorator

from twtw.models.abc import RawEntry


class PathType(TypeDecorator):
    """SQLAlchemy type for storing Path objects."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, Path):
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return Path(value)
        return value


class GitCommit(git.Commit):
    """A git commit object that can be used with Pydantic."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value):
        try:
            repo, commit = value.split("@")
            repo = git.Repo(repo)
            return repo.commit(commit)
        except ValueError as e:
            raise ValueError(f"Invalid git commit: {value}") from e

    def json(self):
        return f"{self.value.repo.working_dir!s}@{self.value!s}"

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")

    def __repr__(self):
        return f"{self.__class__.__name__}({super().__repr__()})"


class SQLGitCommit(TypeDecorator):
    """SQLAlchemy type for storing git.Commit objects."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, git.Commit):
            return f"{value.repo.working_dir!s}@{value!s}"
        if isinstance(value, GitCommit):
            return value.json()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return GitCommit.validate(value)
        return value


class SQLRawEntry(TypeDecorator):
    """SQLAlchemy type for storing RawEntry objects."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, dict):
            value.setdefault("_class", "TimeWarriorRawEntry")
            value = RawEntry.validate(value)
        if isinstance(value, RawEntry):
            fields = value.json()
            return orjson.dumps(fields).decode()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            data = orjson.loads(value.encode())
            return RawEntry.validate(data)
        return value
