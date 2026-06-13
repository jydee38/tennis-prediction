import sys
sys.path.insert(0, '.')

from python.app_logic import find_player_by_name, get_data_and_train_model

print("Loading ATP data...")
df, model, features, db_atp = get_data_and_train_model(tour="ATP")
print(f"ATP DB size: {len(db_atp)}")

print("\nLoading WTA data...")
df_wta, model_wta, features_wta, db_wta = get_data_and_train_model(tour="WTA")
print(f"WTA DB size: {len(db_wta)}")

# Test cases
test_atp = [
    ("Tiafoe F.(6)", db_atp),
    ("Shelton B.(1)", db_atp),
    ("Auger Aliassime F.(1)", db_atp),
    ("Griekspoor T.(6)", db_atp),
    ("Medvedev D.(3)", db_atp),
    ("Mpetshi Perricard G.", db_atp),
]

test_wta = [
    ("Chwalinska.Maja", db_wta),
    ("Mpetshi Perricard D.", db_wta),
    ("Andreeva M.", db_wta),
    ("Rybakina E.", db_wta),
]

print("\n--- TEST ATP (should NOT match WTA players) ---")
for name, db in test_atp:
    result = find_player_by_name(name, db)
    if result:
        print(f"  OK: '{name}' => '{result.name}'")
    else:
        print(f"  MISS: '{name}' => None")

print("\n--- TEST WTA (should NOT match ATP players) ---")
for name, db in test_wta:
    result = find_player_by_name(name, db)
    if result:
        print(f"  OK: '{name}' => '{result.name}'")
    else:
        print(f"  MISS: '{name}' => None")

# Cross-check: Giovanni should NOT be found in WTA DB
print("\n--- CROSS-CHECK: Mpetshi Perricard G. in WTA DB (should be None) ---")
result = find_player_by_name("Mpetshi Perricard G.", db_wta)
if result:
    print(f"  BUG: Found '{result.name}' in WTA DB!")
else:
    print("  OK: Not found in WTA DB (correct!)")
