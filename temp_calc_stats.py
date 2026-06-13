import json, os, sys

# Add repository root to sys.path
import os
repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.append(repo_root)

from python.betting_manager import calculate_stats

stats = calculate_stats()
print(json.dumps(stats, indent=2, ensure_ascii=False))
