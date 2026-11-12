"""Local single-user launcher; public deployment should run app.py directly."""
import os
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    env = dict(os.environ)
    env.setdefault("PORTFOLIO_STORAGE", "sqlite")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("app.py")),
                    "--server.address", "127.0.0.1", *sys.argv[1:]], env=env, check=True)
