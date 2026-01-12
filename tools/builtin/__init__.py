from tools.base import Tool
from tools.builtin.read_file import ReadFileTool
from tools.builtin.wite_file import WriteFileTool

__all__ = ["ReadFileTool", "WriteFileTool"]


def get_all_builtin_tools() -> list[Tool]:
    return [ReadFileTool, WriteFileTool]
