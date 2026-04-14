"""Auto-pull running configuration from a live network device."""

from __future__ import annotations

import logging

from backend.connectors.base import BaseConnector

logger = logging.getLogger("auditforge.config_audit.puller")

# Map target_type to the command that retrieves the full running config
_PULL_COMMANDS: dict[str, str] = {
    "cisco_ios": "show running-config",
    "cisco_asa": "show running-config",
    "cisco_nxos": "show running-config",
    "arista": "show running-config",
    "hp_procurve": "show running-config",
    "fortinet": "show full-configuration",
    "palo_alto": "show config running",
    "juniper": "show configuration",
    "checkpoint": "show configuration",
    "pfsense": "cat /cf/conf/config.xml",
}

# Timeout for config pull (large configs can be slow)
_PULL_TIMEOUT = 60


async def pull_config(connector: BaseConnector, target_type: str) -> tuple[str, str]:
    """Pull the running configuration from a live device.

    Parameters
    ----------
    connector:
        An already-connected ``BaseConnector`` instance.
    target_type:
        Normalised target type string (e.g. ``"cisco_ios"``).

    Returns
    -------
    (raw_config, command_used)
        The full config text and the command that was used.

    Raises
    ------
    RuntimeError
        If the pull fails or returns empty output.
    """
    cmd = _PULL_COMMANDS.get(target_type.lower().strip())
    if cmd is None:
        raise RuntimeError(
            f"No config pull command defined for target_type '{target_type}'"
        )

    logger.info("Pulling config from %s target via '%s'", target_type, cmd)
    result = await connector.execute(cmd, timeout=_PULL_TIMEOUT)

    if result.exit_code != 0 and not result.stdout.strip():
        raise RuntimeError(
            f"Config pull failed (exit_code={result.exit_code}): {result.stderr}"
        )

    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError("Config pull returned empty output")

    logger.info("Config pulled successfully: %d lines", len(raw.splitlines()))
    return raw, cmd
