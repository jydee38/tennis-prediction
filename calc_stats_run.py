import sys, os, json

# Add the python package directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
package_dir = os.path.join(current_dir, 'python')
sys.path.append(package_dir)

from betting_manager import calculate_stats

stats = calculate_stats()
print(json.dumps(stats, ensure_ascii=False, indent=2))
