from __future__ import annotations

import logging
from typing import Any, TypeVar

import attrs
import httpx

RequestT = TypeVar("RequestT")
ResponseT = TypeVar("ResponseT")

logger = logging.getLogger(__name__)


@attrs.define
class HttpClient:
    base_url: str
    headers: dict[str, str]
    client: httpx.Client = attrs.Factory(
        lambda s: httpx.Client(base_url=s.base_url, headers=s.headers), takes_self=True
    )

    def get(self, endpoint: str, *, params: httpx.QueryParams | dict[str, Any]) -> httpx.Response:
        params = params if isinstance(params, httpx.QueryParams) else httpx.QueryParams(params)
        with self.client:
            logging.info("GET %s (params=%s)", endpoint, params)
            response = self.client.get(endpoint, params=params)
            response.raise_for_status()
            return response

    def post(
        self, endpoint: str, *, json: dict[str, Any] | None = None, content: Any | None = None
    ) -> httpx.Response:
        with self.client as client:
            logging.info("POST %s (json=%s, content=%s)", endpoint, json, content)
            response = client.post(endpoint, json=json, content=content)
            response.raise_for_status()
            return response

    def put(
        self, endpoint: str, *, json: dict[str, Any] | None = None, content: Any | None = None
    ) -> httpx.Response:
        with self.client as client:
            logging.info("PUT %s (json=%s, content=%s)", endpoint, json, content)
            response = client.put(endpoint, json=json, content=content)
            response.raise_for_status()
            return response
