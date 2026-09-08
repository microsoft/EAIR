"""Communication layer: message schema and bus."""

from comms.schema import Message, MessageType, SenderRole
from comms.bus import MessageBus

__all__ = ["Message", "MessageType", "SenderRole", "MessageBus"]
