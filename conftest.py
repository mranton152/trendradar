"""Корень проекта попадает в sys.path, чтобы работал `import contracts.schemas`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
