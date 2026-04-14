from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.mission import Mission
from backend.models.mission_topology import MissionTopology
from backend.schemas.topology import (
    TopologyEdgeCreate,
    TopologyLayoutUpdate,
    TopologyResponse,
)

router = APIRouter(tags=["topology"])
logger = logging.getLogger("auditforge.api.topology")

EMPTY_GRAPH: dict = {"nodes": [], "edges": []}


# ── helpers ──────────────────────────────────────────────────────

def _get_mission_or_404(mission_id: int, db: Session) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _to_response(topo: MissionTopology) -> TopologyResponse:
    return TopologyResponse(
        mission_id=topo.mission_id,
        graph=json.loads(topo.graph_json),
        last_rebuilt_at=topo.last_rebuilt_at,
        has_user_layout=topo.user_layout_json is not None,
    )


def _empty_response(mission_id: int) -> TopologyResponse:
    return TopologyResponse(
        mission_id=mission_id,
        graph=EMPTY_GRAPH,
        last_rebuilt_at=None,
        has_user_layout=False,
    )


# ── 1. GET topology ─────────────────────────────────────────────

@router.get("/missions/{mission_id}/topology", response_model=TopologyResponse)
def get_topology(mission_id: int, db: Session = Depends(get_db)):
    """Return the topology for a mission. If none exists, return an empty graph."""
    _get_mission_or_404(mission_id, db)
    topo = db.query(MissionTopology).filter(
        MissionTopology.mission_id == mission_id,
    ).first()
    if not topo:
        return _empty_response(mission_id)
    return _to_response(topo)


# ── 2. POST rebuild ─────────────────────────────────────────────

@router.post("/missions/{mission_id}/topology/rebuild", response_model=TopologyResponse)
def rebuild_topology(mission_id: int, db: Session = Depends(get_db)):
    """Rebuild topology from config snapshots of all mission targets."""
    from backend.core.config_audit.detect import detect_config_format
    from backend.core.config_audit.parsers import get_parser
    from backend.core.config_audit.topology import DeviceTopology, build_topology_graph

    mission = _get_mission_or_404(mission_id, db)

    devices: list[DeviceTopology] = []

    for target in mission.targets:
        if not target.config_snapshots:
            continue

        latest_snap = sorted(
            target.config_snapshots,
            key=lambda s: s.snapshot_at,
            reverse=True,
        )[0]

        fmt = detect_config_format(latest_snap.raw_config)
        parser = get_parser(fmt)
        parsed = parser.parse(latest_snap.raw_config)
        topo_data = parser.extract_topology(parsed)

        devices.append(DeviceTopology(
            device_id=str(target.id),
            hostname=parsed.hostname or target.hostname,
            platform=fmt,
            data=topo_data,
        ))

    graph = build_topology_graph(devices)
    now = datetime.now(timezone.utc)

    topo = db.query(MissionTopology).filter(
        MissionTopology.mission_id == mission_id,
    ).first()

    if topo:
        topo.graph_json = json.dumps(graph)
        topo.auto_layout_json = None
        topo.last_rebuilt_at = now
    else:
        topo = MissionTopology(
            mission_id=mission_id,
            graph_json=json.dumps(graph),
            last_rebuilt_at=now,
        )
        db.add(topo)

    db.commit()
    db.refresh(topo)
    logger.info("Rebuilt topology for mission %d: %d nodes", mission_id, len(nodes))
    return _to_response(topo)


# ── 3. PUT layout ───────────────────────────────────────────────

@router.put("/missions/{mission_id}/topology/layout", response_model=TopologyResponse)
def save_layout(
    mission_id: int,
    body: TopologyLayoutUpdate,
    db: Session = Depends(get_db),
):
    """Save user-defined node positions for the topology map."""
    _get_mission_or_404(mission_id, db)
    topo = db.query(MissionTopology).filter(
        MissionTopology.mission_id == mission_id,
    ).first()
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found. Rebuild first.")

    topo.user_layout_json = json.dumps(body.positions)
    db.commit()
    db.refresh(topo)
    return _to_response(topo)


# ── 4. POST add manual edge ─────────────────────────────────────

@router.post("/missions/{mission_id}/topology/edges", response_model=TopologyResponse)
def add_edge(
    mission_id: int,
    body: TopologyEdgeCreate,
    db: Session = Depends(get_db),
):
    """Add a manual edge to the topology graph."""
    _get_mission_or_404(mission_id, db)
    topo = db.query(MissionTopology).filter(
        MissionTopology.mission_id == mission_id,
    ).first()
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found. Rebuild first.")

    graph = json.loads(topo.graph_json)
    edge = {
        "source": body.source,
        "target": body.target,
        "source_interface": body.source_interface,
        "target_interface": body.target_interface,
        "link_type": body.link_type,
    }
    graph.setdefault("edges", []).append(edge)
    topo.graph_json = json.dumps(graph)
    db.commit()
    db.refresh(topo)
    return _to_response(topo)


# ── 5. DELETE remove edge ────────────────────────────────────────

@router.delete("/missions/{mission_id}/topology/edges", response_model=TopologyResponse)
def remove_edge(
    mission_id: int,
    source: str = Query(..., description="Source node ID"),
    target: str = Query(..., description="Target node ID"),
    db: Session = Depends(get_db),
):
    """Remove an edge from the topology graph by source and target."""
    _get_mission_or_404(mission_id, db)
    topo = db.query(MissionTopology).filter(
        MissionTopology.mission_id == mission_id,
    ).first()
    if not topo:
        raise HTTPException(status_code=404, detail="Topology not found. Rebuild first.")

    graph = json.loads(topo.graph_json)
    edges = graph.get("edges", [])
    graph["edges"] = [
        e for e in edges
        if not (e.get("source") == source and e.get("target") == target)
    ]
    topo.graph_json = json.dumps(graph)
    db.commit()
    db.refresh(topo)
    return _to_response(topo)
