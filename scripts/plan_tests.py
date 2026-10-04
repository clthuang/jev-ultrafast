"""Run the robustness plan's named acceptance tests for chosen tasks.

Fails when a named test is missing, collects nothing, or any variant fails, errors, skips or xfails. Native nodes run
in a fresh owned lab (scripts/validation_lab.py run); the rest run offline. No model or network calls.

    uv run python scripts/plan_tests.py REVIEWS          # every task whose ID contains REVIEWS
    uv run python scripts/plan_tests.py SELECT-2 --native
    uv run python scripts/plan_tests.py --list
"""

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/robustness-efficiency-implementation-plan.md"
# The 45 inherited readiness/composition nodes GATE-READINESS also requires (docs/robustness-efficiency/).
INHERITED = ROOT / "docs/robustness-efficiency/readiness-required-tests.json"
NATIVE_FILES = {"tests/test_browser_native.py"}


def required_nodes():
    """{task: [file::test, ...]} from the plan's Verify lines, in plan order."""
    required = {}
    for section in re.split(r"^### ", PLAN.read_text(), flags=re.M)[1:]:
        task = section.splitlines()[0].split(" — ")[0].strip()
        current, nodes = None, []
        for token in re.findall(r"`([^`\n]+)`", section):
            if re.fullmatch(r"tests/\w+\.py", token):
                current = token
            elif match := re.fullmatch(r"(tests/\w+\.py)::(test_\w+)", token):
                current = match[1]
                nodes.append(token)
            elif re.fullmatch(r"(?:::)?test_\w+", token) and current:
                nodes.append(current + "::" + token.removeprefix("::"))
        if nodes:
            required[task] = list(dict.fromkeys(nodes))
    required.setdefault("GATE-READINESS", [])
    required["GATE-READINESS"] = list(dict.fromkeys(
        [*required["GATE-READINESS"], *json.loads(INHERITED.read_text())]))
    return required


def defined(node):
    path, name = node.split("::")
    source = ROOT / path
    if not source.is_file():
        return False
    tree = ast.parse(source.read_text())
    return any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
               for item in ast.walk(tree))


def run(nodes, native):
    """Run nodes once; return {node: [(variant, outcome), ...]} from JUnit, where outcome is passed/failed/skipped."""
    with tempfile.TemporaryDirectory(prefix="plan-tests-") as directory:
        junit = Path(directory) / "junit.xml"
        options = ["-q", "-p", "no:cacheprovider", "-o", "xfail_strict=true", f"--junitxml={junit}", *nodes]
        command = ([sys.executable, str(ROOT / "scripts/validation_lab.py"), "run", "--", *options] if native
                   else [sys.executable, "-m", "pytest", *options])
        exit_code = subprocess.run(command, cwd=ROOT, check=False).returncode
        results = {node: [] for node in nodes}
        if junit.is_file():
            for case in ET.parse(junit).iter("testcase"):
                module = case.attrib.get("classname", "").replace(".", "/") + ".py"
                name = case.attrib.get("name", "")
                node = f"{module}::{name.split('[', 1)[0]}"
                outcome = next((child.tag for child in case if child.tag in {"failure", "error", "skipped"}),
                               "passed")
                if node in results:
                    results[node].append((name, outcome))
    return exit_code, results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks", nargs="*", help="task IDs or substrings, such as REVIEWS or SELECT-2")
    parser.add_argument("--native", action="store_true", help="also run native nodes in a fresh owned lab")
    parser.add_argument("--list", action="store_true", help="list the named nodes and whether they exist")
    args = parser.parse_args()
    required = required_nodes()
    tasks = [task for task in required if not args.tasks or any(part in task for part in args.tasks)]
    if not tasks:
        raise SystemExit(f"No task matches {args.tasks}; known: {', '.join(required)}")
    nodes = list(dict.fromkeys(node for task in tasks for node in required[task]))
    missing = [node for node in nodes if not defined(node)]
    if args.list:
        for task in tasks:
            for node in required[task]:
                print(f"{task:15} {'missing' if node in missing else 'defined':8} {node}")
        return 0
    problems = [f"missing: {node}" for node in missing]
    offline = [node for node in nodes if node not in missing and node.split("::")[0] not in NATIVE_FILES]
    native = [node for node in nodes if node not in missing and node.split("::")[0] in NATIVE_FILES]
    counts = {"passed": 0}
    for group, is_native in ((offline, False), (native, True)):
        if not group:
            continue
        if is_native and not args.native:
            problems += [f"not run (native; pass --native): {node}" for node in group]
            continue
        exit_code, results = run(group, is_native)
        if exit_code:
            problems.append(f"pytest exited {exit_code} for the {'native' if is_native else 'offline'} nodes")
        for node, variants in results.items():
            if not variants:
                problems.append(f"collected nothing: {node}")
            for variant, outcome in variants:
                counts[outcome] = counts.get(outcome, 0) + 1
                if outcome != "passed":
                    problems.append(f"{outcome}: {node.split('::')[0]}::{variant}")
    print(json.dumps({"tasks": tasks, "named_nodes": len(nodes), "variants": counts, "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
