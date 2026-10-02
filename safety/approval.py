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


# Prefix matching the start of a (sub)command: beginning of the string, a
# shell separator, or a wrapper such as sudo. Used for commands whose names
# are common words (e.g. "shutdown", "halt") so that mentioning them as an
# argument (``grep -rn shutdown .``) is not treated as running them.
_CMD_START = r"(?:^|[;&|`(\n]|\$\(|\bsudo\s+|\bexec\s+|\bxargs\s+)\s*(?:\S*/)?"

DANGEROUS_PATTERNS = [
    # File system destruction (recursive rm on root/home/glob, any flag order)
    r"\brm\s+(?:-\S+\s+)*(?:-[a-z]*r[a-z]*|--recursive)\s+(?:-\S+\s+)*(?:[/~*]|\$\{?HOME\b)",
    r"\brmdir\s+[/~]",
    r"\bshred\s+",
    r"\bsrm\s+",
    r"\bfind\s+.*-delete\b",
    r"\bfind\s+.*-exec\s+rm\b",
    # Disk operations
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bgdisk\b",
    r"\bwipefs\b",
    r"\bblkdiscard\b",
    # System control
    _CMD_START + r"shutdown\b",
    _CMD_START + r"reboot\b",
    _CMD_START + r"halt\b",
    _CMD_START + r"poweroff\b",
    _CMD_START + r"init\s+[06]\b",
    r"\bsystemctl\s+(halt|poweroff|reboot|kexec)\b",
    r"\btelinit\s+[06]\b",
    # Permission changes on root
    r"\bchmod\s+(-R\s+)?777\s+[/~]",
    r"\bchown\s+-R\s+.*\s+[/~]",
    r"\bchmod\s+(-R\s+)?[0-7]*[2367]\s+/",
    r"\bchattr\s+.*\s+/",
    # Network exposure
    r"\bnc\s+-l",
    r"\bnetcat\s+-l",
    r"\bncat\s+-l",
    r"\bsocat\s+.*LISTEN",
    r"\bpython[0-9.]*\s.*-m\s+http\.server",
    r"\bpython[0-9.]*\s.*SimpleHTTPServer",
    r"\bphp\s+-S\s+0\.0\.0\.0",
    # Code execution from network
    r"\bcurl\s+.*\|\s*(sudo\s+)?(bash|sh|python[0-9.]*|ruby|perl|php)\b",
    r"\bwget\s+.*\|\s*(sudo\s+)?(bash|sh|python[0-9.]*|ruby|perl|php)\b",
    r"\bfetch\s+.*\|\s*(bash|sh)\b",
    r"\|\s*sh\s*$",
    r"\|\s*bash\s*$",
    # Fork bomb and resource exhaustion
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
    r"\bwhile\s+true\b.*\bdo\b",
    r"\byes\s+>\s+/dev/",
    r"\bcat\s+/dev/zero\s*>",
    # Kernel/System modification
    r"\binsmod\b",
    r"\brmmod\b",
    r"\bmodprobe\b",
    r"\bsysctl\s+-w\b",
    r"\becho\s+.*>\s*/proc/",
    r"\becho\s+.*>\s*/sys/",
    # Package manager dangerous operations
    r"\b(apt|apt-get|yum|dnf)\s+remove\b.*--purge",
    r"\b(apt|apt-get|yum|dnf)\s+autoremove\b",
    r"\bpip[0-9.]*\s+uninstall\b.*\s-y\b",
    r"\bnpm\s+(uninstall|remove)\b.*\s(-g|--global)\b",
    # Cron/scheduled tasks manipulation
    r"\bcrontab\s+-r\b",
    _CMD_START + r"at\s+.*\brm\s+",
    # Process killing (bulk)
    r"\bkillall\s+-9\b",
    r"\bpkill\s+-9\s+",
    r"\bkill\s+-9\s+-1\b",
    # Potentially malicious scripts
    r"\beval\s+.*\$\(",
    r"\bexec\s+.*\$\(",
    r"\bbase64\s+(-d|--decode)\b.*\|\s*(sh|bash)\b",
    # Database operations
    r"\b(mysql|psql|mongo|mongosh)\b.*\bDROP\s+DATABASE\b",
    r"\b(mysql|psql|mongo|mongosh)\b.*\bDROP\s+TABLE\b",
    r"\bredis-cli\b.*\bFLUSHALL\b",
    r"\bredis-cli\b.*\bFLUSHDB\b",
    # Container/VM operations
    r"\bdocker\s+(rm|rmi)\b.*\s(-[a-z]*f[a-z]*|--force)\b",
    r"\bdocker\s+system\s+prune\b.*\s-[a-z]*a",
    r"\bkubectl\s+delete\b",
    r"\b(virsh|vboxmanage)\s+destroy\b",
    # Git destructive operations
    r"\bgit\s+push\b.*--force",
    r"\bgit\s+reset\b.*--hard\s+HEAD~",
    r"\bgit\s+clean\b.*-fdx",
    # Compression bombs
    r"\btar\s+.*zxf.*-C\s+/",
    r"\bunzip\b.*-d\s+/",
    # History/log manipulation
    r"\bhistory\s+-c\b",
    r">\s*/var/log/",
    r"\brm\s+.*\.log$",
    r"\btruncate\b.*-s\s+0\b",
    # Sudo abuse
    r"\bsudo\s+su\s+-",
    r"\bsudo\s+.*\bpasswd\b",
    r"\becho\s+.*\|\s*sudo\s+tee\b",
]

