from typing import TYPE_CHECKING, Any, ClassVar, Union, cast

from loguru import logger
from pydantic import BaseModel, PrivateAttr, parse_obj_as
from tinydb import Query
from tinydb.queries import QueryLike
from tinydb.table import Table

if TYPE_CHECKING:
    from pydantic.typing import AbstractSetIntStr, DictStrAny, MappingIntStrAny


class TableModel(BaseModel, arbitrary_types_allowed=True):
    __table: ClassVar[Table]
    _loaded: bool = PrivateAttr(False)

    @property
    def is_loaded(self) -> bool:
        """Indicates model was loaded from table."""
        return self._loaded

    @property
    def table(self) -> Table:
        return self.__class__.table_of()

    @classmethod
    def table_of(cls) -> Table:
        if not hasattr(cls, "__table"):
            from twtw.db import TableState

            cls.__table = TableState.db.table(cls.__name__)
        return cast(Table, cls.__table)

    @property
    def field_defaults(self) -> dict[str, Any]:
        return {}

    def dict(
        self,
        *,
        include: Union["AbstractSetIntStr", "MappingIntStrAny"] | None = None,
        exclude: Union["AbstractSetIntStr", "MappingIntStrAny"] | None = None,
        by_alias: bool = False,
        skip_defaults: bool | None = None,
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
        """Query fragment for model."""
        return Query().fragment(self.dict(exclude_unset=True))

    def save(self) -> None:
        """Upsert model to table."""
        _data = self.dict()
        logger.debug("[b]{}[/]: upserting (data={})", self.__class__.__name__, _data)
        self.table.upsert(_data, cond=self.query())
        self._loaded = True

    def load(self) -> "TableModel":
        """Load model from table."""
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
            _loaded._loaded = True
            return _loaded
        return self
