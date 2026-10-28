"""Write the mirrored OpenDRIVE / OpenSCENARIO files (scenarios/) from sim/scenario.py.

Run:  python -X utf8 -B -I scripts/make_scenarios.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # -I does not add the project to sys.path

from sim.scenario import lane_ids_in_xosc, write_all  # noqa: E402

for path in write_all():
    extra = f"  lane ids {sorted(set(lane_ids_in_xosc(path)))}" if path.suffix == ".xosc" else ""
    print(f"{path.name}{extra}")
