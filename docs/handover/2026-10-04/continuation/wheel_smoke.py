"""Inspect and import a built wheel in a fresh offline environment; no browser/provider calls."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def run_child(candidate, output):
    # Load only the dependency-free test boundary helper, never candidate package code.
    spec = importlib.util.spec_from_file_location('validation_lab', candidate / 'scripts/validation_lab.py')
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    os.environ.update(lab.isolated_environment(output / 'sandbox'))
    guard = lab.RuntimeGuard().install()
    try:
        import inspect
        import jev_ultrafast
        from jev_ultrafast import contracts, demo, mcp_server, model, site_notes
        from importlib.resources import files
        imported = [jev_ultrafast, contracts, demo, mcp_server, model, site_notes]
        for module in imported:
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(Path(sys.prefix).resolve()):
                raise AssertionError(f'Imported outside wheel environment: {module.__name__}')
        for function in (jev_ultrafast.Agent, jev_ultrafast.Agent.new_goal, mcp_server.run_goal):
            parameter = inspect.signature(function).parameters['allowed_operations']
            assert parameter.default is inspect.Parameter.empty
        assets = ['snapshot.js', 'static/app.js', 'static/index.html', 'static/style.css', 'static/fixture.html']
        for name in assets:
            assert files('jev_ultrafast').joinpath(name).read_bytes()
        result = {'imports': {module.__name__: module.__file__ for module in imported},
                  'assets': assets, 'required_policy_signatures': True,
                  'runtime_io_denial_installed': True, 'public_api_imports': True}
        print(json.dumps(result, indent=2))
    finally:
        guard.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parent
    candidate = evidence / 'candidate'
    output = args.output.resolve()
    if evidence not in output.parents:
        raise SystemExit('Output must be inside this evidence directory')
    if args.child:
        run_child(candidate, output)
        return
    if output.exists() or args.wheel is None:
        raise SystemExit('Provide --wheel and a new --output directory')
    wheel = args.wheel.resolve()
    if not wheel.is_relative_to(candidate / 'dist'):
        raise SystemExit('Wheel must be from the candidate dist directory')
    output.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        expected = [p for p in (candidate / 'jev_ultrafast').rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py', '.js', '.html', '.css'}]
        checked = {}
        for path in expected:
            name = path.relative_to(candidate).as_posix()
            shipped = archive.read(name)
            assert shipped == path.read_bytes(), f'Stale or missing wheel asset: {name}'
            checked[name] = hashlib.sha256(shipped).hexdigest()
        (output / 'wheel-contents.json').write_text(json.dumps({'names': names, 'checked': checked}, indent=2) + '\n')
    records = []
    with tempfile.TemporaryDirectory(prefix='wheel-env-', dir=output) as directory:
        environment = Path(directory) / 'venv'
        commands = [
            ['uv', 'venv', '--python', str(candidate / '.venv/bin/python'), str(environment)],
            ['uv', 'pip', 'install', '--offline', '--python', str(environment / 'bin/python'), str(wheel)],
            [str(environment / 'bin/python'), '-I', str(Path(__file__).resolve()), '--child', '--output', str(output)],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=output, capture_output=True, text=True, timeout=180, check=False)
            (output / f'command-{index}.log').write_text(result.stdout + result.stderr)
            records.append({'argv': command, 'exit_code': result.returncode, 'log': f'command-{index}.log'})
            (output / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
            if result.returncode:
                raise SystemExit(f'Wheel check failed: command-{index}.log')
    print(json.dumps({'wheel': str(wheel), 'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                      'source_files_checked': len(checked), 'isolated_imports': True}))


if __name__ == '__main__':
    main()
