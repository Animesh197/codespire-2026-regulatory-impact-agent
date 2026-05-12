from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


def format_api_error(exc: BaseException) -> str:
    """Surface FastAPI `detail` (string or list) in UI-friendly text."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
            d = body.get("detail")
            if isinstance(d, list):
                return "; ".join(str(x) for x in d)
            if isinstance(d, str):
                return d
        except Exception:
            pass
        t = (exc.response.text or "").strip()
        if t:
            return t[:800]
    return str(exc)


def check_health(api_base: str, timeout: float = 5.0) -> bool:
    try:
        r = httpx.get(f"{api_base.rstrip('/')}/health", timeout=timeout)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def upload_documents(
    api_base: str,
    regulation_path: str | Path,
    policy_path: str | Path,
    timeout: float = 120.0,
) -> dict[str, Any]:
    api_base = api_base.rstrip("/")
    reg_path = Path(regulation_path)
    pol_path = Path(policy_path)
    with reg_path.open("rb") as rf, pol_path.open("rb") as pf:
        files = {
            "regulation": (reg_path.name, rf, "application/octet-stream"),
            "company_policy": (pol_path.name, pf, "application/octet-stream"),
        }
        r = httpx.post(f"{api_base}/upload", files=files, timeout=timeout)
    r.raise_for_status()
    return r.json()


def analyze_job(api_base: str, job_id: str, timeout: float = 3600.0) -> dict[str, Any]:
    api_base = api_base.rstrip("/")
    r = httpx.post(
        f"{api_base}/analyze",
        json={"job_id": job_id},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_results(api_base: str, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    api_base = api_base.rstrip("/")
    r = httpx.get(f"{api_base}/results", params={"job_id": job_id}, timeout=timeout)
    r.raise_for_status()
    return r.json()
