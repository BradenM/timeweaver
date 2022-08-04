from __future__ import annotations

import attrs
import httpx

from twtw.models.config import config
from twtw.models.models import TeamworkTimeEntryRequest, TeamworkTimeEntryResponse


@attrs.define
class TeamworkApi:
    base_url: str = attrs.field(default=config.TEAMWORK_HOST)
    person_id: str = attrs.field(default=config.TEAMWORK_UID)
    api_key: str = attrs.field(default=config.API_KEY)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Basic {config.API_KEY}", "Content-Type": "application/json"}

    def create_time_entry(
        self, project_id: str, request: TeamworkTimeEntryRequest
    ) -> TeamworkTimeEntryResponse:
        uri = f"{self.base_url}/projects/{project_id}/time_entries.json"
        payload = request.json(by_alias=True)
        response = httpx.post(uri, headers=self.headers, content=payload)
        response.raise_for_status()
        response_data = TeamworkTimeEntryResponse.parse_obj(response.json())
        return response_data
