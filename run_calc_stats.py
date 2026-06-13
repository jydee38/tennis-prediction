import json, sys, os
# Ensure the betting_manager module can be imported
project_root = os.path.abspath(os.path.dirname(__file__))
python_dir = os.path.join(project_root, 'python')
if python_dir not in sys.path:
    sys.path.append(python_dir)

from betting_manager import calculate_stats

# Reconfigure stdout to use UTF-8 to avoid encoding errors on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
else:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

stats = calculate_stats()
print(json.dumps({
    "total_profit": stats["total_profit"],
    "total_stake": stats["total_stake"],
    "total_bets": stats["total_bets"],
    "won_bets": stats["won_bets"],
    "lost_bets": stats["lost_bets"],
    "pending_bets": stats["pending_bets"]
}, ensure_ascii=False, indent=2))
