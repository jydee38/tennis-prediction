import json
from python.betting_manager import calculate_stats

stats = calculate_stats()
with open('stats_output.json', 'w', encoding='utf-8') as f:
    json.dump(stats, f, indent=2, ensure_ascii=False)
print('Stats written to stats_output.json')
