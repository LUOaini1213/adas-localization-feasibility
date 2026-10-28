"""Three reference sensor suites.  Ranges are for a passenger-car target in clear weather.

Cited specifications (vendor product documents, accessed 2026-10-28):
  S81 Hesai AT128 product page: 210 m @ 10 % reflectivity, FOV 120 deg x 25.4 deg.
  S82 Bosch "Multi-camera system plus" one-pager: horizontal FOV > 190 deg, up to 6 cameras + 24 ultrasonic.
  S83 Bosch front radar (premium) one-pager: up to 302 m, horizontal +/-60 deg (seen only via a search
      summary; the PDF link returned 404 when fetched) -> used only as an upper sanity bound.
Everything else is a labelled assumption (A-16 .. A-20 below).  The suites are deliberately
conservative: the long-range radar is modelled with 200 m (not 302 m).
"""
from __future__ import annotations

from dataclasses import dataclass

from .requirements import VEH_LENGTH_M
from .sensors import Sensor

SUITE_ASSUMPTIONS = {
    "A-16": "前向毫米波雷达三个波瓣：200 m/±9°、100 m/±45°、60 m/±60°（保守于 S83 的 302 m/±60°）",
    "A-17": "角雷达两个波瓣：80 m/±45°、40 m/±75°；前角朝向 ±45°，后角朝向 ±135°",
    "A-18": "前视摄像头（100° 级）：150 m/±20°、60 m/±50°，安装在前保险杠后 1.9 m（风挡）",
    "A-19": "11V 方案摄像头：前视长焦 250 m/±15°；前视主摄 150 m/±30°、70 m/±60°；侧前 60 m/±50°（朝向 ±55°）；"
            "侧后 80 m/±50°（朝向 ±160°）；后视 80 m/±30°；4 个环视鱼眼 10 m/±95°（视场 > 190° 见 S82）",
    "A-20": "相对成本档按规则给出：1 + [雷达 ≥ 5] + [摄像头 ≥ 5] + [有激光雷达]；只表示相对高低，不是价格",
}

REAR_X = -VEH_LENGTH_M
HALF_W = 0.85


def _front_radar():
    return Sensor("前向雷达", "radar", 0.0, 0.0, 0.0, ((200.0, 9.0), (100.0, 45.0), (60.0, 60.0)), "A-16")


def _front_camera():
    return Sensor("前视摄像头", "camera", -1.9, 0.0, 0.0, ((150.0, 20.0), (60.0, 50.0)), "A-18")


def _corner_radars():
    lobes = ((80.0, 45.0), (40.0, 75.0))
    return [Sensor("左前角雷达", "radar", -0.3, HALF_W, 45.0, lobes, "A-17"),
            Sensor("右前角雷达", "radar", -0.3, -HALF_W, -45.0, lobes, "A-17"),
            Sensor("左后角雷达", "radar", REAR_X, HALF_W, 135.0, lobes, "A-17"),
            Sensor("右后角雷达", "radar", REAR_X, -HALF_W, -135.0, lobes, "A-17")]


def _eleven_cameras():
    cams = [Sensor("前视长焦", "camera", -1.9, 0.0, 0.0, ((250.0, 15.0),), "A-19"),
            Sensor("前视主摄", "camera", -1.9, 0.0, 0.0, ((150.0, 30.0), (70.0, 60.0)), "A-19"),
            Sensor("左侧前", "camera", -2.2, 0.95, 55.0, ((60.0, 50.0),), "A-19"),
            Sensor("右侧前", "camera", -2.2, -0.95, -55.0, ((60.0, 50.0),), "A-19"),
            Sensor("左侧后", "camera", -2.0, 0.95, 160.0, ((80.0, 50.0),), "A-19"),
            Sensor("右侧后", "camera", -2.0, -0.95, -160.0, ((80.0, 50.0),), "A-19"),
            Sensor("后视", "camera", REAR_X, 0.0, 180.0, ((80.0, 30.0),), "A-19")]
    fish = ((10.0, 95.0),)
    cams += [Sensor("环视前", "camera", 0.0, 0.0, 0.0, fish, "A-19；S82"),
             Sensor("环视后", "camera", REAR_X, 0.0, 180.0, fish, "A-19；S82"),
             Sensor("环视左", "camera", -2.0, 0.95, 90.0, fish, "A-19；S82"),
             Sensor("环视右", "camera", -2.0, -0.95, -90.0, fish, "A-19；S82")]
    return cams


def _lidar():
    return Sensor("激光雷达", "lidar", -1.9, 0.0, 0.0, ((210.0, 60.0),), "S81")


@dataclass(frozen=True)
class Suite:
    sid: str
    label: str
    sensors: tuple

    def count(self, modality: str) -> int:
        return sum(1 for s in self.sensors if s.modality == modality)

    @property
    def cost_tier(self) -> int:
        return 1 + int(self.count("radar") >= 5) + int(self.count("camera") >= 5) + int(self.count("lidar") > 0)


def reference_suites() -> list[Suite]:
    return [
        Suite("1V1R", "前视摄像头 + 前向雷达", (_front_camera(), _front_radar())),
        Suite("5R1V", "前视摄像头 + 前向雷达 + 4 角雷达", (_front_camera(), _front_radar(), *_corner_radars())),
        Suite("11V5R1L", "11 摄像头 + 5 雷达 + 1 激光雷达", (*_eleven_cameras(), _front_radar(), *_corner_radars(),
                                                         _lidar())),
    ]
