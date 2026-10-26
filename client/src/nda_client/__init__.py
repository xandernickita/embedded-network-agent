"""Laptop-side client for the Embedded Network Diagnostics Agent (see docs/PROTOCOL.md)."""

from .client import AgentClient, AgentConnectionError, AgentError

__all__ = ["AgentClient", "AgentConnectionError", "AgentError"]
__version__ = "0.1.0"
