"""Pytest configuration - adds src to path."""
import sys
from pathlib import Path

# Add project root to path so 'from src.x import y' works
sys.path.insert(0, str(Path(__file__).parent.parent))
