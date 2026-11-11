"""esmini v3.10.2 world backend through esminiLib (ctypes).

Adapted from the P5 harness (LUOaini1213/r152-aeb-scenario-tests, aebtest/backends.py, EsminiBackend): same library
loading, same ParameterDeclaration callback to hand the Ego to the ExternalController, same rule of
starting esmini from the scenarios folder with relative ASCII file names (esmini cannot open the
non-ASCII absolute project path).  Changes in this repo (P9): several targets, the Ego is reported
with SE_ReportObjectPosXYH (it can move laterally), and every object state is returned.
"""
from __future__ import annotations

import ctypes as C
import os

from .scenario import SCEN_DIR


class _State(C.Structure):          # SE_ScenarioObjectState, esminiLib.hpp v3.10.2
    _fields_ = [("id", C.c_int), ("model_id", C.c_int), ("ctrl_type", C.c_int), ("timestamp", C.c_double),
                ("x", C.c_double), ("y", C.c_double), ("z", C.c_double),
                ("h", C.c_double), ("p", C.c_double), ("r", C.c_double),
                ("roadId", C.c_uint32), ("junctionId", C.c_uint32), ("t", C.c_double), ("laneId", C.c_int),
                ("laneOffset", C.c_double), ("s", C.c_double), ("speed", C.c_double),
                ("centerOffsetX", C.c_double), ("centerOffsetY", C.c_double), ("centerOffsetZ", C.c_double),
                ("width", C.c_double), ("length", C.c_double), ("height", C.c_double),
                ("objectType", C.c_int), ("objectCategory", C.c_int),
                ("wheel_angle", C.c_double), ("wheel_rot", C.c_double), ("visibilityMask", C.c_int)]


class EsminiBackend:
    name = "esmini"
    _lib = None

    def __init__(self, lib_path: str):
        if EsminiBackend._lib is None:
            lib = C.CDLL(lib_path)
            lib.SE_InitWithArgs.argtypes = [C.c_int, C.POINTER(C.c_char_p)]
            lib.SE_InitWithArgs.restype = C.c_int
            lib.SE_StepDT.argtypes = [C.c_double]
            lib.SE_StepDT.restype = C.c_int
            lib.SE_GetSimulationTime.restype = C.c_double
            lib.SE_GetIdByName.argtypes = [C.c_char_p]
            lib.SE_GetIdByName.restype = C.c_int
            lib.SE_GetObjectState.argtypes = [C.c_int, C.POINTER(_State)]
            lib.SE_GetObjectState.restype = C.c_int
            lib.SE_ReportObjectPosXYH.argtypes = [C.c_int, C.c_double, C.c_double, C.c_double]
            lib.SE_ReportObjectPosXYH.restype = C.c_int
            lib.SE_ReportObjectSpeed.argtypes = [C.c_int, C.c_double]
            lib.SE_ReportObjectSpeed.restype = C.c_int
            lib.SE_SetParameterBool.argtypes = [C.c_char_p, C.c_bool]
            lib.SE_SetParameterBool.restype = C.c_int
            lib.SE_GetObjectNumberOfCollisions.argtypes = [C.c_int]
            lib.SE_GetObjectNumberOfCollisions.restype = C.c_int
            lib.SE_Close.restype = None
            EsminiBackend._cb_type = C.CFUNCTYPE(None, C.c_void_p)
            lib.SE_RegisterParameterDeclarationCallback.argtypes = [EsminiBackend._cb_type, C.c_void_p]
            lib.SE_SetOptionPersistent.argtypes = [C.c_char_p]
            lib.SE_SetOptionPersistent(b"disable_stdout")
            EsminiBackend._lib = lib
        self.lib = EsminiBackend._lib
        self._st = _State()
        self._cwd = None

    def start(self, xosc: str, actor_names: list[str], dt: float, log_stem: str | None = None) -> None:
        lib = self.lib

        def on_params(_):
            lib.SE_SetParameterBool(b"ExtCtrl", True)     # hand the Ego to the ExternalController

        self._cb = EsminiBackend._cb_type(on_params)
        lib.SE_RegisterParameterDeclarationCallback(self._cb, None)
        args = ["esmini", "--osc", xosc, "--headless", "--fixed_timestep", f"{dt}", "--collision",
                "--disable_stdout"]
        if log_stem:
            os.makedirs(SCEN_DIR.parent / "results" / "esmini_logs", exist_ok=True)
            rel = f"../results/esmini_logs/{log_stem}"
            args += ["--csv_logger", f"{rel}.csv", "--logfile_path", f"{rel}.log.txt"]
        else:
            args += ["--disable_log"]
        self._cwd = os.getcwd()
        os.chdir(SCEN_DIR)
        argv = (C.c_char_p * len(args))(*[a.encode("ascii") for a in args])
        if lib.SE_InitWithArgs(len(args), argv) != 0:
            os.chdir(self._cwd)
            raise RuntimeError(f"esmini failed to load {xosc}")
        self.ego = lib.SE_GetIdByName(b"Ego")
        self.ids = {n: lib.SE_GetIdByName(n.encode()) for n in actor_names}
        e = self._state(self.ego)
        if e.ctrl_type != 1:
            raise RuntimeError("Ego is not under the ExternalController (ctrl_type != 1)")
        self.ego_init = (e.x, e.y, e.speed)
        self.collision = False

    def _state(self, oid: int) -> _State:
        self.lib.SE_GetObjectState(oid, C.byref(self._st))
        return _State.from_buffer_copy(self._st)

    def objects(self) -> dict[str, dict]:
        out = {}
        for n, oid in self.ids.items():
            s = self._state(oid)
            out[n] = {"x": s.x, "y": s.y, "v": s.speed, "h": s.h, "lane_id": s.laneId,
                      "cx": s.centerOffsetX, "length": s.length, "width": s.width}
        return out

    def advance(self, dt: float, x: float, y: float, h: float, v: float) -> None:
        self.lib.SE_ReportObjectPosXYH(self.ego, x, y, h)
        self.lib.SE_ReportObjectSpeed(self.ego, v)
        self.lib.SE_StepDT(dt)
        if not self.collision and self.lib.SE_GetObjectNumberOfCollisions(self.ego) > 0:
            self.collision = True

    def time(self) -> float:
        return self.lib.SE_GetSimulationTime()

    def close(self) -> None:
        self.lib.SE_Close()
        if self._cwd:
            os.chdir(self._cwd)
            self._cwd = None
