import json, sys, os
# Add project python package to path
project_root = os.path.abspath(os.path.dirname(__file__))
python_dir = os.path.join(project_root, 'python')
if python_dir not in sys.path:
    sys.path.append(python_dir)

from betting_manager import calculate_stats

stats = calculate_stats()
output_path = os.path.join(project_root, 'stats_output.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)
print(f'Stats written to {output_path}')
