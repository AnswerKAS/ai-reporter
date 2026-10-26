"""Deployment gate and file preservation checks for the Proxmox poller."""

import importlib.util
import io
from pathlib import Path
import subprocess
import sys

import pytest


_MODULE_PATH = Path(__file__).resolve().parents[2] / 'deploy' / 'proxmox_deploy.py'
_SPEC = importlib.util.spec_from_file_location('proxmox_deploy', _MODULE_PATH)
deploy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = deploy
_SPEC.loader.exec_module(deploy)


def test_ci_gate_accepts_only_successful_push_for_exact_main_sha(monkeypatch):
    """Ignore success for a different SHA, branch or manual workflow run."""
    sha = 'a' * 40
    payload = {'workflow_runs': [
        {'head_sha': 'b' * 40, 'head_branch': 'main', 'event': 'push',
         'status': 'completed', 'conclusion': 'success'},
        {'head_sha': sha, 'head_branch': 'main', 'event': 'workflow_dispatch',
         'status': 'completed', 'conclusion': 'success'},
        {'head_sha': sha, 'head_branch': 'main', 'event': 'push',
         'status': 'completed', 'conclusion': 'failure',
         'created_at': '2026-10-27T00:00:00Z'},
    ]}

    class Response(io.BytesIO):
        """Expose a JSON API body as a context-managed HTTP response."""

    import json

    def fake_urlopen(_request, timeout):
        """Return the configured workflow runs without an external request."""
        return Response(json.dumps(payload).encode())

    monkeypatch.setattr(deploy, 'urlopen', fake_urlopen)
    assert deploy.approved_by_ci(sha) is False
    payload['workflow_runs'].append({
        'head_sha': sha, 'head_branch': 'main', 'event': 'push',
        'status': 'completed', 'conclusion': 'success',
        'created_at': '2026-10-27T00:01:00Z',
    })
    assert deploy.approved_by_ci(sha) is True


def test_sync_preserves_server_secrets_and_artifacts(tmp_path):
    """Replace old code while keeping server-owned credentials and uploads."""
    source = tmp_path / 'source'
    live = tmp_path / 'live'
    (source / 'backend').mkdir(parents=True)
    (live / 'backend').mkdir(parents=True)
    (live / 'artifacts').mkdir()
    (source / 'backend' / 'app.py').write_text('new code')
    (live / 'backend' / 'app.py').write_text('old code')
    (live / 'backend' / 'removed.py').write_text('stale code')
    (live / '.env').write_text('server secret')
    (live / 'backend' / '.env').write_text('database secret')
    (live / 'artifacts' / 'upload.csv').write_text('uploaded data')
    deploy.sync_source(source, live)
    assert (live / 'backend' / 'app.py').read_text() == 'new code'
    assert not (live / 'backend' / 'removed.py').exists()
    assert (live / '.env').read_text() == 'server secret'
    assert (live / 'backend' / '.env').read_text() == 'database secret'
    assert (live / 'artifacts' / 'upload.csv').read_text() == 'uploaded data'


def test_first_automatic_check_preserves_unapproved_server_code(tmp_path, monkeypatch):
    """Do not fetch or deploy main until the initial marker is installed."""
    monkeypatch.setattr(deploy, 'STATE_DIR', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['proxmox_deploy.py'])

    def unexpected_fetch(_repo_dir):
        """Fail if the disabled poller attempts to read or change Git state."""
        raise AssertionError('main fetched before activation')

    monkeypatch.setattr(deploy, 'fetch_main', unexpected_fetch)
    deploy.main()
    assert not (tmp_path / 'deployed_sha').exists()


def test_failed_rollout_restores_previous_code(tmp_path, monkeypatch):
    """Restore source and keep the old SHA if Compose rejects a new build."""
    live = tmp_path / 'live'
    repo = tmp_path / 'repo'
    state = tmp_path / 'state'
    live.mkdir()
    repo.mkdir()
    state.mkdir()
    (live / 'app.py').write_text('working')
    (live / '.env').write_text('server secret')
    (repo / 'app.py').write_text('broken')
    monkeypatch.setattr(deploy, 'LIVE_DIR', live)
    monkeypatch.setattr(deploy, 'STATE_DIR', state)

    def fake_preflight():
        """Skip server-only Compose requirements in the rollback fixture."""
        return None

    monkeypatch.setattr(deploy, 'preflight', fake_preflight)
    original_run = deploy.run_command
    builds = 0

    def run_with_failed_build(args, **kwargs):
        """Run real rsync, skip Git checkout and fail only the first build."""
        nonlocal builds
        if args[0] == 'rsync':
            return original_run(args, **kwargs)
        if args[:3] == ['docker', 'compose', 'up']:
            builds += 1
            if builds == 1:
                raise subprocess.CalledProcessError(1, args)
        return ''

    monkeypatch.setattr(deploy, 'run_command', run_with_failed_build)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.deploy(repo, 'a' * 40)
    assert (live / 'app.py').read_text() == 'working'
    assert (live / '.env').read_text() == 'server secret'
    assert not (state / 'deployed_sha').exists()
    assert builds == 2
