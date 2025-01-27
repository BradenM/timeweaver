from pathlib import Path
from typing import Optional

import rich.prompt
import typer
from rich import print
from rich.console import Group
from rich.tree import Tree
from sqlmodel import Session, select

from twtw.db import TableState
from twtw.models.models import Project, ProjectRepository, TeamworkProject
from twtw.session import create_db_and_tables, engine
from twtw.utils import get_or_create

app = typer.Typer()


@app.callback()
def project(ctx: typer.Context):
    """Project commands"""
    create_db_and_tables()

    def _close_db():
        print("Closing database...")
        TableState.db.close()

    ctx.call_on_close(_close_db)


def parse_tags(in_tags: str | None = None) -> list[str] | None:
    if not in_tags:
        return []
    _tags = in_tags.split(",")
    return [t.strip() for t in _tags]


def create_project_node(project: Project, root: Tree) -> Tree:
    """Create project tree node."""
    child_node = root.add(f"[bold underline bright_white]{project.nickname}", highlight=True)
    child_tw = project.resolve_teamwork_project()
    if child_tw:
        child_node.add(child_tw)
    if any(project.tags):
        child_node.add("[bold cyan]Tags: [/][i]" + ", ".join(project.tags))
    repo_node = child_node.add("[bold medium_spring_green]Repos")
    for repo in project.repos:
        repo_node.add(
            Group(
                f"[b green]{repo.name}",
                str(repo.path),
            )
        )
    return child_node


@app.command(name="list")
def do_list(search: str | None = None):
    with Session(engine) as session:
        stmt = select(Project)
        if search:
            stmt = stmt.where(Project.name.like(f"%{search.upper()}%"))
        _projects = list(session.exec(stmt))
        root_projects: set[Project] = {p for p in _projects if p.is_root}
        tree = Tree(label="[b bright_white]Projects", highlight=True, expanded=True)

        for root in root_projects:
            proj_family = create_project_node(root, tree)
            children: set[Project] = {p for p in _projects if p.parent and p.parent == root}
            for child in children:
                create_project_node(child, proj_family)
        print(tree)


@app.command()
def add(
    name: str,
    tags: Optional[str] = None,  # noqa: RUF013, RUF100, UP007
    teamwork_name: Optional[str] = None,  # noqa: RUF013, RUF100, UP007
    teamwork_id: Optional[int] = None,  # noqa: RUF013, RUF100, UP007
):
    with Session(engine) as session:
        tw_proj = None
        if teamwork_id or teamwork_name:
            tw_proj = session.exec(
                select(TeamworkProject).where(
                    TeamworkProject.project_id == teamwork_id
                    or TeamworkProject.name == teamwork_name
                )
            ).first()
            if not tw_proj:
                tw_proj = TeamworkProject(name=teamwork_name, project_id=teamwork_id)
                session.add(tw_proj)

        _tags = parse_tags(tags)

        proj, did_create = get_or_create(
            session, Project, defaults={"tags": _tags, "teamwork_project": tw_proj}, name=name
        )
        if not did_create:
            print(f"[b bright_red]Project {name} already exists.")
            raise typer.Abort()
        session.add(proj)
        proj.validate_parent(session)
        print("[b bright_white]New Project:")
        print(proj)
        print("[b bright_white]Teamwork Project:")
        session.commit()


@app.command()
def modify(name: str, new_name: Optional[str] = None, tags: Optional[str] = None):  # noqa: UP007
    proj = Project(name=name).load()
    _tags = parse_tags(tags)
    print(new_name)
    if new_name:
        proj.name = new_name
    if any(_tags):
        new_tags = set(proj.tags) & set(_tags)
        proj.tags = list(new_tags)
    proj.save()
    print(proj)


@app.command()
def delete(name: str):
    """Delete a given project."""
    with Session(engine) as session:
        proj = session.exec(select(Project).where(Project.name == name.upper())).first()
        if proj:
            if rich.prompt.Confirm.ask(
                f"[b bright_white]Delete project [b bright_red]{proj.name}[/] and all associated repos?"
            ):
                session.delete(proj)
                session.commit()
                print(f"[b bright_green]Deleted project: {name}")


@app.command()
def associate(name: str, path: Optional[Path] = None):  # noqa: UP007
    with Session(engine) as session:
        proj = session.exec(select(Project).where(Project.name == name.upper())).first()
        print("resolved project:", proj)
        _path = path or Path.cwd()
        proj_repo = ProjectRepository(path=str(_path), project=proj)
        if rich.prompt.Confirm.ask(
            f"Associate repo @ [b bright_white]{proj_repo.path}[/] with [b bright_green]{proj.name}[/]?"
        ):
            session.add(proj_repo)
            session.commit()
            print("[b bright_white]Updated Project:")
            print(proj)


if __name__ == "__main__":
    app()
