from python.data.odds_api import get_all_tennis_data
odds_data = get_all_tennis_data()
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
        b = match.get('bookmakers', [])
        if b:
            m = b[0].get('markets', [])
            if m:
                o = m[0].get('outcomes', [])
                if len(o) == 2:
                    print(f"ATP Match: {t_name} | {o[0].get('price')} vs {o[1].get('price')} | {match['home_team']} vs {match['away_team']}")
                else:
                    print(f"ATP Match (no outcomes): {t_name}")
            else:
                print(f"ATP Match (no markets): {t_name}")
        else:
            print(f"ATP Match (no bookmakers): {t_name}")
