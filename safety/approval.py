from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import asyncio
import re
from typing import Any, Awaitable, Callable
from config.config import ApprovalPolicy
from tools.base import ToolConfirmation


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass
class ApprovalContext:

    tool_name: str
    params: dict[str, Any]
    is_mutating: bool
    affected_paths: list[Path]
    command: str | None = None
    is_dangerous: bool = False


DANGEROUS_PATTERNS = [
    # File system destruction
    r"rm\s+(-rf?|--recursive)\s+[/~]",
    r"rm\s+-rf?\s+\*",
    r"rmdir\s+[/~]",
    r"shred\s+",
    r"srm\s+",
    r"find\s+.*-delete",
    r"find\s+.*-exec\s+rm",
    # Disk operations
    r"dd\s+if=",
    r"mkfs",
    r"fdisk",
    r"parted",
    r"gdisk",
    r"wipefs",
    r"blkdiscard",
    # System control
    r"shutdown",
    r"reboot",
    r"halt",
    r"poweroff",
    r"init\s+[06]",
    r"systemctl\s+(halt|poweroff|reboot|kexec)",
    r"telinit\s+[06]",
    # Permission changes on root
    r"chmod\s+(-R\s+)?777\s+[/~]",
    r"chown\s+-R\s+.*\s+[/~]",
    r"chmod\s+(-R\s+)?[0-7]*[2367]\s+/",
    r"chattr\s+.*\s+/",
    # Network exposure
    r"nc\s+-l",
    r"netcat\s+-l",
    r"ncat\s+-l",
    r"socat\s+.*LISTEN",
    r"python.*-m\s+http\.server",
    r"python.*SimpleHTTPServer",
    r"php\s+-S\s+0\.0\.0\.0",
    # Code execution from network
    r"curl\s+.*\|\s*(bash|sh|python|ruby|perl|php)",
    r"wget\s+.*\|\s*(bash|sh|python|ruby|perl|php)",
    r"fetch\s+.*\|\s*(bash|sh)",
    r"\|\s*sh\s*$",
    r"\|\s*bash\s*$",
    # Fork bomb and resource exhaustion
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
    r"while\s+true.*do",
    r"yes\s+>\s+/dev/",
    r"cat\s+/dev/zero\s*>",
    # Kernel/System modification
    r"insmod",
    r"rmmod",
    r"modprobe",
    r"sysctl\s+-w",
    r"echo\s+.*>\s*/proc/",
    r"echo\s+.*>\s*/sys/",
    # Package manager dangerous operations
    r"(apt|apt-get|yum|dnf)\s+remove.*--purge",
    r"(apt|apt-get|yum|dnf)\s+autoremove",
    r"pip\s+uninstall.*-y",
    r"npm\s+(uninstall|remove).*-g",
    # Cron/scheduled tasks manipulation
    r"crontab\s+-r",
    r"at\s+.*rm\s+",
    # Process killing (bulk)
    r"killall\s+-9",
    r"pkill\s+-9\s+.*",
    r"kill\s+-9\s+-1",
    # Potentially malicious scripts
    r"eval\s+.*\$\(",
    r"exec\s+.*\$\(",
    r"base64\s+-d.*\|\s*(sh|bash)",
    # Database operations
    r"(mysql|psql|mongo).*DROP\s+DATABASE",
    r"(mysql|psql|mongo).*DROP\s+TABLE",
    r"redis-cli.*FLUSHALL",
    r"redis-cli.*FLUSHDB",
    # Container/VM operations
    r"docker\s+(rm|rmi).*-f",
    r"docker\s+system\s+prune.*-a",
    r"kubectl\s+delete",
    r"(virsh|vboxmanage)\s+destroy",
    # Git destructive operations
    r"git\s+push.*--force",
    r"git\s+reset.*--hard\s+HEAD~",
    r"git\s+clean.*-fdx",
    # Compression bombs
    r"tar\s+.*zxf.*-C\s+/",
    r"unzip.*-d\s+/",
    # History/log manipulation
    r"history\s+-c",
    r">\s*/var/log/",
    r"rm\s+.*\.log$",
    r"truncate.*-s\s+0",
    # Sudo abuse
    r"sudo\s+su\s+-",
    r"sudo\s+.*passwd",
    r"echo\s+.*\|\s*sudo\s+tee",
]

