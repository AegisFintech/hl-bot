"""Push current branch using .env credentials without tokens in argv or remote URLs."""
import os
import subprocess
import tempfile
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / '.env')
with tempfile.TemporaryDirectory() as directory:
    askpass = Path(directory) / 'askpass'
    askpass.write_text('#!/usr/bin/python3\nimport os,sys\nprint(os.environ["PUSH_USER"] if "Username" in sys.argv[1] else os.environ["PUSH_TOKEN"])\n')
    askpass.chmod(0o700)
    env = dict(os.environ, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT='0',
               PUSH_USER=values.get('GIT_USER') or 'x-access-token', PUSH_TOKEN=values.get('GIT_PAT') or '')
    subprocess.run(['git', 'push', 'origin', 'HEAD'], cwd=root, env=env, check=True)
