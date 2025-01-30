from __future__ import annotations

from typing import Any, TypeVar

import attrs
import httpx

RequestT = TypeVar("RequestT")
ResponseT = TypeVar("ResponseT")


@attrs.define
class HttpClient:
    base_url: str
    headers: dict[str, str]
    client: httpx.Client = attrs.Factory(
        lambda s: httpx.Client(base_url=s.base_url, headers=s.headers), takes_self=True
    )

    def get(self, endpoint: str, *, params: httpx.QueryParams) -> httpx.Response:
        with self.client:
            response = self.client.get(endpoint, params=params)
            response.raise_for_status()
            return response

    def post(
        self, endpoint: str, *, json: dict[str, Any] | None = None, content: Any | None = None
    ) -> httpx.Response:
        with self.client as client:
            response = client.post(endpoint, json=json, content=content)
            response.raise_for_status()
            return response

    def put(
        self, endpoint: str, *, json: dict[str, Any] | None = None, content: Any | None = None
    ) -> httpx.Response:
        with self.client as client:
            response = client.put(endpoint, json=json, content=content)
            response.raise_for_status()
            return response
