"""Opt-in independent JSON Schema qualification (requires jsonschema).

python -m tests.v2.schema_smoke
No host or desktop input. Compare compact MCP schemas to unfactored contracts.
"""
import copy
import json

from jsonschema import Draft202012Validator

from cu_suite.v2.contracts import ACTION_ARGS, SCHEMAS, STEP, STEPS, tool_definitions
from cu_suite.v2.help import guide


def standard_refs(node):
    if isinstance(node, dict):
        return {k: "#/$defs/"+v if k == "$ref" else standard_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [standard_refs(v) for v in node]
    return node


def sample(schema):
    if "$ref" in schema:
        step = {"id": "nested", "op": "focus"}
        return step if schema["$ref"] == "step" else [step]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {key: sample(schema["properties"][key]) for key in schema.get("required", [])}
    if kind == "array":
        return [sample(schema["items"]) for _ in range(schema.get("minItems", 0))]
    if kind == "boolean":
        return False
    if kind in ("number", "integer"):
        return schema.get("minimum", 0)
    return "example"


def main():
    definitions = tool_definitions()
    for tool in definitions:
        Draft202012Validator.check_schema(tool["inputSchema"])
    compact = next(t["inputSchema"] for t in definitions if t["name"] == "axis.run")
    expanded = standard_refs({**copy.deepcopy(SCHEMAS["axis.run"]), "$defs": {"step": STEP, "steps": STEPS}})
    validators = [Draft202012Validator(s) for s in (compact, expanded)]
    cases = [guide()["example"]["arguments"]]
    for op, schema in ACTION_ARGS.items():
        args = sample(schema)
        # minProperties-only selectors still require a discovered discriminator.
        for name in ("at", "start", "end"):
            if name in args:
                args[name] = {"selector": {"name": "Input"}}
        step = {"id": "s", "op": op, "args": args}
        request = {"session_id": "session", "idempotency_key": "key", "steps": [step]}
        assert all(v.is_valid(request) for v in validators), op
        cases.append(request)
        for field in ("id", "op"):
            variant = copy.deepcopy(request)
            del variant["steps"][0][field]
            cases.append(variant)
        variant = copy.deepcopy(request)
        variant["steps"][0]["args"]["unknown"] = True
        cases.append(variant)
        for field in schema.get("required", []):
            variant = copy.deepcopy(request)
            del variant["steps"][0]["args"][field]
            cases.append(variant)
        detailed = guide({"action": op})["args_schema"]
        Draft202012Validator.check_schema(detailed)
        assert Draft202012Validator(detailed).is_valid(args), op
    for case in cases:
        assert validators[0].is_valid(case) == validators[1].is_valid(case), case
    print(json.dumps({"tools": len(definitions), "actions": len(ACTION_ARGS), "equivalence_cases": len(cases), "native": False}))


if __name__ == "__main__":
    main()
