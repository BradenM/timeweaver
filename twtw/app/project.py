from pathlib import Path
from typing import Optional

import rich.prompt
import typer
from rich import print
from rich.console import Group
from rich.panel import Panel
from rich.tree import Tree

from twtw.db import TableState
from twtw.models.models import Project, ProjectRepository, TeamworkProject

app = typer.Typer()


def parse_tags(in_tags: Optional[str] = None) -> Optional[list[str]]:
    if not in_tags:
        return []
    _tags = in_tags.split(",")
    return [t.strip() for t in _tags]


# def project_as_table(proj: Project):
#     table = Table(row_styles=["", "dim"])
#     table.add_column("")


@app.command(name="list")
def do_list():
    tbl = TableState.db.table(Project.__name__).all()
    _projects = [Project(name=item["name"]).load() for item in tbl]
    root_projects: set[Project] = {p for p in _projects if p.is_root}
    tree = Tree(label="[b bright_white]Projects", highlight=True, expanded=True)
    for root in root_projects:
        tw_proj = root.resolve_teamwork_project()
        tags = "[bold bright_white]Tags: [/bold bright_white]" + ", ".join(root.tags)
        root_group = Group(f"[b bright_cyan]{root.name}")
        root_attrs_group = Group(tags)
        if tw_proj:
            root_attrs_group.renderables.append(tw_proj)
        root_group.renderables.append(Panel.fit(root_attrs_group, border_style="cyan"))
        proj_family = tree.add(root_group)
        children: set[Project] = {p for p in _projects if p.parent == root}
        for child in children:
            child_node = proj_family.add(f"[b bright_white]{child.nickname}", highlight=True)
            repo_node = child_node.add("[bright_white]Repos")
            for repo in child.repos:
                repo_node.add(
                    Group(
                        f"[b green]{repo.name}",
                        str(repo.path),
                    )
                )
    print(tree)


@app.command()
def add(
    name: str,
    tags: Optional[str] = None,
    teamwork_name: Optional[str] = None,
    teamwork_id: Optional[int] = None,
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
def modify(name: str, new_name: Optional[str] = None, tags: Optional[str] = None):
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
def associate(name: str, path: Optional[Path] = None):
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
