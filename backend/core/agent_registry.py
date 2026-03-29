"""In-memory registry of live WebSocket-connected agents."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiveAgent:
    agent_id: int
    session_id: int
    websocket: Any  # fastapi.WebSocket
    os_type: str = ""
    hostname: str = ""
    ip_address: str = ""
    connected_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)


_registry: dict[str, LiveAgent] = {}  # token -> LiveAgent
_lock = threading.Lock()


def register(token: str, agent: LiveAgent) -> None:
    with _lock:
        _registry[token] = agent


def unregister(token: str) -> LiveAgent | None:
    with _lock:
        return _registry.pop(token, None)


def get_by_token(token: str) -> LiveAgent | None:
    with _lock:
        return _registry.get(token)


def get_by_session(session_id: int) -> list[LiveAgent]:
    with _lock:
        return [a for a in _registry.values() if a.session_id == session_id]


def get_all() -> list[LiveAgent]:
    with _lock:
        return list(_registry.values())


def update_heartbeat(token: str) -> None:
    with _lock:
        agent = _registry.get(token)
        if agent:
            agent.last_heartbeat = time.time()
