import json, sys, os

project_root = os.path.abspath(os.path.dirname(__file__))
python_dir = os.path.join(project_root, 'python')
if python_dir not in sys.path:
    sys.path.append(python_dir)

from betting_manager import calculate_stats

stats = calculate_stats()
print('Total Profit:', stats['total_profit'])
print('Total Bets:', stats['total_bets'])
print('Won Bets:', stats['won_bets'])
print('Lost Bets:', stats['lost_bets'])
print('Pending Bets:', stats['pending_bets'])
