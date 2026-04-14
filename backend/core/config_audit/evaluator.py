"""ConfigEvaluator — sits above the connector layer to intercept rules
answerable from a parsed device configuration."""

from __future__ import annotations

from backend.core.config_audit.parsers.base import BaseConfigParser, ParsedConfigResult


class ConfigEvaluator:
    """Evaluates audit commands against a parsed config file.

    Instantiated once per scan (after config pull/upload succeeds) and
    called for every rule in the execution loop **before** transport
    routing.  If ``try_evaluate`` returns a string, the scan executor
    uses it as simulated output and skips the live connector.
    """

    def __init__(self, parser: BaseConfigParser, parsed: ParsedConfigResult) -> None:
        self._parser = parser
        self._parsed = parsed

    def try_evaluate(self, command: str, transport: str) -> str | None:
        """Attempt to answer *command* from the config.

        Parameters
        ----------
        command:
            The (possibly env-adapted) audit command string.
        transport:
            The command transport tag (``"cli"``, ``"shell"``, ``"sql"``,
            ``"powershell"``).

        Returns
        -------
        str | None
            Simulated command output, or ``None`` if the command cannot
            be answered from config alone.
        """
        # Only CLI and shell commands can potentially be answered from config.
        # SQL and PowerShell commands always need a live connection.
        if transport not in ("cli", "shell"):
            return None

        if not command or not command.strip():
            return None

        return self._parser.simulate(command, self._parsed)

    @property
    def format_id(self) -> str:
        return self._parsed.format_id

    @property
    def hostname(self) -> str | None:
        return self._parsed.hostname
