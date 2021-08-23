from __future__ import annotations

from typing import Optional

from git import GitConfigParser
from pydantic import HttpUrl, validator
from tinydb import Query
from tinydb.queries import QueryLike

from twtw.models.base import TableModel


class Config(TableModel):
    PROFILE: str = "default"
    TEAMWORK_HOST: Optional[HttpUrl] = None
    API_KEY: Optional[str] = None
    GIT_USER: Optional[str] = None

    def query(self) -> QueryLike:
        return Query().PROFILE == self.PROFILE

    @validator("GIT_USER", pre=True, always=True)
    def get_current_git_user(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v
        git_config = GitConfigParser(read_only=True)
        git_config.read()
        if git_config.has_option("user", "email"):
            return git_config.get("user", "email")


config = Config().load()
