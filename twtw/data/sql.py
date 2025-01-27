from __future__ import annotations

from typing import TypeVar

import attrs
from sqlmodel import Session, SQLModel

from .abc import DataAccess

AnyModel = TypeVar("AnyModel", bound=SQLModel)


@attrs.define
class SQLAlchemyDataAccess(DataAccess):
    session: Session

    def add(self, value: AnyModel) -> None:
        self.session.add(value)

    def commit(self):
        self.session.commit()
