"""Install test I/O boundaries before collecting modules that import browser_harness."""

import os
import tempfile
from pathlib import Path

import pytest

from scripts import validation_lab


def pytest_addoption(parser):
    parser.addoption("--lab-manifest", help="Manifest from validation_lab.py prepare; required for native tests")


def pytest_configure(config):
    manifest_path = config.getoption("--lab-manifest")
    config._lab_temporary = None
    config._lab_environment = dict(os.environ)
    config._lab_manifest = None
    config._lab_manifest_path = Path(manifest_path).absolute() if manifest_path else None
    if manifest_path:
        try:
            config._lab_manifest = validation_lab.configure_native(config._lab_manifest_path)
        except (OSError, ValueError, validation_lab.LabSafetyError) as error:
            raise pytest.UsageError(str(error)) from error
    else:
        config._lab_temporary = tempfile.TemporaryDirectory(prefix="jev-offline-", dir="/tmp")
        os.environ.update(validation_lab.isolated_environment(config._lab_temporary.name))
    config._lab_guard = validation_lab.RuntimeGuard(config._lab_manifest).install()


def pytest_collection_modifyitems(config, items):
    selected, deselected = [], []
    for item in items:
        if item.get_closest_marker("native") and config._lab_manifest is None:
            if config.option.markexpr and "native" in config.option.markexpr.replace("not native", ""):
                raise pytest.UsageError("Native tests require a verified --lab-manifest; refusing to skip them")
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture(autouse=True)
def test_io_boundary(request, tmp_path, monkeypatch):
    # Existing per-module fixtures may provide further isolation or explicit fake clients/processes.
    monkeypatch.chdir(tmp_path)
    from jev_ultrafast import model

    def deny_provider(*_args, **_kwargs):
        raise validation_lab.LabSafetyError("Real model HTTP is forbidden in every test mode")

    monkeypatch.setattr(model.CLIENT, "post", deny_provider)
    if request.node.get_closest_marker("native"):
        path = request.config._lab_manifest_path
        if not path:
            pytest.fail("Native test selected without a lab manifest")
        validation_lab.validate_manifest(path)


@pytest.fixture
def lab_manifest(request):
    manifest = request.config._lab_manifest
    if manifest is None:
        pytest.fail("This fixture requires --lab-manifest")
    return manifest


def pytest_unconfigure(config):
    guard = getattr(config, "_lab_guard", None)
    if guard:
        guard.close()
    temporary = getattr(config, "_lab_temporary", None)
    if temporary:
        temporary.cleanup()
    environment = getattr(config, "_lab_environment", None)
    if environment is not None:
        os.environ.clear()
        os.environ.update(environment)
