"""GAB (Qatar) register scrape. gab.qa is not reachable from the workspace; the register
(https://www.gab.qa/accredited-bodies/) was read in the browser on 2026-11-09.
Tables #qms, #ems, #ohsms (ISO/IEC 17021-1) contain no rows. Only #ghg (ISO 14065 VVBs) and #ib
(ISO/IEC 17020) are populated -> out of scope."""
import json
REGISTER = {"qms": [], "ems": [], "ohsms": []}
if __name__ == "__main__":
    json.dump(REGISTER, open("gab_raw.json", "w"))
