"""
AD Discovery API Endpoints
============================
Provides endpoints for Active Directory computer discovery, WinRM checks,
bulk target creation, and remote WinRM enablement.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.connectors.ad_connector import (
    ADComputer,
    async_check_winrm,
    async_discover_computers,
    async_enable_winrm_via_wmi,
    async_test_connection,
    generate_enable_winrm_script,
    match_benchmark,
    match_os_to_platform,
)
from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.models.client import Client
from backend.models.mission import Mission
from backend.models.target import Target
from backend.utils.encryption import decrypt_value, encrypt_value  # UNUSED: 'encrypt_value' — safe to remove

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ad", tags=["ad-discovery"])


# Request / Response Schemas


class ADTestConnectionRequest(BaseModel):
    client_id: int
    # Override credentials (optional — falls back to client's stored creds)
    dc_host: str | None = None
    domain: str | None = None
    username: str | None = None
    password: str | None = None
    use_ssl: bool = True


class ADDiscoverRequest(BaseModel):
    client_id: int
    dc_host: str | None = None
    domain: str | None = None
    username: str | None = None
    password: str | None = None
    use_ssl: bool = True
    ou_filter: str | None = None
    resolve_dns: bool = True


class ADCheckWinRMRequest(BaseModel):
    hosts: list[str]
    timeout: float = 3.0


class ADEnableWinRMRequest(BaseModel):
    client_id: int
    target_hosts: list[str]


class ADBulkCreateRequest(BaseModel):
    client_id: int
    mission_id: int
    computers: list[dict[str, Any]]
    auto_scan: bool = False


class ADComputerResponse(BaseModel):
    cn: str
    dns_hostname: str | None = None
    ip_address: str | None = None
    operating_system: str | None = None
    os_version: str | None = None
    distinguished_name: str | None = None
    when_created: str | None = None
    last_logon: str | None = None
    enabled: bool = True
    ou_path: str | None = None
    # Enriched fields
    target_type: str | None = None
    platform_subtype: str | None = None
    os_confidence: str | None = None
    matched_benchmark_id: int | None = None
    matched_benchmark_name: str | None = None


# Helpers


def _get_client_ad_creds(
    db: Session,
    client_id: int,
    override_dc: str | None = None,
    override_domain: str | None = None,
    override_username: str | None = None,
    override_password: str | None = None,
    override_ssl: bool | None = None,
    override_ou: str | None = None,
) -> dict[str, Any]:
    """Get AD credentials, preferring overrides then falling back to client's stored creds."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    dc_host = override_dc or client.ad_dc_host
    domain = override_domain or client.ad_domain
    username = override_username or client.ad_username
    use_ssl = override_ssl if override_ssl is not None else bool(client.ad_use_ssl)
    ou_filter = override_ou or client.ad_base_ou

    # Password: use override if provided, otherwise decrypt stored
    password = override_password
    if not password and client.ad_password_encrypted:
        try:
            password = decrypt_value(client.ad_password_encrypted, settings.effective_encryption_key)
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to decrypt stored AD password")

    if not all([dc_host, domain, username, password]):
        raise HTTPException(
            status_code=400,
            detail="AD credentials incomplete. Provide dc_host, domain, username, and password.",
        )

    return {
        "dc_host": dc_host,
        "domain": domain,
        "username": username,
        "password": password,
        "use_ssl": use_ssl,
        "ou_filter": ou_filter,
        "client": client,
    }


def _get_benchmarks_for_matching(db: Session) -> list[dict[str, Any]]:
    """Get all benchmarks for OS-to-benchmark matching."""
    benchmarks = db.query(Benchmark).filter(Benchmark.status == "active").all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "platform": b.platform,
            "platform_family": b.platform_family,
            "version": b.version,
            "is_ready": b.is_ready,
        }
        for b in benchmarks
    ]