# Shell control/redirection metacharacters. A command containing any of these
# can chain, redirect or substitute arbitrary commands, so it is never "safe".
_SHELL_METACHARS = re.compile(r"[;&|<>`\n\r]|\$\(")

# Patterns for safe commands (can be auto-approved). Only genuinely read-only
# commands belong here; anything that can write files, execute code or
# mutate system state must go through confirmation.
SAFE_PATTERNS = [
    # Information commands
    r"^(ls|dir|pwd|cd|echo|cat|head|tail|less|more|wc)(\s|$)",
    r"^(locate|which|whereis|file|stat|du|df)(\s|$)",
    r"^(tree|exa|bat)(\s|$)",
    # Development tools (read-only)
    r"^git\s+(status|log|diff|show|blame|shortlog)(\s|$)",
    r"^git\s+(branch|tag|remote)(\s+(-a|-r|-v|-vv|-l|--all|--list|--verbose))*\s*$",
    r"^(npm|yarn|pnpm)\s+(list|ls|outdated|view|info|search)(\s|$)",
    r"^pip[0-9.]*\s+(list|show|freeze|search)(\s|$)",
    r"^cargo\s+(tree|search)(\s|$)",
    r"^gem\s+(list|search|info)(\s|$)",
    r"^go\s+(list|doc|version)(\s|$)",
    r"^composer\s+(show|search|outdated)(\s|$)",
    # Text processing (read-only; no in-place editors or output-file options)
    r"^(grep|egrep|fgrep|rg|cut|tr|diff|comm|paste|join)(\s|$)",
    r"^jq(\s|$)",
    # System info
    r"^(date|cal|uptime|whoami|id|groups|hostname|uname|arch)(\s|$)",
    r"^(env|printenv|set)$",
    r"^printenv\s+\w+$",
    r"^locale(\s|$)",
    r"^timedatectl(\s+status)?$",
    # Process info (read-only)
    r"^(ps|top|htop|btop|pgrep|pstree|lsof)(\s|$)",
    r"^(free|vmstat|iostat|mpstat|sar)(\s|$)",
    # Network info (read-only)
    r"^ip\s+(addr|address|link|route|neigh)(\s+show(\s+\S+)?)?$",
    r"^ifconfig(\s+-a)?$",
    r"^(netstat|ss|ping|traceroute|nslookup|dig|host)(\s|$)",
    # Disk/filesystem info
    r"^(lsblk|blkid|findmnt)(\s|$)",
    r"^df\s+-h",
    r"^du\s+-[sh]",
    # Archive listing
    r"^tar\s+(-?t[a-z]*|--list)(\s|$)",
    r"^unzip\s+-l(\s|$)",
    r"^7z\s+l(\s|$)",
    # Package info
    r"^(apt|apt-cache|yum|dnf)\s+(search|show|list|info)(\s|$)",
    r"^dpkg\s+(-l|--list)",
    r"^rpm\s+(-q|--query)",
    # Compiler/build info
    r"^(gcc|g\+\+|clang|rustc|javac|python[0-9.]*|node)\s+(--version|-v|-V)$",
    # Version control (read-only)
    r"^(svn|hg|bzr)\s+(status|log|diff|info)(\s|$)",
    # Documentation
    r"^(man|info|help|whatis|apropos)(\s|$)",
    # Safe utilities
    r"^(bc|calc|units)(\s|$)",
    r"^seq(\s|$)",
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
    command = command.strip()
    if _SHELL_METACHARS.search(command):
        return False
    # rg --pre <cmd> runs <cmd> on every searched file
    if re.search(r"(^|\s)--pre(=|\s|$)", command):
        return False

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

        safe = is_safe_command(command)

        if self.approval_policy == ApprovalPolicy.NEVER:
            return ApprovalDecision.APPROVED if safe else ApprovalDecision.REJECTED

        if self.approval_policy in {
            ApprovalPolicy.AUTO_APPROVE,
            ApprovalPolicy.ON_FAILURE,
        }:
            return ApprovalDecision.APPROVED

        if self.approval_policy == ApprovalPolicy.ALWAYS:
            return ApprovalDecision.NEEDS_CONFIRMATION

        # ON_REQUEST / AUTO_EDIT: auto-approve only known read-only commands
        if safe:
            return ApprovalDecision.APPROVED
        return ApprovalDecision.NEEDS_CONFIRMATION

    async def check_approval(self, context: ApprovalContext) -> ApprovalDecision:
        if not context.is_mutating:
            return ApprovalDecision.APPROVED

        if self.approval_policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        # Commands are fully decided by the command safety assessment
        if context.command:
            return self._assess_command_safety(context.command)

        if self.approval_policy == ApprovalPolicy.ALWAYS:
            return ApprovalDecision.NEEDS_CONFIRMATION

        if self.approval_policy == ApprovalPolicy.NEVER:
            return ApprovalDecision.REJECTED

        # Check if any paths are outside the workspace
        workspace = Path(self.cwd).resolve()
        has_outside_path = False
        for path in context.affected_paths:
            if not Path(path).resolve().is_relative_to(workspace):
                has_outside_path = True
                break

        # If there are paths outside the workspace, require confirmation
        if has_outside_path:
            return ApprovalDecision.NEEDS_CONFIRMATION

        if context.is_dangerous:
            return ApprovalDecision.NEEDS_CONFIRMATION

        return ApprovalDecision.APPROVED

    async def request_confirmation(self, confirmation: ToolConfirmation) -> bool:
        if self.confirmation_callback:
            result = self.confirmation_callback(confirmation)
            # Support both sync and async callbacks
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                return await result
            return result

        # No way to ask the user: deny rather than silently approve
        return False
