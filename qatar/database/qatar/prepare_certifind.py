import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import write_certifind_csvs
raw = json.load(open(Path(__file__).parent / "gab_raw.json"))
bodies, accs, scopes = [], [], []  # no 17021-1 entries in register
write_certifind_csvs(Path(__file__).parents[2] / "data/gab-qatar", bodies, accs, scopes)
print("Excluded: 7 GHG VVBs (ISO 14065), IB bodies (ISO/IEC 17020)")
