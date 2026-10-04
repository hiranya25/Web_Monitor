import os
import sys

# Path to Python 3.12 virtualenv interpreter
VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")

# Re-exec under Python 3.12 if currently running under system Python
if sys.executable != VENV_PYTHON and os.path.exists(VENV_PYTHON):
    os.execlp(VENV_PYTHON, VENV_PYTHON, *sys.argv)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

venv_site = os.path.join(BASE_DIR, "venv", "lib", "python3.12", "site-packages")
if os.path.exists(venv_site) and venv_site not in sys.path:
    sys.path.insert(0, venv_site)

from a2wsgi import ASGIMiddleware
from app.main import app
from app.scheduler import start_scheduler

start_scheduler()

application = ASGIMiddleware(app)
