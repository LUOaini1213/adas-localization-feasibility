"""P9 mirrored left-hand-traffic (LHT) vs right-hand-traffic (RHT) simulation check.

scenario.py        - traffic-side-neutral scenario specs, mirroring (lane index -> lane id), xodr/xosc writer
esmini_backend.py  - esmini v3.10.2 through esminiLib (ctypes); adapted from the P5 harness
python_backend.py  - the same storyboard re-integrated in Python (cross-check, and tests without esmini)
controller.py      - simple ego controller: ACC + cut-in detection + no-undertaking rule + system-initiated
                     lane change with a UN R171 6.2.4 rear check; all side-dependent logic goes through
                     one parameter (overtaking side sign)
runner.py          - closed loop, metrics, run lists
"""
