from __future__ import annotations

from typing import Optional

from git import GitConfigParser
from pydantic import HttpUrl, validator
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from tinydb import Query
from tinydb.queries import QueryLike

from twtw.models.base import TableModel


class Config(TableModel):
    PROFILE: str = "default"
    TEAMWORK_HOST: Optional[HttpUrl] = None
    API_KEY: Optional[str] = None
    GIT_USER: Optional[str] = None
    TEAMWORK_UID: Optional[str] = None

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

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield f"[b]{self.__class__.__name__}[/b]"
        dt_table = Table("Field", "Value", expand=True, highlight=True)
        for field, value in self.dict().items():
            dt_table.add_row(field, str(value))
        yield dt_table


config = Config().load()
