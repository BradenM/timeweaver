from __future__ import annotations

import abc
from typing import Any

import attrs


@attrs.define
class DataAccess(abc.ABC):
    @abc.abstractmethod
    def add(self, value: Any) -> None:
        ...

    @abc.abstractmethod
    def commit(self) -> None:
        ...
