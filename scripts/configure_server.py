"""Create a server configuration without overwriting an existing deployment."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.config import Settings


def main():
    parser = argparse.ArgumentParser(description='Configure the open shared web edition.')
    parser.add_argument('--origin', required=True, help='Public origin, e.g. https://bible.example.com')
    parser.add_argument('--port', type=int, default=8000, help='Loopback port used by Nginx')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    origin = args.origin.rstrip('/')
    if any(c.isspace() for c in origin) or any(c in origin for c in "\"'#$\\"):
        parser.error('origin must be an HTTP(S) origin without whitespace or shell characters')
    try:
        Settings(deployment='server', public_origin=origin).validate()
    except ValueError as error:
        parser.error(str(error))
    target = ROOT / '.env'
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        parser.error('.env already exists; preserve it for updates or edit it explicitly')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(f'DEPLOYMENT_MODE=server\nPUBLIC_ORIGIN={origin}\nAPP_PORT={args.port}\nPORT={args.port}\n')
    print('Created .env. The web edition is open to all visitors with shared read/write access.')


if __name__ == '__main__':
    main()
