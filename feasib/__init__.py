"""P9 sensor-suite feasibility calculator.

requirements.py  - function requirements -> required detection range / FOV / latency budget
                   (AEB, ACC, lane-change rear coverage per UN R171 6.2.4 / UN R79 5.6.4.7, cut-in FOV)
sensors.py       - sensor model (range lobes, mounting), target-class factors, rain degradation
suites.py        - reference sensor suites (1V1R, 5R1V, 11V5R1L) with cited specs or labelled assumptions
feasibility.py   - checks every requirement against every suite (clear weather and rain)
"""
