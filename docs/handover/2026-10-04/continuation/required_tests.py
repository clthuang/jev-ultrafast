"""Report missing named acceptance nodes in the approved plan without importing tests."""
import ast
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent
plan = (root / 'baseline/docs/robustness-efficiency-implementation-plan.md').read_text()
required = {}
for section in re.split(r'^### ', plan, flags=re.M)[1:]:
    task = section.splitlines()[0].split(' — ')[0]
    current = None
    nodes = []
    for token in re.findall(r'`([^`\n]+)`', section):
        if re.fullmatch(r'tests/\w+\.py', token):
            current = token
        elif match := re.fullmatch(r'(tests/\w+\.py)::(test_\w+)', token):
            current = match[1]
            nodes.append(token)
        elif re.fullmatch(r'(?:::)?test_\w+', token) and current:
            nodes.append(current + '::' + token.removeprefix('::'))
    if nodes:
        required[task] = list(dict.fromkeys(nodes))
missing = []
parse_errors = {}
for task, nodes in required.items():
    for node in nodes:
        name, function = node.split('::')
        path = root / 'candidate' / name
        functions = set()
        if path.exists():
            try:
                functions = {entry.name for entry in ast.walk(ast.parse(path.read_text()))
                             if isinstance(entry, (ast.FunctionDef, ast.AsyncFunctionDef))}
            except SyntaxError as error:
                parse_errors[name] = str(error)
        if function not in functions:
            missing.append({'task': task, 'node': node})
print(json.dumps({'required': required, 'missing': missing, 'parse_errors': parse_errors}, indent=2))
