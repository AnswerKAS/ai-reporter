"""Generate local Langfuse credentials and configure the backend once."""

from pathlib import Path
from secrets import token_hex


ROOT = Path(__file__).resolve().parents[1]
LANGFUSE_ENV = ROOT / 'langfuse' / '.env'
BACKEND_ENV = ROOT / 'backend' / '.env'


def main() -> None:
    """Create secrets without replacing existing keys or printing their values."""
    if not BACKEND_ENV.exists():
        raise SystemExit('Сначала создайте backend/.env из backend/.env.example.')

    if not LANGFUSE_ENV.exists():
        secrets = {
            key: token_hex(24) for key in (
                'LF_POSTGRES_PASSWORD', 'LF_CLICKHOUSE_PASSWORD',
                'LF_REDIS_PASSWORD', 'LF_MINIO_PASSWORD', 'LF_SALT',
                'LF_NEXTAUTH_SECRET', 'LF_ADMIN_PASSWORD')
        }
        secrets.update({
            'LF_ENCRYPTION_KEY': token_hex(32),
            'LF_PUBLIC_KEY': 'pk-lf-' + token_hex(16),
            'LF_SECRET_KEY': 'sk-lf-' + token_hex(32),
            'LF_ADMIN_EMAIL': 'admin@ai-reporter.local',
            'APP_DOCKER_NETWORK': 'ai-reporter_default',
        })
        LANGFUSE_ENV.write_text(''.join(f'{key}={value}\n' for key, value in secrets.items()))
        LANGFUSE_ENV.chmod(0o600)
    else:
        secrets = dict(line.split('=', 1) for line in LANGFUSE_ENV.read_text().splitlines()
                       if '=' in line and not line.startswith('#'))

    backend = BACKEND_ENV.read_text()
    additions = {
        'LANGFUSE_PUBLIC_KEY': secrets['LF_PUBLIC_KEY'],
        'LANGFUSE_SECRET_KEY': secrets['LF_SECRET_KEY'],
        'LANGFUSE_BASE_URL': 'http://langfuse-web:3000',
    }
    existing = {line.split('=', 1)[0].strip() for line in backend.splitlines()
                if '=' in line and not line.lstrip().startswith('#')}
    missing = {key: value for key, value in additions.items() if key not in existing}
    if missing:
        backend += '\n# Local Langfuse agent traces\n'
        backend += ''.join(f'{key}={value}\n' for key, value in missing.items())
        BACKEND_ENV.write_text(backend)
        BACKEND_ENV.chmod(0o600)
    print('Langfuse настроен; секреты сохранены локально и не показаны.')


if __name__ == '__main__':
    main()
