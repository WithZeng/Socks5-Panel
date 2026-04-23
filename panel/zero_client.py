import logging
from dataclasses import dataclass
from typing import Any

import requests


logger = logging.getLogger(__name__)


@dataclass
class ZeroAPIError(RuntimeError):
    status: int
    message: str
    body: str = ""

    def __str__(self) -> str:
        detail = f" ({self.body[:240]})" if self.body else ""
        return f"Zero API error {self.status}: {self.message}{detail}"


class ZeroClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 10,
        session: requests.Session | None = None,
        dry_run: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.dry_run = dry_run

    def get_subscription(self):
        return self._request("GET", "/api/subscription")

    def list_lines(self):
        return self._request("GET", "/api/subscription/lines")

    def list_forward_endpoints(self):
        return self._request("GET", "/api/forward_endpoints")

    def list_ports(
        self,
        *,
        line_id: int | None = None,
        outbound_endpoint_id: int | None = None,
        page: int = 1,
        page_size: int = 50,
    ):
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if line_id is not None:
            params["line_id"] = line_id
        if outbound_endpoint_id is not None:
            params["outbound_endpoint_id"] = outbound_endpoint_id
        return self._request("GET", "/api/ports", params=params)

    def iter_all_ports(self, **filters):
        page = 1
        while True:
            data, _ = self.list_ports(page=page, **filters)
            items = self._extract_items(data)
            for item in items:
                yield item

            if not items or not self._has_next_page(data, page):
                break
            page += 1

    def create_port(self, payload: dict[str, Any]):
        return self._write_request("POST", "/api/ports", json=payload)

    def update_port(self, port_id: int, payload: dict[str, Any]):
        return self._write_request("PATCH", f"/api/ports/{port_id}", json=payload)

    def delete_port(self, port_id: int):
        return self._write_request("DELETE", f"/api/ports/{port_id}")

    def _write_request(self, method: str, path: str, **kwargs):
        if self.dry_run:
            logger.info("Zero dry-run %s %s payload=%s", method, path, kwargs.get("json"))
            return {"dry_run": True, "path": path, "method": method, "payload": kwargs.get("json")}, None
        return self._request(method, path, **kwargs)

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["X-API-Key"] = self.api_key

        sanitized_headers = dict(headers)
        if "X-API-Key" in sanitized_headers:
            sanitized_headers["X-API-Key"] = "***"

        logger.debug("Zero request %s %s headers=%s", method, url, sanitized_headers)
        if kwargs.get("json") is not None:
            logger.debug("Zero request payload=%s", kwargs["json"])

        response = self.session.request(
            method=method,
            url=url,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        preview = response.text[:500]
        logger.debug("Zero response %s %s body=%s", response.status_code, url, preview)

        if response.status_code >= 400:
            raise ZeroAPIError(response.status_code, response.reason or "request failed", preview)

        try:
            data = response.json()
        except ValueError:
            data = {"raw_text": response.text}
        return data, response

    @staticmethod
    def _extract_items(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "results", "data", "list", "rows"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _has_next_page(data: Any, current_page: int) -> bool:
        if not isinstance(data, dict):
            return False
        page = data.get("page") or current_page
        total_pages = data.get("total_pages")
        if isinstance(total_pages, int):
            return page < total_pages
        total = data.get("total")
        page_size = data.get("page_size")
        if isinstance(total, int) and isinstance(page_size, int) and page_size > 0:
            return page * page_size < total
        items = ZeroClient._extract_items(data)
        return bool(items) and len(items) >= int(data.get("page_size") or 50)
