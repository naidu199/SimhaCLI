from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

@dataclass
class AgentEventType(str, Enum):
    #Agent lifecycle events
	AGENT_START = "agent_started"
	AGENT_END = "agent_ended"
	AGENT_ERROR = "agent_error"

 	# Task-related events
	TEXT_DELTA = "text_delta"
	TEXT_COMPLETE = "text_complete"


@dataclass
class AgentEvent:
	type: AgentEventType
	data: dict[str, Any ] = field(default_factory=dict)

	@classmethod
	def agent_started(cls, message: str) -> AgentEvent:
		return cls(type=AgentEventType.AGENT_START, data={"message": message},)
