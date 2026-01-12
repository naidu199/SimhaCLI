from tools.base import Tool
from tools.builtin.edit_file import EditFileTool
from tools.builtin.glob import GlobTool
from tools.builtin.grep import GrepTool
from tools.builtin.list_dir import ListDirTool
from tools.builtin.read_file import ReadFileTool
from tools.builtin.shell import ShellTool
from tools.builtin.wite_file import WriteFileTool

__all__ = [
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "ShellTool",
    "ListDirTool",
    "GlobTool",
    "GrepTool",
]


def get_all_builtin_tools() -> list[Tool]:
    return [
        ReadFileTool,
        WriteFileTool,
        EditFileTool,
        ShellTool,
        ListDirTool,
        GlobTool,
        GrepTool,
    ]
