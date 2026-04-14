"""Topology edge inference engine.

Infers network edges between devices by analysing their parsed topology
data (interfaces, routes, VPN peers).  Three inference methods in
priority order:

1. Same-subnet matching — two device interfaces share a network
2. VPN peer matching — a peer IP matches another device's interface IP
3. Default gateway matching — a route gateway matches another device's interface
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from backend.core.config_audit.parsers.base import InterfaceInfo, TopologyData


@dataclass
class DeviceTopology:
    """Topology data associated with a specific device/target."""
    device_id: str
    hostname: str | None
    platform: str
    data: TopologyData


@dataclass
class InferredEdge:
    """An inferred network edge between two devices."""
    source_id: str
    target_id: str
    source_interface: str | None = None
    target_interface: str | None = None
    link_type: str = "subnet"  # "subnet", "vpn", "gateway"
    shared_network: str | None = None


def infer_edges(devices: list[DeviceTopology]) -> list[InferredEdge]:
    """Infer all edges between the given devices.

    Returns a deduplicated list of InferredEdge, preferring the most
    specific inference method (subnet > vpn > gateway).
    """
    edges: list[InferredEdge] = []
    seen: set[tuple[str, str]] = set()  # (min_id, max_id) for dedup

    # Build IP -> (device_id, interface_name) index
    ip_index: dict[str, list[tuple[str, str]]] = {}
    for dev in devices:
        for iface in dev.data.interfaces:
            if iface.ip:
                ip_index.setdefault(iface.ip, []).append(
                    (dev.device_id, iface.name)
                )

    # 1. Same-subnet matching
    iface_networks: list[tuple[str, str, ipaddress.IPv4Network]] = []
    for dev in devices:
        for iface in dev.data.interfaces:
            if iface.ip and iface.mask:
                try:
                    net = ipaddress.IPv4Network(
                        f"{iface.ip}/{iface.mask}", strict=False
                    )
                    iface_networks.append((dev.device_id, iface.name, net))
                except ValueError:
                    continue

    for i, (dev_a, iface_a, net_a) in enumerate(iface_networks):
        for dev_b, iface_b, net_b in iface_networks[i + 1:]:
            if dev_a == dev_b:
                continue
            if net_a.overlaps(net_b):
                key = (min(dev_a, dev_b), max(dev_a, dev_b))
                if key not in seen:
                    seen.add(key)
                    edges.append(InferredEdge(
                        source_id=dev_a,
                        target_id=dev_b,
                        source_interface=iface_a,
                        target_interface=iface_b,
                        link_type="subnet",
                        shared_network=str(net_a),
                    ))

    # 2. VPN peer matching
    for dev in devices:
        for peer_ip in dev.data.vpn_peers:
            if peer_ip in ip_index:
                for other_id, other_iface in ip_index[peer_ip]:
                    if other_id == dev.device_id:
                        continue
                    key = (min(dev.device_id, other_id), max(dev.device_id, other_id))
                    if key not in seen:
                        seen.add(key)
                        edges.append(InferredEdge(
                            source_id=dev.device_id,
                            target_id=other_id,
                            target_interface=other_iface,
                            link_type="vpn",
                        ))

    # 3. Default gateway matching
    for dev in devices:
        for route in dev.data.routes:
            if route.gateway and route.gateway in ip_index:
                for other_id, other_iface in ip_index[route.gateway]:
                    if other_id == dev.device_id:
                        continue
                    key = (min(dev.device_id, other_id), max(dev.device_id, other_id))
                    if key not in seen:
                        seen.add(key)
                        edges.append(InferredEdge(
                            source_id=dev.device_id,
                            target_id=other_id,
                            source_interface=route.interface,
                            target_interface=other_iface,
                            link_type="gateway",
                        ))

    return edges


def build_topology_graph(
    devices: list[DeviceTopology],
) -> dict:
    """Build a complete topology graph dict with nodes and inferred edges.

    Returns ``{"nodes": [...], "edges": [...]}``.
    """
    nodes = []
    for dev in devices:
        interfaces = [
            {
                "name": i.name,
                "ip": i.ip,
                "mask": i.mask,
                "status": i.status,
                "description": i.description,
            }
            for i in dev.data.interfaces
        ]
        routes_list = [
            {
                "network": r.network,
                "mask": r.mask,
                "gateway": r.gateway,
                "interface": r.interface,
            }
            for r in dev.data.routes
        ]
        nodes.append({
            "id": dev.device_id,
            "hostname": dev.hostname,
            "platform": dev.platform,
            "interfaces": interfaces,
            "routes": routes_list,
            "vpn_peers": dev.data.vpn_peers,
        })

    inferred = infer_edges(devices)
    edge_list = [
        {
            "id": f"{e.source_id}-{e.target_id}",
            "source": e.source_id,
            "target": e.target_id,
            "source_interface": e.source_interface,
            "target_interface": e.target_interface,
            "link_type": e.link_type,
            "shared_network": e.shared_network,
        }
        for e in inferred
    ]

    return {"nodes": nodes, "edges": edge_list}
