from __future__ import annotations

import abc
from collections.abc import Iterable
from typing import Any, Callable, Protocol, T, TypeAlias, TypeVar, runtime_checkable

import attrs
import questionary
from rich import get_console
from rich.console import Console

ChoiceT = TypeVar("ChoiceT")
ChoiceKeyFunc: TypeAlias = Callable[[ChoiceT], str] | None


@runtime_checkable
class HasMultiSelect(Protocol):
    def create_choices(
        self, items: Iterable[ChoiceT], key: ChoiceKeyFunc, *args, **kwargs
    ) -> Iterable[ChoiceT | Any]:
        ...

    def create_multiselect(
        self, items: Iterable[ChoiceT], key: ChoiceKeyFunc, *args, **kwargs
    ) -> Iterable[ChoiceT | Any]:
        ...


@attrs.define
class Prompter(abc.ABC):
    @abc.abstractmethod
    def invoke_prompt(self, *args, **kwargs):
        ...

    def multiselect(self, items: Iterable[ChoiceT], *args, key: ChoiceKeyFunc = None, **kwargs):
        if not isinstance(self, HasMultiSelect):
            raise TypeError("Prompter does not support multiselect.")
        prompt = self.create_multiselect(items, key, *args, **kwargs)
        return self.invoke_prompt(prompt)


@attrs.define
class QuestionaryPrompter(Prompter, HasMultiSelect):
    def create_choices(
        self, items: Iterable[ChoiceT], key: Callable[[ChoiceT], str] | None, *args, **kwargs
    ) -> Iterable[questionary.Choice]:
        get_key = key or str
        for i in items:
            yield questionary.Choice(title=get_key(i), value=i)

    def create_multiselect(
        self, items: Iterable[ChoiceT], key: ChoiceKeyFunc = None, *args, title: str, **kwargs
    ) -> questionary.Question:
        choices = self.create_choices(items, key)
        return questionary.checkbox(title, choices=choices, **kwargs)

    def invoke_prompt(self, prompt: questionary.Question) -> T:
        return prompt.ask()


@attrs.define
class Reporter:
    console: Console = attrs.field(factory=get_console)
    prompt: Prompter = attrs.field(factory=QuestionaryPrompter)
