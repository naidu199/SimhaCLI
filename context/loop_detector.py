from collections import deque
from typing import Any


class LoopDetector:
    def __init__(self):
        self.max_exact_repeats = 3
        self.max_cycle_length = 3
        self.max_consecutive_failures = 3  # Stop after 3 consecutive failed tool calls
        self._history: deque[str] = deque(maxlen=20)
        self._consecutive_failures = 0
        self._last_failed_tool_signature: str | None = (
            None  # Track tool + params signature
        )

    def record_action(self, action_type: str, **details: Any):
        output = [action_type]

        if action_type == "tool_call":
            tool_name = details.get("tool_name", "")
            output.append(tool_name)
            args = details.get("args", {})

            if isinstance(args, dict):
                for k in sorted(args.keys()):
                    output.append(f"{k}={str(args[k])}")
        elif action_type == "response":
            output.append(details.get("text", ""))
            # Reset failure counter on successful response
            self._consecutive_failures = 0
            self._last_failed_tool_signature = None

        signature = "|".join(output)
        self._history.append(signature)

    def record_tool_failure(self, tool_name: str, args: dict[str, Any]) -> None:
        """Record a tool call failure. Only counts as consecutive if same tool with same/similar params fails."""
        # Create a signature that includes tool name and parameters
        signature_parts = [tool_name]
        if isinstance(args, dict):
            for k in sorted(args.keys()):
                signature_parts.append(f"{k}={str(args[k])}")
        current_signature = "|".join(signature_parts)

        # Only increment if the same tool with same parameters fails again
        if self._last_failed_tool_signature == current_signature:
            self._consecutive_failures += 1
        else:
            # Different parameters or first failure - reset counter
            self._consecutive_failures = 1
            self._last_failed_tool_signature = current_signature

    def check_for_loop(self) -> str | None:
        # Check for consecutive failures first
        if self._consecutive_failures >= self.max_consecutive_failures:
            tool_name = (
                self._last_failed_tool_signature.split("|")[0]
                if self._last_failed_tool_signature
                else "unknown"
            )
            return f"Tool '{tool_name}' failed {self._consecutive_failures} times consecutively with the same parameters. Stopping to prevent infinite loop."

        if len(self._history) < 2:
            return None

        if len(self._history) >= self.max_exact_repeats:
            recent = list(self._history)[-self.max_exact_repeats :]
            if len(set(recent)) == 1:
                return f"Same action repeated {self.max_exact_repeats} times"

        if len(self._history) >= self.max_cycle_length * 2:
            history = list(self._history)

            # Check for cycles with patterns of increasing length in the recent history
            for cycle_len in range(
                2, min(self.max_cycle_length + 1, len(history) // 2 + 1)
            ):
                recent = history[-cycle_len * 2 :]
                if recent[:cycle_len] == recent[cycle_len:]:
                    return f"Detected repeating cycle of length {cycle_len}"

        return None

    def clear(self) -> None:
        self._history.clear()
        self._consecutive_failures = 0
        self._last_failed_tool_signature = None
