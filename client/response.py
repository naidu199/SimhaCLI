from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


@dataclass
class TextDelta: #Represents a chunk of text received from the streaming response
	content: str
	is_final: bool = False
	def __str__(self) -> str:
		return self.content

@dataclass
class TokenUsage: #Tracks token usage statistics
	prompt_tokens: int = 0
	completion_tokens: int = 0
	total_tokens: int = 0
	cached_tokens: int = 0

	#To add two TokenUsage objects together
	def __add__(self, other: TokenUsage) -> TokenUsage:
		return TokenUsage(
			prompt_tokens=self.prompt_tokens + other.prompt_tokens,
			completion_tokens=self.completion_tokens + other.completion_tokens,
			total_tokens=self.total_tokens + other.total_tokens,
			cached_tokens=self.cached_tokens + other.cached_tokens,
		)

@dataclass
class EventType(str, Enum): #Types of events that can occur during streaming
	TEXT_DELTA = "text_delta"
	MESSAGE_COMPLETE = "message_complete"
	ERROR="error"

@dataclass
class StreamEvent: #Represents an event during streaming
	type: EventType
	text_delta: TextDelta | None = None
	error: str | None = None
	final_reason: str | None = None
	usage: TokenUsage | None = None
