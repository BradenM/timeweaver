from typing import TYPE_CHECKING, Any, Union

from loguru import logger
from pydantic import BaseModel, parse_obj_as
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
        logger.debug("[b]{}[/]: upserting (data={})", self.__class__.__name__, _data)
        self.table.upsert(_data, cond=self.query())

    def load(self) -> "TableModel":
        query = self.query()
        data = self.table.get(query)
        if data:
            logger.debug(
                "[b]{}[/]: loading from table (query={}, data={})",
                self.__class__.__name__,
                query,
                data,
            )
            _loaded = parse_obj_as(self.__class__, data)
            return _loaded
        return self
