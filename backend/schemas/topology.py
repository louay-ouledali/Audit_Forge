from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TopologyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mission_id: int
    graph: dict  # {nodes: [...], edges: [...]}
    last_rebuilt_at: datetime | None = None
    has_user_layout: bool = False


class TopologyLayoutUpdate(BaseModel):
    positions: dict[str, dict[str, float]]  # node_id -> {x, y}


class TopologyEdgeCreate(BaseModel):
    source: str
    target: str
    source_interface: str | None = None
    target_interface: str | None = None
    link_type: str = "manual"
