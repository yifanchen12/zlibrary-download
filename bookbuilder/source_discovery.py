from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

from .config import normalize_base_url


SOURCE_REGISTRY_URL = (
    "https://raw.githubusercontent.com/yifanchen12/zlibrary-download/main/source_registry.json"
)
SOURCE_CHECK_INTERVAL = 6 * 60 * 60
MAX_MANIFEST_BYTES = 16 * 1024
_MANAGED_HOST = re.compile(r"(?:[a-z0-9-]+\.)*z-library\.[a-z]{2,24}", re.IGNORECASE)


class SourceDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceDiscoveryResult:
    current_url: str
    preferred_url: str
    changed: bool
    checked_at: float
    registry_updated_at: str
    managed_source: bool = True


def managed_source_origin(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not _MANAGED_HOST.fullmatch(host)
    ):
        return None
    return f"https://{host}"


def preferred_url_from_manifest(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SourceDiscoveryError("入口清单格式或版本无效。")
    value = payload.get("preferred_base_url")
    if not isinstance(value, str):
        raise SourceDiscoveryError("入口清单缺少 preferred_base_url。")
    parsed = urlsplit(value.strip())
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SourceDiscoveryError("入口清单中的地址必须是 HTTPS 站点根地址。")
    preferred = managed_source_origin(value)
    if preferred is None:
        raise SourceDiscoveryError("入口清单中的地址未通过安全校验。")
    updated_at = payload.get("updated_at", "")
    return preferred, updated_at if isinstance(updated_at, str) else ""


def discover_preferred_source(current_url: str, timeout: float = 8.0) -> SourceDiscoveryResult:
    current = normalize_base_url(current_url)
    if managed_source_origin(current) is None:
        return SourceDiscoveryResult(current, current, False, time.time(), "", managed_source=False)
    try:
        response = requests.get(
            SOURCE_REGISTRY_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "AuthorizedBookBuilder/source-discovery",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        if len(response.content) > MAX_MANIFEST_BYTES:
            raise SourceDiscoveryError("入口清单超过允许大小。")
        preferred, updated_at = preferred_url_from_manifest(response.json())
    except SourceDiscoveryError:
        raise
    except (requests.RequestException, ValueError) as error:
        raise SourceDiscoveryError("暂时无法读取远程入口清单。") from error
    return SourceDiscoveryResult(
        current_url=current,
        preferred_url=preferred,
        changed=current != preferred,
        checked_at=time.time(),
        registry_updated_at=updated_at,
    )


def redirected_managed_source(current_url: str, navigated_url: str) -> str | None:
    current = managed_source_origin(current_url)
    redirected = managed_source_origin(navigated_url)
    if current is None or redirected is None or current == redirected:
        return None
    return redirected


def source_check_due(last_checked_at: float, now: float | None = None) -> bool:
    current_time = time.time() if now is None else now
    return last_checked_at <= 0 or current_time - last_checked_at >= SOURCE_CHECK_INTERVAL
