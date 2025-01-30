from __future__ import annotations

import logging

import attrs
from rich import print

from twtw.models.config import config
from twtw.models.models import LogEntry
from twtw.models.teamwork import (
    TeamworkTimeEntriesList,
    TeamworkTimeEntry,
    TeamworkTimeEntryRequest,
    TeamworkTimeEntryResponse,
)

from ._api import HttpClient

logger = logging.getLogger(__name__)


@attrs.define
class TeamworkApi:
    base_url: str = attrs.Factory(lambda: config.TEAMWORK_HOST)
    basic_auth: str = attrs.Factory(lambda: config.API_KEY)
    person_id: str = attrs.Factory(lambda: config.TEAMWORK_UID)
    client: HttpClient = attrs.Factory(
        lambda s: HttpClient(
            base_url=s.base_url,
            headers={"Authorization": f"Basic {s.basic_auth}", "Content-Type": "application/json"},
        ),
        takes_self=True,
    )

    def _validate_time_entry_response(self, response) -> TeamworkTimeEntryResponse:
        response = TeamworkTimeEntryResponse.parse_obj(response.json())
        if not response.status == "OK":
            raise RuntimeError(
                f"Failed to post entry, teamwork responded with: {response.status} ({response})"
            )
        return response

    def create_time_entry(
        self, *, log_entry: LogEntry, project_id: str | int, person_id: str | int | None = None
    ) -> TeamworkTimeEntryResponse:
        """Create a new teamwork time entry."""
        request = TeamworkTimeEntryRequest.from_entry(
            entry=log_entry, person_id=person_id or self.person_id
        )
        print(
            f"[b bright_black]Creating Time Entry: {request.time_entry.hours}:{request.time_entry.minutes} @ {request.time_entry.date} [{request.time_entry.tags}]"
        )
        endpoint = f"/projects/{project_id}/time_entries.json"
        response = self.client.post(endpoint, content=request.json(by_alias=True))
        return self._validate_time_entry_response(response)

    def update_time_entry(
        self, log_entry: LogEntry, person_id: str | int | None = None
    ) -> TeamworkTimeEntryResponse:
        """Update an existing teamwork time entry."""
        request = TeamworkTimeEntryRequest.from_entry(
            entry=log_entry, person_id=person_id or self.person_id
        )
        print(
            f"[b bright_black]Updating Time Entry (id: {log_entry.teamwork_id}): {request.time_entry.hours}:{request.time_entry.minutes} @ {request.time_entry.date} [{request.time_entry.tags}]"
        )
        endpoint = f"/time_entries/{log_entry.teamwork_id}.json"
        response = self.client.put(endpoint, content=request.json(by_alias=True))
        return self._validate_time_entry_response(response).copy(
            update={"time_log_id": log_entry.teamwork_id}
        )

    def list_time_entries(
        self,
        project_id: str | int | None = None,
        person_id: str | int | None = None,
        limit: int = 100,
    ) -> list[TeamworkTimeEntry]:
        """List teamwork time entries."""
        endpoint = (
            "/time_entries.json"
            if project_id is None
            else f"/projects/{project_id}/time_entries.json"
        )
        params = {"pagesize": limit, "sortorder": "desc"}
        if person_id:
            params |= {"userId": person_id}
        response = self.client.get(endpoint, params=params)
        data = TeamworkTimeEntriesList.parse_obj(response.json())
        if data.status != "OK":
            raise RuntimeError(f"Failed to list entries, teamwork responded with: {data.status}")
        return data.time_entries or []
