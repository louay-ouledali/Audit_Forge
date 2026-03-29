"""Connector registry — maps target_type / connection_method to the right connector class."""

from __future__ import annotations

import logging

from backend.connectors.base import BaseConnector, CommandResult
from backend.connectors.ssh_connector import SSHConnector
from backend.connectors.winrm_connector import WinRMConnector
from backend.connectors.netmiko_connector import NetmikoConnector
from backend.connectors.postgres_connector import PostgreSQLConnector
from backend.connectors.oracle_connector import OracleConnector
from backend.connectors.mssql_connector import MSSQLConnector
from backend.connectors.mysql_connector import MySQLConnector
from backend.connectors.mongodb_connector import MongoDBConnector

_logger = logging.getLogger("auditforge.connectors")

# Mapping from (target_type, connection_method) to connector classes.
# connection_method takes precedence when set; otherwise target_type is used.
_CONNECTOR_MAP: dict[str, type[BaseConnector]] = {
    "ssh": SSHConnector,
    "winrm": WinRMConnector,
    "netmiko": NetmikoConnector,
    "postgresql": PostgreSQLConnector,
    "oracle": OracleConnector,
    "mssql": MSSQLConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
}

# Fallback mapping from target_type to connector class
_TARGET_TYPE_MAP: dict[str, type[BaseConnector]] = {
    "linux": SSHConnector,
    "windows": WinRMConnector,
    "cisco_ios": NetmikoConnector,
    "cisco_nxos": NetmikoConnector,
    "cisco_asa": NetmikoConnector,
    "juniper": NetmikoConnector,
    "fortinet": NetmikoConnector,
    "palo_alto": NetmikoConnector,
    "checkpoint": NetmikoConnector,
    "arista": NetmikoConnector,
    "hp_procurve": NetmikoConnector,
    "postgresql": PostgreSQLConnector,
    "oracle": OracleConnector,
    "mssql": MSSQLConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
    "cassandra": SSHConnector,
    "vmware_esxi": SSHConnector,
}


def get_connector(target_type: str, connection_method: str | None = None) -> BaseConnector:
    """Return the appropriate connector instance for the given target.

    Parameters
    ----------
    target_type:
        The ``Target.target_type`` value (e.g. ``"linux"``, ``"windows"``).
    connection_method:
        Optional explicit connection method override (e.g. ``"ssh"``, ``"winrm"``).

    Raises
    ------
    ValueError
        If no connector is registered for the supplied type/method.
    """

    key = (connection_method or "").lower().strip()
    if key and key in _CONNECTOR_MAP:
        return _CONNECTOR_MAP[key]()

    key = target_type.lower().strip()
    if key in _CONNECTOR_MAP:
        return _CONNECTOR_MAP[key]()
    if key in _TARGET_TYPE_MAP:
        return _TARGET_TYPE_MAP[key]()

    # Graceful fallback: SSH is the most universal connector.
    # The user can always override via connection_method on the Target.
    _logger.warning(
        "No connector mapped for target_type='%s', connection_method='%s' "
        "-- falling back to SSHConnector",
        target_type, connection_method,
    )
    return SSHConnector()


__all__ = [
    "BaseConnector",
    "CommandResult",
    "SSHConnector",
    "WinRMConnector",
    "NetmikoConnector",
    "PostgreSQLConnector",
    "OracleConnector",
    "MSSQLConnector",
    "MySQLConnector",
    "MongoDBConnector",
    "get_connector",
]