def _computer_to_response(
    comp: ADComputer,
    benchmarks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert an ADComputer to an API response dict with benchmark matching."""
    platform_info = match_os_to_platform(comp.operating_system)
    bm = match_benchmark(comp.operating_system, benchmarks)

    return {
        "cn": comp.cn,
        "dns_hostname": comp.dns_hostname,
        "ip_address": comp.ip_address,
        "operating_system": comp.operating_system,
        "os_version": comp.os_version,
        "distinguished_name": comp.distinguished_name,
        "when_created": comp.when_created.isoformat() if comp.when_created else None,
        "last_logon": comp.last_logon.isoformat() if comp.last_logon else None,
        "enabled": comp.enabled,
        "ou_path": comp.ou_path,
        "target_type": platform_info["target_type"],
        "platform_subtype": platform_info["platform_subtype"],
        "os_confidence": platform_info["confidence"],
        "matched_benchmark_id": bm["id"] if bm else None,
        "matched_benchmark_name": bm["name"] if bm else None,
    }


# Endpoints


@router.post("/test-connection")
async def ad_test_connection(
    req: ADTestConnectionRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Test connection to an AD domain controller."""
    creds = _get_client_ad_creds(
        db, req.client_id,
        override_dc=req.dc_host,
        override_domain=req.domain,
        override_username=req.username,
        override_password=req.password,
        override_ssl=req.use_ssl,
    )

    result = await async_test_connection(
        dc_host=creds["dc_host"],
        domain=creds["domain"],
        username=creds["username"],
        password=creds["password"],
        use_ssl=creds["use_ssl"],
    )

    if not result.success:
        return {
            "success": False,
            "error": result.error,
        }

    return {
        "success": True,
        "domain_name": result.domain_name,
        "domain_dn": result.domain_dn,
        "dc_hostname": result.dc_hostname,
        "forest_name": result.forest_name,
        "computer_count": result.computer_count,
    }


@router.post("/discover")
async def ad_discover_computers(
    req: ADDiscoverRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Discover computer objects in Active Directory."""
    creds = _get_client_ad_creds(
        db, req.client_id,
        override_dc=req.dc_host,
        override_domain=req.domain,
        override_username=req.username,
        override_password=req.password,
        override_ssl=req.use_ssl,
        override_ou=req.ou_filter,
    )

    result = await async_discover_computers(
        dc_host=creds["dc_host"],
        domain=creds["domain"],
        username=creds["username"],
        password=creds["password"],
        use_ssl=creds["use_ssl"],
        ou_filter=creds["ou_filter"],
        resolve_dns=req.resolve_dns,
    )

    if not result.success:
        return {
            "success": False,
            "error": result.error,
            "computers": [],
            "total": 0,
        }

    # Enrich with benchmark matching
    benchmarks = _get_benchmarks_for_matching(db)
    computers = [_computer_to_response(c, benchmarks) for c in result.computers]

    return {
        "success": True,
        "computers": computers,
        "total": result.total_found,
    }


@router.post("/check-winrm")
async def ad_check_winrm(req: ADCheckWinRMRequest) -> dict:
    """Check WinRM availability on multiple hosts."""
    tasks = [async_check_winrm(host, req.timeout) for host in req.hosts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    host_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            host_results.append({
                "host": req.hosts[i],
                "winrm_http": False,
                "winrm_https": False,
                "winrm_available": False,
                "error": str(result),
            })
        else:
            host_results.append(result)

    available = sum(1 for r in host_results if r.get("winrm_available"))
    return {
        "results": host_results,
        "total": len(host_results),
        "available": available,
    }


@router.post("/enable-winrm")
async def ad_enable_winrm(
    req: ADEnableWinRMRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Attempt to enable WinRM on target machines via WMI through the DC.

    Falls back to generating a PowerShell script if direct enablement fails.
    """
    creds = _get_client_ad_creds(db, req.client_id)

    results = []
    for host in req.target_hosts:
        result = await async_enable_winrm_via_wmi(
            target_host=host,
            dc_host=creds["dc_host"],
            domain=creds["domain"],
            username=creds["username"],
            password=creds["password"],
        )
        results.append({"host": host, **result})

    successes = sum(1 for r in results if r.get("success"))

    # If any failed, also provide a bulk fallback script
    failed_hosts = [r["host"] for r in results if not r.get("success")]
    fallback_script = None
    if failed_hosts:
        fallback_script = generate_enable_winrm_script(
            failed_hosts, creds["domain"], creds["username"]
        )

    return {
        "results": results,
        "total": len(results),
        "successes": successes,
        "fallback_script": fallback_script,
    }


@router.post("/bulk-create-targets")
async def ad_bulk_create_targets(
    req: ADBulkCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Create targets from discovered AD computers and assign to a mission."""
    # Validate mission and client
    mission = db.query(Mission).filter(Mission.id == req.mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    client = db.query(Client).filter(Client.id == req.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if mission.client_id != req.client_id:
        raise HTTPException(status_code=400, detail="Mission does not belong to this client")

    # Get benchmarks for matching
    benchmarks = _get_benchmarks_for_matching(db)

    created = []
    skipped = []
    errors = []

    for comp_data in req.computers:
        try:
            hostname = comp_data.get("dns_hostname") or comp_data.get("cn")
            ip_address = comp_data.get("ip_address")
            os_str = comp_data.get("operating_system")

            # Check for existing target with same hostname or IP
            existing = None
            if hostname:
                existing = db.query(Target).filter(
                    Target.client_id == req.client_id,
                    Target.hostname == hostname,
                ).first()
            if not existing and ip_address:
                existing = db.query(Target).filter(
                    Target.client_id == req.client_id,
                    Target.ip_address == ip_address,
                ).first()

            if existing:
                # Just assign to mission if not already
                if mission not in existing.missions:
                    existing.missions.append(mission)
                skipped.append({
                    "hostname": hostname,
                    "reason": "already_exists",
                    "target_id": existing.id,
                })
                continue

            # Determine target type and benchmark
            platform_info = match_os_to_platform(os_str)
            target_type = platform_info["target_type"] or "windows"
            platform_subtype = platform_info["platform_subtype"]

            # Match benchmark
            bm = match_benchmark(os_str, benchmarks)
            benchmark_id = comp_data.get("matched_benchmark_id") or (bm["id"] if bm else None)

            # Determine connection method
            connection_method = "winrm" if target_type == "windows" else "ssh"
            port = 5985 if connection_method == "winrm" else 22

            # Use AD credentials for WinRM targets
            ssh_username = None
            ssh_password_encrypted = None
            if connection_method == "winrm" and client.ad_username and client.ad_password_encrypted:
                ssh_username = client.ad_username
                ssh_password_encrypted = client.ad_password_encrypted

            target = Target(
                client_id=req.client_id,
                hostname=hostname,
                ip_address=ip_address,
                target_type=target_type,
                os_details=os_str,
                connection_method=connection_method,
                port=port,
                platform_subtype=platform_subtype,
                default_benchmark_id=benchmark_id,
                ssh_username=ssh_username,
                ssh_password_encrypted=ssh_password_encrypted,
                connection_status="untested",
                notes=f"Discovered via AD: {comp_data.get('distinguished_name', '')}",
            )
            db.add(target)
            db.flush()  # Get the ID

            # Assign to mission
            target.missions.append(mission)

            created.append({
                "target_id": target.id,
                "hostname": hostname,
                "ip_address": ip_address,
                "target_type": target_type,
                "benchmark_id": benchmark_id,
                "benchmark_name": bm["name"] if bm else None,
            })

        except Exception as e:
            logger.error("Failed to create target from AD computer %s: %s", comp_data.get("cn"), e)
            errors.append({
                "hostname": comp_data.get("dns_hostname") or comp_data.get("cn"),
                "error": str(e),
            })

    db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total_created": len(created),
        "total_skipped": len(skipped),
        "total_errors": len(errors),
    }


@router.post("/generate-winrm-script")
async def ad_generate_winrm_script(
    req: ADEnableWinRMRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Generate a PowerShell script to enable WinRM on targets (no direct execution)."""
    creds = _get_client_ad_creds(db, req.client_id)
    script = generate_enable_winrm_script(
        req.target_hosts, creds["domain"], creds["username"]
    )
    return {"script": script}
