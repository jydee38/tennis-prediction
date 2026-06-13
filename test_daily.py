from python.data.odds_api import get_all_tennis_data
odds_data = get_all_tennis_data()
print(f"Total odds fetched: {len(odds_data.get('odds', []))}")
atp_matches = 0
for match in odds_data.get('odds', []):
    t_name = match.get('sport_title', 'Tennis')
    t_name_low = t_name.lower()
    if any(x in t_name_low for x in ["challenger", "itf", "srx", "utr", "exhibition", "m15", "m25", "w15", "w25", "w35", "w50", "w75", "w100", "future"]):
        continue
    sport_title_upper = str(match.get('sport_title', '')).upper()
    t_name_upper = str(t_name).upper()
    is_wta = 'WTA' in sport_title_upper or 'WOMEN' in sport_title_upper or 'WTA' in t_name_upper or 'WOMEN' in t_name_upper
    if not is_wta:
        atp_matches += 1
        print(f"ATP Match: {t_name} | {match['home_team']} vs {match['away_team']}")
print(f"Total ATP matches passing filters: {atp_matches}")
