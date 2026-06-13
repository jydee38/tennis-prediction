import json, os, sys
import os
repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.append(repo_root)
from python.betting_manager import calculate_stats
stats = calculate_stats()
output_path = os.path.join(repo_root, 'stats_output.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)
print(f'Stats written to {output_path}')
