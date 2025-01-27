from collections import defaultdict
from contextlib import contextmanager
from typing import Any, TypeVar

from git import BadName
from rich import print
from rich.progress import track
from sqlmodel import Session, SQLModel, select
from tinydb.table import Table

from twtw.db import TableState
from twtw.models.models import CommitEntry, LogEntry, Project, ProjectRepository, TeamworkProject
from twtw.session import create_db_and_tables, engine
from twtw.utils import get_or_create, pick

ModelT = TypeVar("ModelT", bound=SQLModel)


@contextmanager
def report_model():
    results_map = defaultdict[str, dict[str, int]](lambda: dict(created=0, existing=0))

    def add_entry(session: Session, model: type[ModelT], **kwargs) -> tuple[ModelT, bool]:
        inst, did_create = get_or_create(session, model, **kwargs)
        result_key = "created" if did_create else "existing"
        results_map[model.__name__][result_key] += 1
        return inst, did_create

    try:
        yield add_entry, results_map
    finally:
        for model_name, results in results_map.items():
            print(
                f"[b bright_green]:heavy_check_mark: Created {results['created']} new [b i bright_cyan]{model_name}[/b i bright_cyan] items"
            )
            print(
                f"[b bright_gray]:information: Skipped {results['existing']} existing [b i bright_cyan]{model_name}[/b i bright_cyan] items"
            )


def report_model_header(table: Table):
    print(
        f"[b bright_white]Migrating[/] [b i bright_cyan]{table.name}[/] [b bright_gray]({len(table)} items)"
    )


def migrate_projects():
    teamwork_projects = TableState.db.table(TeamworkProject.__name__)
    projects = TableState.db.table(Project.__name__)

    tw_projects_by_id = dict()

    with Session(engine) as session:
        report_model_header(teamwork_projects)
        with report_model() as model_report:
            get_or_create_entry, _ = model_report
            for item in teamwork_projects.all():
                inst, _ = get_or_create_entry(session, TeamworkProject, **item)
                tw_projects_by_id[inst.project_id] = inst
        session.commit()

    report_model_header(projects)

    projects_by_name = {p["name"]: p for p in projects.all()}
    root_tw_projects: dict[str, TeamworkProject] = dict()

    with Session(engine) as session:
        with report_model() as model_report:
            get_or_create_entry, _ = model_report
            for project_name in sorted(projects_by_name):
                item = projects_by_name[project_name]
                if project_tw := item.pop("teamwork_project", None):
                    tw_proj = tw_projects_by_id[project_tw["project_id"]]
                    root_tw_projects[item["name"]] = tw_proj
                else:
                    parent_name = ".".join(item["name"].split(".")[:-1])
                    tw_proj = root_tw_projects.get(parent_name, None)

                if tw_proj is None:
                    print(
                        f'[bright_red]Error[/] [bright_white]Could not find TeamworkProject for project[/] [bright_cyan]{item["name"]}'
                    )

                repos = item.pop("repos", [])

                lookup = pick(item, ["name"])
                # get/create new project
                inst, _ = get_or_create_entry(
                    session, Project, defaults=item | {"teamwork_project": tw_proj}, **lookup
                )
                inst.validate_parent(session)

                # migrate ProjectRepositories for given project
                for repo in repos:
                    repo, _ = get_or_create_entry(
                        session, ProjectRepository, **repo | {"project": inst}
                    )

        session.commit()

    print("[b bright_green]Migrated Projects!")


def migrate_entries():
    commit_entries = TableState.db.table(CommitEntry.__name__)
    log_entries = TableState.db.table(LogEntry.__name__)

    def resolve_commit_repo(
        project_repos: list[ProjectRepository], commit_sha: str
    ) -> dict[str, Any]:
        for project_repo in project_repos:
            git_repo = project_repo.git_repo
            try:
                commit = git_repo.commit(commit_sha)
                if commit:
                    return {"repo": project_repo, "commit": commit}
            except (BadName, ValueError):
                continue
        print(
            f"[bright_red]Error[/] [bright_white]Could not find commit[/] [bright_cyan]{commit_sha}"
        )
        return {"repo": None, "commit": None}

    report_model_header(log_entries)
    with Session(engine) as session:
        with report_model() as model_report:
            get_or_create_entry, _ = model_report
            for item in log_entries.all():
                project_info = item.pop("project")
                project = session.exec(
                    select(Project).where(Project.name == project_info["name"].upper())
                ).first()
                get_or_create_entry(session, LogEntry, defaults={"project": project}, **item)
        session.commit()

    report_model_header(commit_entries)
    with Session(engine) as session:
        project_repos = list(session.exec(select(ProjectRepository)).all())

        with report_model() as model_report:
            get_or_create_entry, _ = model_report

            for item in track(commit_entries.all(), description="Migrating commits..."):
                commit_sha = item.pop("sha")
                resolved_repo = resolve_commit_repo(project_repos, commit_sha)
                get_or_create_entry(
                    session,
                    CommitEntry,
                    defaults=resolved_repo,
                    **item,
                    commit=resolved_repo["commit"],
                )
        session.commit()


def migrate():
    create_db_and_tables()

    sorted_tables = {
        TeamworkProject,
        Project,
        ProjectRepository,
        CommitEntry,
        LogEntry,
    }

    for table in sorted_tables:
        with Session(engine):
            table_name = table.__name__
            db_table = TableState.db.table(table_name)
            count = len(db_table)
            print(
                f"[b bright_white]Migrating[/] [b i bright_cyan]{table_name}[/] [b bright_gray]({count} items)"
            )

    migrate_projects()
    migrate_entries()


if __name__ == "__main__":
    migrate()
