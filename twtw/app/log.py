from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, TypeVar

import attr
import questionary
import sh
import typer
from pydantic import BaseModel
from rich import print
from sqlmodel import Session, select

from twtw.data import SQLAlchemyDataAccess
from twtw.db import TableState
from twtw.models.abc import EntriesSource
from twtw.models.config import config
from twtw.models.models import LogEntry, Project
from twtw.models.timewarrior import TimeWarriorEntry, TimeWarriorLoader, TimeWarriorRawEntry
from twtw.session import create_db_and_tables, engine
from twtw.state.commit import TimeWarriorCreateEntryFlow
from twtw.state.csv import CSVCreateEntryFlow
from twtw.state.entry import CreateFlowState

ModelT = TypeVar("ModelT", bound=BaseModel)
T = TypeVar("T")


class CommitMode(str, Enum):
    replicate = "replicate"
    distribute = "distribute"


@attr.s(auto_attribs=True, collect_by_mro=True, kw_only=True)
class QRichPrompt:
    question: questionary.Question

    def __rich__(self):
        self.question.ask()


app = typer.Typer(no_args_is_help=True)


@app.callback()
def log(ctx: typer.Context):
    """Log commands"""
    create_db_and_tables()

    def _close_db():
        print("Closing database...")
        TableState.db.close()

    ctx.call_on_close(_close_db)


@app.command(name="pending")
def do_pending(project_name: Optional[str] = None):  # noqa: UP007
    if project_name:
        proj = Project(name=project_name).load()
        entries = list(reversed(list(TimeWarriorEntry.unlogged_by_project(proj.name))))
        for i in entries:
            print(i)
        return
    tbl = TableState.db.table(Project.__name__).all()
    _projects = [Project(name=item["name"]).load() for item in tbl]
    # root_projects: set[Project] = {p for p in _projects if p.is_root}
    _pending: list[TimeWarriorEntry] = []
    for proj in _projects:
        _proj_entries = list(TimeWarriorEntry.unlogged_by_project(proj.name))
        _pending += _proj_entries
    _pending = sorted(_pending, key=lambda e: e.start, reverse=True)
    for i in _pending:
        print(i)


@app.command(name="list")
def do_list(project_name: Optional[str] = None, synced: Optional[bool] = None):  # noqa: UP007
    with Session(engine) as session:
        stmt = select(LogEntry)
        if project_name:
            project = session.exec(
                select(Project).where(Project.name == project_name.upper())
            ).first()
            stmt = stmt.join(Project).where(LogEntry.project == project)
        if synced is not None:
            stmt = stmt.where(
                LogEntry.teamwork_id.isnot(None) if synced else LogEntry.teamwork_id.is_(None)
            )

        items = session.exec(stmt).all()
        for i in items:
            print(i)


@app.command(name="csv")
def do_csv(csv_path: Path, commit: bool = False):
    with Session(engine) as session:
        projects = list(session.exec(select(Project)).all())
        dataaccess = SQLAlchemyDataAccess(session)
        try:
            flow = CSVCreateEntryFlow(path=csv_path, projects=projects, db=dataaccess)
            flow.start()
            if commit is False:
                flow.dry_run = True
            flow.choose()
            flow.choose()
        except Exception as e:
            print(e)
        else:
            if commit:
                session.commit()
            print(":tada:  [b bright_green]Done!")


@app.command(name="create")
def do_create(name: str, commit: bool = False, draft: bool = False, distribute: bool = False):
    with Session(engine) as session:
        dataaccess = SQLAlchemyDataAccess(session)
        projects = list(session.exec(select(Project)).all())
        proj = session.exec(select(Project).where(Project.name == name.upper())).first()
        flow = TimeWarriorCreateEntryFlow(
            proj=proj, git_author=config.GIT_USER, projects=projects, db=dataaccess
        )
        flow.start()
        if commit and draft:
            raise RuntimeError("Cannot both commit and draft logs!")
        is_dryrun = not commit and not draft
        if is_dryrun:
            flow.dry_run = is_dryrun
        if draft:
            flow.draft_logs = draft
        flow.should_distribute = distribute
        while True:
            if flow.machine.is_state(CreateFlowState.CANCEL, flow):
                print(
                    "[bright_black][bold](DRY RUN)[/bold] Pass [bright_white bold]--commit[/bright_white bold] to submit logs or [bright_white bold]--draft[/bright_white bold] to submit drafts."
                )
                print("[dark_orange]Cancelled!")
                break
            try:
                flow.choose()
            except KeyboardInterrupt as e:
                raise typer.Abort(e) from e
            except Exception as e:
                print(e, type(e))
                break
            else:
                if commit:
                    session.commit()
                print(":tada:  [b bright_green]Done!")


def get_project_tags() -> set[str]:
    return {t["name"].lower() for t in Project.table_of().all()}


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
        entry: TimeWarriorRawEntry = next(i for i in source.loader.entries if i.id == id)
    except StopIteration as e:
        raise RuntimeError("Entry not found!") from e
    return entry


@app.command(name="swap")
def do_swap(new_project: str, ids: list[int], annotation: str = None):  # noqa: RUF013
    """Swap project for given entry ids."""
    project_tags = get_project_tags()

    def swap(id: int):
        entry = get_timew_entry(id, project_tags=project_tags)
        print("Found entry:", entry)
        current_proj_name = next(i for i in entry.tags if i.lower() in project_tags)
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


class TimeSide(str, Enum):
    start = "start"
    end = "end"


@app.command(name="modify-relative")
def do_modify_relative(side: TimeSide, id: int, time: str):
    entry = get_timew_entry(id)
    time_obj = datetime.strptime(time, "%I:%M%p").time()
    date_to_modify = entry.start if side == "start" else entry.end
    new_date = datetime.combine(date_to_modify.date(), time_obj)
    print("[bold bright_green]Found entry:[/]", entry)
    print(
        f"Will modify: {entry.str_id} {side!s} from {date_to_modify} ({date_to_modify.isoformat()}) to {new_date} ({new_date.isoformat()})"
    )
    tw: sh.Command = sh.Command("timew")
    cmd = tw.modify.bake(side.value, entry.str_id, new_date.isoformat())
    print(f"[bright_cyan]Command:[/] [i bright_black]: {cmd!s}")
    typer.confirm("Confirm changes?", abort=True)
    cmd()
