"""Pull a CI-approved main commit into the existing Proxmox Compose project."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY = 'AnswerKAS/ai-reporter'
REPOSITORY_URL = f'https://github.com/{REPOSITORY}.git'
WORKFLOW = 'ci.yml'
LIVE_DIR = Path('/opt/ai-reporter')
STATE_DIR = Path('/var/lib/ai-reporter-deploy')
HEALTH_URL = 'http://127.0.0.1:8080/api/health'
EXCLUDES = (
    '.git/', '.env', '.claude/', '.opencode/', '._*', '.DS_Store',
    'artifacts/', 'node_modules/', '.venv/', 'dist/', '__pycache__/',
    '.pytest_cache/',
)


class DeploymentError(RuntimeError):
    """Signal a deployment failure that should appear in the service log."""


def run_command(args: list[str], *, cwd: Path | None = None,
                timeout: int = 900, capture: bool = False) -> str:
    """Run one command without a shell and return captured output if requested."""
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            capture_output=capture, timeout=timeout)
    return result.stdout.strip() if capture else ''


def fetch_main(repo_dir: Path) -> str:
    """Fetch public main and return the exact commit advertised by GitHub."""
    if not (repo_dir / '.git').is_dir():
        run_command(['git', 'clone', '--no-checkout', REPOSITORY_URL,
                     str(repo_dir)], timeout=180)
    run_command(['git', 'fetch', '--quiet', '--no-tags', 'origin',
                 'refs/heads/main'], cwd=repo_dir, timeout=180)
    sha = run_command(['git', 'rev-parse', 'FETCH_HEAD'], cwd=repo_dir,
                      capture=True)
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise DeploymentError('Git returned an invalid main commit SHA')
    return sha


def approved_by_ci(sha: str) -> bool:
    """Accept only a successful push workflow run for this exact main SHA."""
    url = (f'https://api.github.com/repos/{REPOSITORY}/actions/workflows/'
           f'{WORKFLOW}/runs?branch=main&event=push&head_sha={sha}&per_page=10')
    request = Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'ai-reporter-proxmox-deployer',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urlopen(request, timeout=15) as response:
            runs = json.load(response).get('workflow_runs', [])
    except (HTTPError, URLError, TimeoutError) as exc:
        raise DeploymentError(f'GitHub CI status is unavailable: {exc}') from exc
    matches = [run for run in runs if run.get('head_sha') == sha
               and run.get('head_branch') == 'main'
               and run.get('event') == 'push']
    if not matches:
        return False
    latest = max(matches, key=lambda run: (run.get('created_at') or '',
                                           run.get('run_attempt') or 0))
    return latest.get('status') == 'completed' and latest.get('conclusion') == 'success'


def sync_source(source: Path, destination: Path) -> None:
    """Sync code while protecting server secrets, artifacts and local tools."""
    command = ['rsync', '-a', '--checksum', '--delete',
               *(f'--exclude={item}' for item in EXCLUDES),
               f'{source}/', f'{destination}/']
    run_command(command, timeout=180)


def snapshot_source(source: Path, backup: Path) -> None:
    """Save the current source tree for rollback without copying secrets."""
    backup.mkdir(parents=True)
    command = ['rsync', '-a', *(f'--exclude={item}' for item in EXCLUDES),
               f'{source}/', f'{backup}/']
    run_command(command, timeout=180)


def healthy(timeout: int = 90) -> bool:
    """Wait until the frontend proxy reports a healthy backend."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(HEALTH_URL, timeout=3) as response:
                if response.status == 200 and json.load(response).get('status') == 'ok':
                    return True
        except (HTTPError, URLError, TimeoutError, ValueError):
            pass
        time.sleep(2)
    return False


def preflight() -> None:
    """Require the existing Compose project and its server-owned secrets."""
    for relative in ('docker-compose.yml', '.env', 'backend/.env',
                     'langfuse/.env'):
        if not (LIVE_DIR / relative).is_file():
            raise DeploymentError(f'Missing server file: {relative}')
    run_command(['docker', 'compose', 'config', '-q'], cwd=LIVE_DIR,
                timeout=30)


def prune_backups(keep: int = 3) -> None:
    """Retain only recent source snapshots after a successful rollout."""
    backups = sorted((path for path in STATE_DIR.glob('backup-*') if path.is_dir()),
                     key=lambda path: path.stat().st_mtime)
    for path in backups[:-keep]:
        shutil.rmtree(path)


def deploy(repo_dir: Path, sha: str) -> None:
    """Roll out a verified commit and restore the previous code on failure."""
    preflight()
    backup = STATE_DIR / f'backup-{int(time.time())}'
    snapshot_source(LIVE_DIR, backup)
    try:
        run_command(['git', 'checkout', '--detach', '--force', sha], cwd=repo_dir,
                    timeout=60)
        sync_source(repo_dir, LIVE_DIR)
        run_command(['docker', 'compose', 'config', '-q'], cwd=LIVE_DIR,
                    timeout=30)
        run_command(['docker', 'compose', 'up', '-d', '--build', '--timeout', '600', 'backend', 'frontend'],
                    cwd=LIVE_DIR, timeout=900)
        if not healthy():
            raise DeploymentError('Application health check failed after rollout')
    except Exception:
        print('Rollout failed; restoring previous source and containers', flush=True)
        sync_source(backup, LIVE_DIR)
        try:
            run_command(['docker', 'compose', 'up', '-d', '--build', '--timeout', '600',
                         'backend', 'frontend'], cwd=LIVE_DIR, timeout=900)
        except Exception as exc:
            print(f'Rollback container restart failed: {exc}', flush=True)
        raise
    marker = STATE_DIR / 'deployed_sha'
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(sha + '\n')
    os.replace(temporary, marker)
    try:
        prune_backups()
    except OSError as exc:
        print(f'Could not remove old source backup: {exc}', flush=True)
    print(f'Deployed {sha}', flush=True)


def main() -> None:
    """Poll main once, subject to the initial activation marker and CI gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='inspect main and CI without deploying')
    args = parser.parse_args()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another deployment check is running', flush=True)
            return
        if not args.check and not (STATE_DIR / 'enabled').exists():
            print('Initial deployment is not enabled; server source is preserved',
                  flush=True)
            return
        repo_dir = STATE_DIR / 'repository'
        sha = fetch_main(repo_dir)
        previous = STATE_DIR / 'deployed_sha'
        if previous.exists() and previous.read_text().strip() == sha:
            print(f'Already deployed {sha}', flush=True)
            return
        approved = approved_by_ci(sha)
        print(f'Main {sha}: CI {"passed" if approved else "not passed yet"}',
              flush=True)
        if approved and not args.check:
            if fetch_main(repo_dir) == sha:
                deploy(repo_dir, sha)
            else:
                print('Main changed during verification; retrying next cycle',
                      flush=True)


if __name__ == '__main__':
    main()
