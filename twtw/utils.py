import itertools
from typing import Any, Callable, Protocol, Sequence, TypeVar


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
    return dict(
        (key, list(group))
        for key, group in itertools.groupby(sorted(in_seq, key=key_fn), key=key_fn)
    )
