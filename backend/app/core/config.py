import os
from pathlib import Path
from urllib.parse import unquote

import certifi
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / '.env')

# Схема clickhouse:// у пользовательского сервера отдаёт только HTTPS.
# secure по умолчанию = True; отключить можно переменной CLICKHOUSE_SECURE=false
# (или схемой clickhouses:// — безусловный TLS, clickhouse:// без неё — plain HTTP).
_secure_env = os.environ.get('CLICKHOUSE_SECURE', 'true').strip().lower()


class DbConfig:
    def __init__(self, url: str | None) -> None:
        self.raw = (url or '').strip()
        self.host = 'localhost'
        self.port = 8123
        self.user = 'default'
        self.password = ''
        self.database = 'default'
        self.secure = _secure_env in ('1', 'true', 'yes', 'on')
        self.verify = True
        self.ca_cert = certifi.where()
        if self.raw:
            self._parse()

    def _parse(self) -> None:
        scheme, _, rest = self.raw.partition('://')
        if not rest:
            return
        self.secure = scheme == 'clickhouses' or self.secure
        authority, _, path = rest.partition('/')
        if '@' in authority:
            userinfo, _, hostport = authority.rpartition('@')
            if ':' in userinfo:
                user, _, password = userinfo.partition(':')
                self.user = unquote(user)
                self.password = unquote(password)
            else:
                self.user = unquote(userinfo)
        else:
            hostport = authority
        if ':' in hostport:
            host, _, port = hostport.rpartition(':')
            self.host = host
            self.port = int(port)
        else:
            self.host = hostport
        if path:
            self.database = unquote(path.rstrip('/'))

    @property
    def configured(self) -> bool:
        return bool(self.raw)

    @property
    def client_options(self) -> dict:
        return {
            'host': self.host,
            'port': self.port,
            'username': self.user,
            'password': self.password,
            'database': self.database or 'default',
            'secure': self.secure,
            'verify': self.verify,
            'ca_cert': self.ca_cert,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f'DbConfig(host={self.host}, port={self.port}, database={self.database}, secure={self.secure})'


DB = DbConfig(os.environ.get('DATABASE_URL'))