# Patterns for safe commands (can be auto-approved)
SAFE_PATTERNS = [
    # Information commands
    r"^(ls|dir|pwd|cd|echo|cat|head|tail|less|more|wc)(\s|$)",
    r"^(find|locate|which|whereis|file|stat|du|df)(\s|$)",
    r"^(tree|exa|bat)(\s|$)",
    # Development tools (read-only)
    r"^git\s+(status|log|diff|show|branch|remote|tag|blame|shortlog)(\s|$)",
    r"^(npm|yarn|pnpm)\s+(list|ls|outdated|view|info|search)(\s|$)",
    r"^pip\s+(list|show|freeze|search)(\s|$)",
    r"^cargo\s+(tree|search|check)(\s|$)",
    r"^gem\s+(list|search|info)(\s|$)",
    r"^go\s+(list|doc|version)(\s|$)",
    r"^composer\s+(show|search|outdated)(\s|$)",
    # Text processing (usually safe)
    r"^(grep|egrep|fgrep|awk|sed|cut|sort|uniq|tr|diff|comm|paste|join)(\s|$)",
    r"^(jq|yq|xmllint)(\s|$)",
    # System info
    r"^(date|cal|uptime|whoami|id|groups|hostname|uname|arch)(\s|$)",
    r"^(env|printenv|set)$",
    r"^(locale|timedatectl)(\s|$)",
    # Process info (read-only)
    r"^(ps|top|htop|btop|pgrep|pstree|lsof)(\s|$)",
    r"^(free|vmstat|iostat|mpstat|sar)(\s|$)",
    # Network info (read-only)
    r"^(ip\s+(addr|link|route|neigh)|ifconfig)(\s|$)",
    r"^(netstat|ss|ping|traceroute|nslookup|dig|host)(\s|$)",
    r"^(curl|wget)\s+.*(-I|--head|\-\-spider)(\s|$)",
    # Disk/filesystem info
    r"^(lsblk|blkid|findmnt|mount)(\s|$)",
    r"^df\s+-h",
    r"^du\s+-[sh]",
    # Archive listing (safe extraction patterns)
    r"^(tar|unzip|7z)\s+.*(-t|--list|-l)(\s|$)",
    # Package info
    r"^(apt|apt-cache|yum|dnf)\s+(search|show|list|info)(\s|$)",
    r"^dpkg\s+(-l|--list)",
    r"^rpm\s+(-q|--query)",
    # Compiler/build info
    r"^(gcc|g\+\+|clang|rustc|javac|python|node)\s+(--version|-v)$",
    r"^make\s+-n",
    # Version control (read-only)
    r"^(svn|hg|bzr)\s+(status|log|diff|info)(\s|$)",
    # Documentation
    r"^(man|info|help|whatis|apropos)(\s|$)",
    r"^.*--help$",
    # Safe utilities
    r"^(bc|calc|units)(\s|$)",
    r"^(time|timeout)(\s|$)",
    r"^(watch|yes|seq|shuf)(\s|$)",
    # Database read-only
    r"^(mysql|psql|sqlite3).*SELECT(\s|$)",
    r"^(mysql|psql|sqlite3).*(SHOW|DESCRIBE|EXPLAIN)(\s|$)",
    # Docker/container info
    r"^docker\s+(ps|images|version|info|inspect)(\s|$)",
    r"^kubectl\s+(get|describe|logs|version)(\s|$)",
]

