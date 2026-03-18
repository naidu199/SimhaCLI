from re import M
from tools.base import Tool
from tools.builtin.edit_file import EditFileTool
from tools.builtin.glob import GlobTool
from tools.builtin.grep import GrepTool
from tools.builtin.list_dir import ListDirTool
from tools.builtin.memory import MemoryTool
from tools.builtin.read_file import ReadFileTool
from tools.builtin.shell import ShellTool
from tools.builtin.todo import TodosTool
from tools.builtin.web_fetch import WebFetchTool
from tools.builtin.web_search import WebSearchTool
from tools.builtin.write_file import WriteFileTool
from tools.workflow.workflow_tool import WorkflowTool

__all__ = [
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "ShellTool",
    "ListDirTool",
    "GlobTool",
    "GrepTool",
    "WebSearchTool",
    "WebFetchTool",
    "TodosTool",
    "MemoryTool",
    "WorkflowTool",
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
        WebSearchTool,
        WebFetchTool,
        TodosTool,
        MemoryTool,
        WorkflowTool,
    ]
