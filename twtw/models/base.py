from pathlib import Path
from typing import Any, Callable, Optional

from click import get_app_dir
from pydantic import BaseModel, Field, validator
from tinydb import Query, TinyDB
from tinydb.table import Table

from twtw.db import create_db_storage


class TableModel(BaseModel):
    db_path: Path = Field(default_factory=lambda: (Path(get_app_dir("twtw")) / "db.json"))
    db: Optional[TinyDB]
    table_name: Optional[str]
    table: Optional[Table]

    class Config:
        arbitrary_types_allowed = True
        validate_all = True

    @validator("table_name", pre=True)
    def validate_table_name(cls, v: Optional[str], values: dict[str, Any]):
        if not v:
            return cls.__name__
        return v

    @validator("db", pre=True)
    def validate_db(cls, v: Optional[TinyDB], values: dict[str, Any]) -> TinyDB:
        if not v:
            db_path = values.get("db_path")
            db_path.parent.mkdir(exist_ok=True)
            storage = create_db_storage()
            return TinyDB(
                str(db_path),
                storage=storage,
                sort_keys=True,
                indent=4,
                separators=(",", ": "),
            )
        return v

    @validator("table", pre=True)
    def validate_table(cls, v: Optional[Table], values: dict[str, Any]) -> Table:
        if not v:
            db: TinyDB = values.get("db")
            table_name = values.get("table_name")
            return db.table(table_name)
        return v

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [
            dict(key=k, value=v)
            for k, v in self.dict(exclude={"db", "table_name", "db_path", "table"}).items()
        ]

    def save(self):
        for row in self.rows:
            self.table.upsert(row, Query().key == row["key"])


def get_existing_value(key: str, default_factory: Optional[Callable[..., Any]] = None) -> Any:
    def _validate(cls, v: Any, values: dict[str, Any]) -> Any:
        if v:
            return v
        table: Table = values.get("table")
        if stored := table.get(Query().key == key):
            return stored
        if default_factory:
            if callable(default_factory):
                return default_factory()
            if isinstance(default_factory, (classmethod, staticmethod)):
                return default_factory.__get__(cls)()

    return validator(key, pre=True, always=True, allow_reuse=True)(_validate)
