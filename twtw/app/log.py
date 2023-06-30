from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, TypeVar

import attr
import questionary
import typer
from pydantic import BaseModel
from rich import print
from tinydb import Query

from twtw.db import TableState
from twtw.models.abc import EntriesSource
from twtw.models.config import config
from twtw.models.models import LogEntry, Project
from twtw.models.timewarrior import TimeWarriorEntry, TimeWarriorLoader, TimeWarriorRawEntry
from twtw.state.commit import TimeWarriorCreateEntryFlow
from twtw.state.csv import CSVCreateEntryFlow

ModelT = TypeVar("ModelT", bound=BaseModel)
T = TypeVar("T")


class CommitMode(str, Enum):
    replicate = "replicate"
    distribute = "distribute"


@attr.s(auto_attribs=True, collect_by_mro=True, kw_only=True)
class QRichPrompt:
    question: "questionary.Question"

    def __rich__(self):
        self.question.ask()


app = typer.Typer()


@app.callback()
def project(ctx: typer.Context):
    """Project commands"""

    def _close_db():
        print("Closing database...")
        TableState.db.close()

    ctx.call_on_close(_close_db)


@app.command(name="pending")
def do_pending(project_name: str = None):
    if project_name:
        proj = Project(name=project_name).load()
        entries = list(reversed(list(TimeWarriorEntry.unlogged_by_project(proj.name))))
        for i in entries:
            print(i)
        return
    tbl = TableState.db.table(Project.__name__).all()
    _projects = [Project(name=item["name"]).load() for item in tbl]
    # root_projects: set[Project] = {p for p in _projects if p.is_root}
    _pending: List["TimeWarriorEntry"] = []
    for proj in _projects:
        _proj_entries = list(TimeWarriorEntry.unlogged_by_project(proj.name))
        _pending += _proj_entries
    _pending = list(reversed(sorted(_pending, key=lambda e: e.start)))
    for i in _pending:
        print(i)


@app.command(name="list")
def do_list(project_name: str = None, synced: bool = None):
    bquery = Query().teamwork_id.exists()
    if synced is False:
        bquery = ~bquery
    if synced is None:
        bquery = Query().noop()
    if project_name:
        bquery &= Query().project.name == Project(name=project_name).load().name

    tbl = TableState.db.table(LogEntry.__name__)
    items = tbl.search(bquery)
    print(items)


@app.command(name="csv")
def do_csv(csv_path: Path, commit: bool = False):
    try:
        flow = CSVCreateEntryFlow(path=csv_path)
        flow.start()
        if commit is False:
            flow.dry_run = True
        flow.choose()
        flow.choose()
    except Exception as e:
        print(e)
    else:
        print(":tada:  [b bright_green]Done!")


@app.command(name="create")
def do_create(name: str, commit: bool = False, distribute: bool = False):
    proj = Project(name=name).load()
    try:
        flow = TimeWarriorCreateEntryFlow(proj=proj, git_author=config.GIT_USER)
        flow.start()
        if commit is False:
            flow.dry_run = True
        flow.should_distribute = distribute
        flow.choose()
        flow.choose()
        try:
            flow.choose()
        except KeyboardInterrupt as e:
            raise typer.Abort(e)
        except Exception as e:
            print(e)
        try:
            flow.choose()
        except KeyboardInterrupt:
            raise typer.Abort(e)
        except Exception as e:
            print(e)
    except KeyboardInterrupt as e:
        raise typer.Abort(e)
    except Exception as e:
        print("Error:")
        print(e)
        # import pdb
        #
        # pdb.xpm()
        raise
    else:
        print(":tada:  [b bright_green]Done!")


def get_project_tags() -> set[str]:
    return set([t["name"].lower() for t in Project.table_of().all()])


def build_timew_source(
    filters: list[Callable[[dict], bool]], project_tags: set[str] | None = None
) -> EntriesSource:
    project_tags = project_tags or get_project_tags()
    print("project tags:", project_tags)
    source = EntriesSource.from_loader(
        TimeWarriorLoader, filters=filters, project_tags=list(project_tags)
    )
    return source


def get_timew_entry(
    id: int, *, source: EntriesSource | None = None, project_tags: set[str] | None = None
) -> TimeWarriorRawEntry:
    source = source or build_timew_source([lambda v: v["id"] != id], project_tags=project_tags)
    try:
        entry: TimeWarriorRawEntry = next((i for i in source.loader.entries if i.id == id))
    except StopIteration as e:
        raise RuntimeError("Entry not found!") from e
    return entry


@app.command(name="swap")
def do_swap(new_project: str, ids: list[int], annotation: Optional[str] = None):
    """Swap project for given entry ids."""
    project_tags = get_project_tags()

    def swap(id: int):
        entry = get_timew_entry(id, project_tags=project_tags)
        print("Found entry:", entry)
        current_proj_name = next((i for i in entry.tags if i.lower() in project_tags))
        current_proj = Project(name=current_proj_name.upper()).load()
        print("[bright_red] :x: Will remove project:", current_proj)
        print("[bright_red] :x: Will remove annotation:", entry.annotation)
        new_proj: Project = Project(name=new_project.upper()).load()
        new_annot = annotation or entry.annotation
        print("[bold bright_green] :heavy_check_mark: Will set project:", new_proj)
        print("[bold bright_green] :heavy_check_mark: Will set annotation:", new_annot)
        typer.confirm("Confirm changes?", abort=True)
        entry = (
            entry.remove_tag(current_proj_name.lower())
            .remove_tag(entry.annotation)
            .add_tags(new_proj.name.lower(), new_annot)
        )
        print("[bold bright_green]Done!")

    for id in ids:
        swap(id)


@app.command(name="reannotate")
def do_reannotate(id: int, annotation: str):
    """Update annotation of given entry."""
    entry = get_timew_entry(id)
    print("[bright_red] :x: Will remove annotation:", entry.annotation)
    print("[bold bright_green] :heavy_check_mark: Will add annotation:", annotation)
    typer.confirm("Confirm changes?", abort=True)
    entry = entry.remove_tag(entry.annotation).add_tag(annotation)
    print(entry)
    print("[bold bright_green]Done!")
