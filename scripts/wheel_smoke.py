"""Build the wheel, check it ships the exact sources and assets, and import the public API from an isolated install.

The child installs the test I/O guard before importing the package, so no browser, provider or review can start.

    uv run python scripts/wheel_smoke.py
"""

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "jev_ultrafast"
SHIPPED = {".py", ".js", ".html", ".css"}
ASSETS = ["snapshot.js", "static/app.js", "static/index.html", "static/style.css", "static/fixture.html"]


def child(sandbox):
    """Runs inside the fresh environment: guard first, then import only from that environment."""
    spec = importlib.util.spec_from_file_location("validation_lab", ROOT / "scripts/validation_lab.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    os.environ.update(lab.isolated_environment(sandbox))
    guard = lab.RuntimeGuard().install()
    try:
        from importlib.resources import files

        import jev_ultrafast
        from jev_ultrafast import contracts, demo, mcp_server, model, site_notes

        modules = [jev_ultrafast, contracts, demo, mcp_server, model, site_notes]
        for module in modules:
            if not Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
                raise AssertionError(f"{module.__name__} imported from outside the wheel environment")
        for function in (jev_ultrafast.Agent, jev_ultrafast.Agent.new_goal, mcp_server.run_goal):
            parameter = inspect.signature(function).parameters["allowed_operations"]
            assert parameter.default is inspect.Parameter.empty, f"{function.__qualname__} has a default policy"
        for name in ASSETS:
            assert files("jev_ultrafast").joinpath(name).read_bytes(), f"missing asset {name}"
        print(json.dumps({"imports": {module.__name__: module.__file__ for module in modules}, "assets": ASSETS,
                          "required_policy_signatures": True, "io_denied_before_import": True}))
    finally:
        guard.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="install the locked dependencies from uv's cache only")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    with tempfile.TemporaryDirectory(prefix="wheel-smoke-") as directory:
        directory = Path(directory)
        subprocess.run(["uv", "build", "--wheel", "-o", str(directory / "dist")], cwd=ROOT, check=True,
                       capture_output=True)
        [wheel] = (directory / "dist").glob("*.whl")
        checked = {}
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            for path in sorted(PACKAGE.rglob("*")):
                if path.is_file() and path.suffix in SHIPPED and "__pycache__" not in path.parts:
                    name = path.relative_to(ROOT).as_posix()
                    assert name in names, f"wheel lacks {name}"
                    assert archive.read(name) == path.read_bytes(), f"wheel ships a stale {name}"
                    checked[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        environment, python = directory / "venv", str(directory / "venv/bin/python")
        # The locked runtime dependencies first, then the wheel alone, so it cannot pull a different version.
        requirements = directory / "requirements.txt"
        commands = [
            ["uv", "export", "--quiet", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes",
             "-o", str(requirements)],
            ["uv", "venv", "--quiet", "--python", sys.executable, str(environment)],
            ["uv", "pip", "install", "--quiet", *(["--offline"] if args.offline else []), "--python", python,
             "-r", str(requirements)],
            ["uv", "pip", "install", "--quiet", "--offline", "--no-deps", "--python", python, str(wheel)],
            [python, "-I", str(Path(__file__).resolve()), "--child", str(directory / "box")],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=ROOT if command[1] == "export" else directory, capture_output=True,
                                    text=True, timeout=300, check=False)
            if result.returncode:
                raise SystemExit(f"failed: {' '.join(command)}\n{result.stdout}{result.stderr}")
        report = json.loads(result.stdout)
        print(json.dumps({"wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                          "sources_checked": len(checked), **report}, indent=2))


if __name__ == "__main__":
    main()
