"""Quick script to dump and validate tool schemas after _build_tools cleaning."""

import json
import sys

sys.path.insert(0, ".")

from config.loader import load_config
from tools.registry import create_default_registry
from client.llm_client import LLMClient

config = load_config()
registry = create_default_registry(config)
schemas = registry.get_schemas()

# Simulate what the API actually receives
client = LLMClient(config)
built_tools = client._build_tools(schemas)

print(f"Total tools: {len(built_tools)}\n")
for t in built_tools:
    fn = t.get("function", {})
    name = fn.get("name", "???")
    params = fn.get("parameters", {})
    issues = []
    if not isinstance(params, dict):
        issues.append(f"parameters is {type(params).__name__}, not dict")
    else:
        if "type" not in params:
            issues.append("missing 'type' in parameters")
        if "$defs" in params or "definitions" in params:
            issues.append("has $defs/$definitions")
        props = params.get("properties", {})
        for pname, pval in props.items():
            if isinstance(pval, dict):
                if "$ref" in pval:
                    issues.append(f"'{pname}' has unresolved $ref")
                if "anyOf" in pval:
                    issues.append(f"'{pname}' has 'anyOf'")
                if "default" in pval:
                    issues.append(f"'{pname}' has 'default'")
                if "title" in pval:
                    issues.append(f"'{pname}' has 'title'")

    status = "ISSUES" if issues else "OK"
    print(f"[{status}] {name}")
    if issues:
        for i in issues:
            print(f"  ! {i}")
        print(f"  Schema: {json.dumps(fn, indent=2)[:600]}")
    print()
