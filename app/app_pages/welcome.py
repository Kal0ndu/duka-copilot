"""Public landing page for visitors who are not logged in."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.auth_theme import render_landing

render_landing()
