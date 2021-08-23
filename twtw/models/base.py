from typing import TYPE_CHECKING, Any, Union

from pydantic import BaseModel
from tinydb import Query
from tinydb.queries import QueryLike
from tinydb.table import Table

if TYPE_CHECKING:
    from pydantic.typing import AbstractSetIntStr, DictStrAny, MappingIntStrAny


class TableModel(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    @property
    def table(self) -> Table:
        from twtw.db import TableState

        return TableState.db.table(self.__class__.__name__)

    @property
    def field_defaults(self) -> dict[str, Any]:
        return {}

    def dict(
        self,
        *,
        include: Union["AbstractSetIntStr", "MappingIntStrAny"] = None,
        exclude: Union["AbstractSetIntStr", "MappingIntStrAny"] = None,
        by_alias: bool = False,
        skip_defaults: bool = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> "DictStrAny":
        params = dict(
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            skip_defaults=skip_defaults,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )
        params.update(self.field_defaults)
        return super().dict(**params)

    def query(self) -> QueryLike:
        return Query().fragment(self.dict(exclude_unset=True))

    def save(self) -> None:
        _data = self.dict()
        self.table.upsert(_data, cond=self.query())

    def load(self) -> "TableModel":
        data = self.table.get(self.query())
        if data:
            loaded = self.copy(update=data, deep=True)
            return loaded
        return self
