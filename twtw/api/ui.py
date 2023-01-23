from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable, Protocol, T, TypeAlias, TypeVar, runtime_checkable

import attrs
import questionary
from rich import get_console
from rich.console import Console
from rich.prompt import Confirm, PromptBase

ChoiceT = TypeVar("ChoiceT")
ChoiceKeyFunc: TypeAlias = Callable[[ChoiceT], str] | None

PromptType = TypeVar("PromptType")


@runtime_checkable
class Promptable(Protocol[PromptType]):
    def invoke_prompt(self, prompt: PromptType, *args, **kwargs):
        ...


@runtime_checkable
class HasMultiSelect(Protocol):
    def create_choices(
        self,
        items: Iterable[ChoiceT],
        *,
        key: ChoiceKeyFunc = None,
        disabled: Callable[[ChoiceT], str] = None,
    ) -> Iterable[ChoiceT | Any]:
        ...

    def create_multiselect(
        self,
        items: Iterable[ChoiceT],
        *,
        title: str = None,
        key: ChoiceKeyFunc = None,
        disabled: Callable[[ChoiceT], str] = None,
    ) -> Iterable[ChoiceT | Any] | Any:
        ...


@runtime_checkable
class HasConfirm(Protocol):
    def create_confirm(self, text: str, *args, **kwargs) -> Callable[[Any], bool] | Any:
        ...


@attrs.define
class QuestionaryPrompt(Promptable[questionary.Question]):
    def invoke_prompt(self, prompt: questionary.Question, **kwargs) -> T:
        return prompt.ask()


@attrs.define
class RichPrompt(Promptable[PromptBase]):
    def invoke_prompt(self, prompt: PromptBase[T], *args, **kwargs) -> T:
        return prompt(**kwargs)


@attrs.define
class QuestionaryMultiSelect(QuestionaryPrompt, HasMultiSelect):
    def create_choices(
        self,
        items: Iterable[ChoiceT],
        *,
        key: ChoiceKeyFunc = None,
        disabled: Callable[[ChoiceT], str] = None,
    ) -> Iterable[questionary.Choice]:
        get_key = key or str
        disabled = disabled or (lambda _: None)
        for i in items:
            yield questionary.Choice(title=get_key(i) or "", value=i, disabled=disabled(i))

    def create_multiselect(
        self,
        items: Iterable[ChoiceT],
        *,
        title: str = None,
        key: ChoiceKeyFunc = None,
        disabled: Callable[[ChoiceT], str] = None,
        style: questionary.Style = None,
    ) -> questionary.Question:
        styles = style or questionary.Style([("disabled", "fg:#E32636 italic bold")])
        choices = self.create_choices(items, key=key, disabled=disabled)
        return questionary.checkbox(title or "Choose", choices=list(choices), style=styles)


@attrs.define
class RichConfirm(RichPrompt, HasConfirm):
    def create_confirm(self, text: str, *args, **kwargs) -> Callable[[Any], bool] | Any:
        return lambda: Confirm.ask(text, *args, **kwargs)


@attrs.define
class Prompter:
    prompt_types: list[Promptable] = attrs.field(factory=list)

    def add(self, prompt_type: Promptable):
        self.prompt_types.append(prompt_type)

    def resolve_prompt(self, proto: Promptable) -> Promptable:
        try:
            return next((i for i in self.prompt_types if isinstance(i, proto)))
        except StopIteration as e:
            raise TypeError(f"No prompt type found for protocol: {proto}") from e

    def multiselect(self, items: Iterable[ChoiceT], **kwargs):
        prompt_type = self.resolve_prompt(HasMultiSelect)
        prompt = prompt_type.create_multiselect(items, **kwargs)
        return prompt_type.invoke_prompt(prompt)

    def confirm(self, text: str, *args, **kwargs) -> bool:
        prompt_type = self.resolve_prompt(HasConfirm)
        prompt = prompt_type.create_confirm(text, *args, **kwargs)
        return prompt_type.invoke_prompt(prompt)


@attrs.define
class Reporter:
    console: Console = attrs.field(factory=get_console)
    prompt: Prompter = attrs.field(
        factory=lambda: Prompter(prompt_types=[QuestionaryMultiSelect(), RichConfirm()])
    )

    def render_text(self, *items: str) -> str:
        with self.console.capture() as capture:
            self.console.print(*items)
        return capture.get()
