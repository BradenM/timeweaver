#!/usr/bin/env python3
import re
from pathlib import Path
from typing import List, Optional

import git
import typer
from rich import print
from rich.traceback import install

from twtw import aggregate as twaggregate
from twtw import config as twconfig
from twtw import recent as twrecent
from twtw import tw
from twtw.app.config import app as config_app
from twtw.app.log import app as log_app
from twtw.app.project import app as project_app
from twtw.teamwork import load_entries

install(show_locals=True, suppress=["typer", "click", "transitions"])

app = typer.Typer()
app.add_typer(config_app, name="config")
app.add_typer(project_app, name="project")
app.add_typer(log_app, name="log")


@app.callback()
def cli():
    """ArroyoDev Timewarrior Integration Entrypoint"""


@app.command()
def recent(days: Optional[float] = 3, unlogged: bool = False):
    """Preview recent entries."""
    twrecent.get_recent(days=days, unlogged=unlogged)


@app.command()
def aggregate():
    """Aggregate time entries.."""
    twaggregate.get_aggregates()


@app.command()
def sync(commit: bool = False):
    """arroyoDev Timewarrior Integration Entrypoint"""
    load_entries(commit=commit)


# @app.command()
# def csv(csv_path: Path, commit: bool = False):
#     """arroyoDev CSV Teamwork integration entrypoint."""
#     csv_path = Path(csv_path)
#     twcsv.load_entries(csv_path, commit=commit)


@app.command()
def set_key(api_key: str):
    """Set Api Key."""
    config = twconfig.load_config()
    config.api_key = api_key
    config.save()


def time_in_range(start, end, x):
    """Return true if x is in the range [start, end]"""
    if start <= end:
        return start <= x <= end
    else:
        return start <= x or x <= end


@app.command()
def changelog(
    sha: str,
    tag: List[int],
    end_sha: Optional[str] = None,
    save: bool = False,
    raw: bool = False,
    latest: bool = False,
):
    cwd = Path.cwd()
    repo = git.Repo(cwd)

    # get commits from parent of SHA to HEAD.
    # so commits[0] os the most recent, and commits[-1] is the parent of SHA's rev.
    sha_rng = f"{sha}~1..."
    if end_sha:
        sha_rng = f"{sha_rng}{end_sha}"
    commits = list(repo.iter_commits(sha_rng))
    commits = list(reversed([c for c in commits if c.author.email == "bradenmars@bradenmars.me"]))
    print(f"[bright_white]Found [b]{len(commits)}[/b] commits.")

    _, data = tw.parse_timewarrior(process=True)
    data = [e for e in data if e["id"] in tag]

    conv_commit_pattern = re.compile(
        r"^(?P<type>build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test|tests)(\((?P<scope>.+)\))?: (?P<title>.+$)"
    )

    dfmt = "%b %d"
    commit_shas = set()
    excluded_shas = set()
    entries = {}

    def add_commit(commit: git.Commit):
        commit_dt = commit.authored_datetime.strftime(dfmt)
        summary = commit.summary
        # typer.secho(f"Matching: {summary}")
        parts = conv_commit_pattern.match(summary).groupdict()
        ctype = parts["type"].strip()
        scope = (parts.get("scope", "other") or "other").lower().strip()
        title = parts.get("title").strip()

        entries.setdefault(commit_dt, {})
        entries[commit_dt].setdefault(scope, {})
        entries[commit_dt][scope].setdefault(ctype, [])
        entries[commit_dt][scope][ctype].append(title)

    def create_chlog(ets):
        chlog_out = ""
        for dtime, scopes in ets.items():
            # desc = f"\n== {dtime} =="
            desc = ""
            lb = "<BR>" if (save or raw) else "\n"
            subheader_tmpl = "## {type} ({scope}): {lb}"
            for scope, types in scopes.items():
                # scope_desc = f"## {scope.capitalize()}"
                for type, titles in types.items():
                    desc += subheader_tmpl.format(type=type.capitalize(), scope=scope, lb=lb)
                    for title in titles:
                        desc += f"  • {title.capitalize()}{lb}"

            chlog_out += desc
        return chlog_out

    for tentry in data:
        for commit in commits:
            if latest or time_in_range(
                tentry["start"], tentry["end"], commit.authored_datetime.astimezone()
            ):
                if not commit_shas.issuperset({commit.hexsha}):
                    add_commit(commit)
                commit_shas.add(commit.hexsha)
            else:
                if not commit_shas.issuperset({commit.hexsha}):
                    excluded_shas.add(commit.hexsha)

    chlog = create_chlog(entries)
    print(f"[bold bright_green]Commits: [bright_white]{len(commit_shas)}")
    print(f"[bold bright_yellow]Excluded: [bright_white]{len(excluded_shas)}")
    print()
    print(chlog)
    for tentry in data:
        if save:
            tw.annotate_entry(tentry["id"], chlog)


if __name__ == "__main__":
    app()
