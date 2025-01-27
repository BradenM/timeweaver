from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from typing import Any, Protocol, TypeVar

from sqlmodel import Session, SQLModel, select


class SupportsLessThan(Protocol):
    def __lt__(self, other: Any) -> bool:
        ...


Key = TypeVar("Key", bound=SupportsLessThan)
Value = TypeVar("Value")


def group_by(in_seq: Sequence[Value], key_fn: Callable[[Value], Key]) -> dict[Key, list[Value]]:
    """
    Group elements of a list.

    Args:
        in_seq: The input sequence.
        key_fn: The key function.

    Returns:
        A dict keyed by key_fn with lists of results.

    """
    return {
        key: list(group) for key, group in itertools.groupby(sorted(in_seq, key=key_fn), key=key_fn)
    }


def truncate(content: str, length: int = 20):
    return (
        "{:.<{elip}.{len}}".format(
            content,
            elip=length + 3 if len(content) >= length else len(content),
            len=length,
        )
        if content
        else ""
    )


ModelT = TypeVar("ModelT", bound=SQLModel)


def get_or_create(
    session: Session, model: type[ModelT], defaults: dict[str, Any] | None = None, **kwargs
) -> tuple[ModelT, bool]:
    """
    Retrieve an instance of the given model from the database filtered by the provided keyword
    arguments or create a new instance if it does not already exist.

    Parameters:
        session (Session): The database session used for query execution and creating a database record.
        model (type[ModelT]): The SQLAlchemy model class for the type of instance to retrieve or create.
        defaults (dict[str, Any] | None): Optional dictionary of default values to use for creating
            the instance if one does not already exist.
        **kwargs: Arbitrary keyword arguments to filter the query when checking if the instance
            already exists and for providing values when creating a new instance.

    Returns:
        tuple[ModelT, bool]: A tuple containing the found or created instance as the first element
            and a boolean indicating whether the instance was created (True) or retrieved
            (False) as the second element.
    """
    instance = session.execute(select(model).filter_by(**kwargs)).scalar()
    if instance:
        return instance, False
    else:
        params = kwargs | (defaults or {})
        instance = model(**params)
        session.add(instance)
        return instance, True
