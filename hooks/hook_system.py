import asyncio
import json
import os
import shlex
import signal
import sys
import tempfile
from typing import Any
from config.config import Config, HookConfig, HookTrigger
from tools.base import ToolResult

# Max size (in bytes) of a single AI_AGENT_* env value; larger values are
# truncated to avoid E2BIG ("Argument list too long") when spawning hooks.
MAX_ENV_VALUE_BYTES = 32 * 1024


def _env_value(value: Any) -> str:
    """Stringify and truncate a value so it is safe to place in os.environ."""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, default=str)
        except (TypeError, ValueError):
            value = str(value)
    # NUL bytes are not allowed in environment values
    value = value.replace("\x00", "")
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) > MAX_ENV_VALUE_BYTES:
        value = encoded[:MAX_ENV_VALUE_BYTES].decode("utf-8", errors="ignore")
    return value


class HookSystem:
    def __init__(self, config: Config):
        self.config = config
        self.hooks: list[HookConfig] = []
        if self.config.hooks_enabled:
            self.hooks = [hook for hook in self.config.hooks if hook.enabled]

    async def execute_hook(self, hook: HookConfig, env: dict[str, str]) -> None:
        try:
            if hook.command:
                # Substitute the documented {file} placeholder (e.g. "black {file}")
                file_path = env.get("AI_AGENT_FILE", "")
                command = hook.command.replace("{file}", shlex.quote(file_path))
                await self._run_command(command, hook.time_out_sec, env)
            else:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False
                ) as f:
                    f.write("#!/bin/bash\n")
                    f.write(hook.script)
                    script_path = f.name
                try:
                    os.chmod(
                        script_path, 0o755
                    )  # Make the script executable 7- means read, write, execute for owner, 5- means read and execute for group and others, 0- means no permissions
                    await self._run_command(script_path, hook.time_out_sec, env)
                finally:
                    os.unlink(script_path)
        except Exception as e:
            print(e)

    async def _run_command(
        self,
        command: str,
        timeout: float,
        env: dict[str, str],
    ) -> None:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.cwd,
            env=env,
            start_new_session=True,
        )

        try:
            await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                # Process already exited between the timeout and the kill
                pass
            await process.wait()

    def _build_env(
        self,
        trigger: HookTrigger,
        tool_name: str | None = None,
        user_message: str | None = None,
        error: Exception | None = None,
        tool_params: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env["AI_AGENT_TRIGGER"] = trigger.value
        env["AI_AGENT_CWD"] = _env_value(str(self.config.cwd))
        env.pop("AI_AGENT_FILE", None)

        if tool_name:
            env["AI_AGENT_TOOL_NAME"] = _env_value(tool_name)

        if user_message:
            env["AI_AGENT_USER_MESSAGE"] = _env_value(user_message)

        if error:
            env["AI_AGENT_ERROR"] = _env_value(str(error))

        if tool_params is not None:
            env["AI_AGENT_TOOL_PARAMS"] = _env_value(tool_params)
            path = tool_params.get("path") if isinstance(tool_params, dict) else None
            if path:
                env["AI_AGENT_FILE"] = _env_value(str(path))

        return env

    async def trigger_before_agent(self, user_input: str) -> None:
        env = self._build_env(
            HookTrigger.BEFORE_AGENT,
            user_message=user_input,
        )

        for hook in self.hooks:
            if hook.trigger == HookTrigger.BEFORE_AGENT:
                await self.execute_hook(hook, env)

    async def trigger_after_agent(
        self,
        user_message: str,
        agent_response: str,
    ) -> None:
        env = self._build_env(
            HookTrigger.AFTER_AGENT,
            user_message=user_message,
        )
        env["AI_AGENT_RESPONSE"] = _env_value(agent_response)

        for hook in self.hooks:
            if hook.trigger == HookTrigger.AFTER_AGENT:
                await self.execute_hook(hook, env)

    async def trigger_before_tool(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
    ) -> None:
        env = self._build_env(
            HookTrigger.BEFORE_TOOL, tool_name=tool_name, tool_params=tool_params
        )

        for hook in self.hooks:
            if hook.trigger == HookTrigger.BEFORE_TOOL:
                await self.execute_hook(hook, env)

    async def trigger_after_tool(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
        tool_result: ToolResult,
    ) -> None:
        env = self._build_env(
            HookTrigger.AFTER_TOOL, tool_name=tool_name, tool_params=tool_params
        )
        env["AI_AGENT_TOOL_RESULT"] = _env_value(tool_result.to_model_output())

        for hook in self.hooks:
            if hook.trigger == HookTrigger.AFTER_TOOL:
                await self.execute_hook(hook, env)

    async def trigger_on_error(self, error: Exception) -> None:
        env = self._build_env(HookTrigger.ON_ERROR, error=error)

        for hook in self.hooks:
            if hook.trigger == HookTrigger.ON_ERROR:
                await self.execute_hook(hook, env)
