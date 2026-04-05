"""HTTP client wrapper with auth header injection."""
from __future__ import annotations

from typing import Any

import httpx

from cli.config import get_server_url, get_token


def _client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        base_url=get_server_url() + "/api",
        headers={"Authorization": f"Bearer {get_token()}"},
        timeout=timeout,
    )


def get(path: str, **params: Any) -> Any:
    with _client() as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        return r.json()


def post(path: str, json: Any = None, **kwargs: Any) -> Any:
    with _client() as c:
        r = c.post(path, json=json, **kwargs)
        r.raise_for_status()
        return r.json()


def put(path: str, json: Any = None) -> Any:
    with _client() as c:
        r = c.put(path, json=json)
        r.raise_for_status()
        return r.json()


def delete(path: str) -> Any:
    with _client() as c:
        r = c.delete(path)
        r.raise_for_status()
        return r.json()


def stream_download(path: str, dest: str) -> str:
    """Download a file to disk, return the file path."""
    import os
    with _client(timeout=300.0) as c:
        with c.stream("GET", path) as r:
            r.raise_for_status()
            # Try to get filename from content-disposition
            cd = r.headers.get("content-disposition", "")
            if "filename=" in cd:
                fname = cd.split("filename=")[-1].strip('"').strip("'")
            else:
                fname = path.split("/")[-1]
            out_path = os.path.join(dest, fname)
            with open(out_path, "wb") as f:
                for chunk in r.iter_bytes(8192):
                    f.write(chunk)
    return out_path
