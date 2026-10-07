"""Headless SimhaCLI backend (``simhacli serve``) for editor integrations."""

from server.agent_server import PROTOCOL_VERSION, AgentServer, run_server

__all__ = ["PROTOCOL_VERSION", "AgentServer", "run_server"]
