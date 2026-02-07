"""Abstract base connector and shared data-classes for network scan engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandResult:
    """Structured result returned by every connector's ``execute`` method."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time_ms: int = 0


class BaseConnector(ABC):
    """Common interface that every target-specific connector must implement."""

    @abstractmethod
    async def connect(self, target: Any) -> bool:
        """Establish a connection to *target*.

        Parameters
        ----------
        target:
            A ``Target`` model instance (or dict-like) that carries host,
            port, credentials, and any connector-specific extras.

        Returns
        -------
        bool
            ``True`` when the connection is established successfully.

        Raises
        ------
        ConnectionError
            When the connection cannot be established.
        """

    @abstractmethod
    async def execute(self, command: str, timeout: int = 30) -> CommandResult:
        """Execute a single command on the connected target.

        Parameters
        ----------
        command:
            The shell / SQL / CLI command string to run.
        timeout:
            Maximum seconds to wait for the command to complete.

        Returns
        -------
        CommandResult
        """

    @abstractmethod
    async def get_system_info(self) -> dict:
        """Collect basic system information from the target.

        Returns
        -------
        dict
            Keys should include items like ``hostname``, ``os``,
            ``os_version``, ``ip``, ``architecture``, etc.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection cleanly."""

    # ---- context-manager helpers ----
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
        return False
