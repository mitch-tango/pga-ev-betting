#!/usr/bin/env python3
"""
Start the PGA +EV Discord bot.

Usage:
    python scripts/run_bot.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.discord_bot.bot import run

if __name__ == "__main__":
    run()
