import sys
from pathlib import Path

# The server runs as a script (python server/main.py), so its modules import
# each other as top-level modules.
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
sys.path.insert(0, str(Path(__file__).parent.parent))
