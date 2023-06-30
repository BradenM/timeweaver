from pathlib import Path

import rich.prompt
import typer
from rich import print
from rich.console import Group
from rich.tree import Tree

from twtw.db import TableState
from twtw.models.models import Project, ProjectRepository, TeamworkProject

app = typer.Typer()


@app.callback()
def project(ctx: typer.Context):
    """Project commands"""

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
def do_list():
    tbl = TableState.db.table(Project.__name__).all()
    _projects = [Project(name=item["name"]).load() for item in tbl]
    root_projects: set[Project] = {p for p in _projects if p.is_root}
    tree = Tree(label="[b bright_white]Projects", highlight=True, expanded=True)

    for root in root_projects:
        proj_family = create_project_node(root, tree)
        children: set[Project] = {p for p in _projects if p.parent == root}
        for child in children:
            create_project_node(child, proj_family)
    print(tree)


@app.command()
def add(
    name: str,
    tags: str | None = None,
    teamwork_name: str | None = None,
    teamwork_id: int | None = None,
):
    tw_proj = None
    if teamwork_name and teamwork_id:
        tw_proj = TeamworkProject(name=teamwork_name, project_id=teamwork_id)
        tw_proj.save()
    if not tw_proj and teamwork_name:
        _tw_proj = TeamworkProject(name=teamwork_name).load()
        if _tw_proj.project_id:
            tw_proj = _tw_proj
    _tags = parse_tags(tags)
    proj = Project(name=name, tags=_tags, teamwork_project=tw_proj).load()
    proj.save()
    print("[b bright_white]New Project:")
    print(proj)
    print("[b bright_white]Teamwork Project:")
    print(proj.resolve_teamwork_project())


@app.command()
def modify(name: str, new_name: str | None = None, tags: str | None = None):
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
def associate(name: str, path: Path | None = None):
    proj = Project(name=name).load()
    _path = path or Path.cwd()
    proj_repo = ProjectRepository(path=_path)
    if rich.prompt.Confirm.ask(
        f"Associate repo @ [b bright_white]{proj_repo.path}[/] with [b bright_green]{proj.name}[/]?"
    ):
        proj_repo.save()
        proj.repos.append(proj_repo)
        proj.save()
        print("[b bright_white]Updated Project:")
        print(proj)