# Patterns requiring user confirmation (moderate risk)
CONFIRM_PATTERNS = [
    # File operations in user space
    r"^rm\s+(?!.*(-rf?|--recursive)\s+[/~])(?!.*\s+\*)",
    r"^mv\s+",
    r"^cp\s+.*-r",
    # Installation/updates
    r"^(apt|apt-get|yum|dnf)\s+(install|update|upgrade)",
    r"^pip\s+install",
    r"^npm\s+install",
    r"^cargo\s+install",
    # Git write operations
    r"^git\s+(commit|push|pull|merge|rebase|stash|add|checkout|clone)",
    # Build/compile operations
    r"^(make|cmake|ninja|gradle|mvn)\s+(?!-n)",
    r"^(npm|yarn|pnpm)\s+(run|build)",
    # Archive creation
    r"^(tar|zip|7z)\s+.*c",
    # Process management (selective)
    r"^kill\s+(?!-9\s+-1)",
    r"^pkill\s+(?!-9)",
    # Service management
    r"^systemctl\s+(start|stop|restart|reload)(?!\s+(halt|poweroff|reboot))",
    r"^service\s+.*\s+(start|stop|restart)",
]


def is_dangerous_command(command: str) -> bool:
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True

    return False


def is_safe_command(command: str) -> bool:
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True

    return False


def is_confirm_command(command: str) -> bool:
    for pattern in CONFIRM_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True

    return False


class ApprovalManager:
    def __init__(
        self,
        approval_policy: ApprovalPolicy,
        cwd: Path,
        confirmation_callback: Callable[[ToolConfirmation], bool] | None = None,
    ) -> None:
        self.approval_policy = approval_policy
        self.cwd = cwd
        self.confirmation_callback = confirmation_callback

    def _assess_command_safety(self, command: str) -> ApprovalDecision:
        if self.approval_policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        if is_dangerous_command(command):
            return ApprovalDecision.REJECTED

        if self.approval_policy == ApprovalPolicy.NEVER:
            if is_safe_command(command):
                return ApprovalDecision.APPROVED
            return ApprovalDecision.REJECTED

        if self.approval_policy in {
            ApprovalPolicy.AUTO_APPROVE,
            ApprovalPolicy.ON_FAILURE,
        }:
            return ApprovalDecision.APPROVED

        if self.approval_policy == ApprovalPolicy.AUTO_EDIT:
            if is_safe_command(command):
                return ApprovalDecision.APPROVED
            if is_confirm_command(command):
                return ApprovalDecision.NEEDS_CONFIRMATION
            return ApprovalDecision.NEEDS_CONFIRMATION

        # Default policy behavior (likely CONFIRM or similar)
        if is_safe_command(command):
            return ApprovalDecision.APPROVED
        if is_confirm_command(command):
            return ApprovalDecision.NEEDS_CONFIRMATION

        return ApprovalDecision.NEEDS_CONFIRMATION

    async def check_approval(self, context: ApprovalContext) -> ApprovalDecision:
        if not context.is_mutating:
            return ApprovalDecision.APPROVED

        if context.command:
            decision = self._assess_command_safety(context.command)
            if decision != ApprovalDecision.NEEDS_CONFIRMATION:
                return decision

        # Check if any paths are outside the workspace
        has_outside_path = False
        for path in context.affected_paths:
            if not path.is_relative_to(self.cwd):
                has_outside_path = True
                break

        # If there are paths outside the workspace, require confirmation
        if has_outside_path:
            if self.approval_policy == ApprovalPolicy.YOLO:
                return ApprovalDecision.APPROVED
            return ApprovalDecision.NEEDS_CONFIRMATION

        if context.is_dangerous:
            if self.approval_policy == ApprovalPolicy.YOLO:
                return ApprovalDecision.APPROVED
            return ApprovalDecision.NEEDS_CONFIRMATION

        return ApprovalDecision.APPROVED

    async def request_confirmation(self, confirmation: ToolConfirmation) -> bool:
        if self.confirmation_callback:
            result = self.confirmation_callback(confirmation)
            # Support both sync and async callbacks
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                return await result
            return result

        return True
