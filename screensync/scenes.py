"""Friendly scene presets and the DS22000 DP25 scene_data_v2 compiler."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SceneStop:
    color: tuple[int, int, int]
    brightness: int = 700
    transition_duration: float = 4.0
    hold_duration: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            tuple(int(max(0, min(255, value))) for value in data.get("color", (128, 128, 128))),
            int(max(0, min(1000, data.get("brightness", 700)))),
            float(max(0, min(100, data.get("transition_duration", 4.0)))),
            float(max(0, min(100, data.get("hold_duration", 0.0)))),
        )


@dataclass
class ScenePreset:
    name: str
    stops: list[SceneStop]
    loop: bool = True
    builtin: bool = True

    def to_dict(self):
        return {"name": self.name, "stops": [stop.to_dict() for stop in self.stops], "loop": self.loop, "builtin": self.builtin}

    @classmethod
    def from_dict(cls, data):
        return cls(str(data.get("name", "Custom scene")), [SceneStop.from_dict(stop) for stop in data.get("stops", [])], bool(data.get("loop", True)), bool(data.get("builtin", False)))


def _stop(rgb, brightness, transition, hold=0):
    return SceneStop(tuple(rgb), brightness, transition, hold)


BUILTIN_SCENES = (
    ScenePreset("Vaporwave", [_stop((255, 35, 165), 720, 7), _stop((142, 45, 255), 740, 7), _stop((38, 215, 255), 700, 7), _stop((95, 35, 210), 700, 7)]),
    ScenePreset("Cyberpunk", [_stop((15, 50, 225), 720, 4), _stop((130, 35, 255), 760, 4), _stop((255, 25, 155), 740, 4)]),
    ScenePreset("Aurora", [_stop((5, 95, 105), 580, 9), _stop((15, 210, 125), 620, 9), _stop((30, 225, 225), 600, 9), _stop((125, 75, 235), 560, 9)]),
    ScenePreset("Sunset", [_stop((255, 170, 35), 680, 5), _stop((255, 90, 35), 720, 5), _stop((245, 65, 105), 700, 5), _stop((150, 35, 180), 620, 5)]),
    ScenePreset("Ocean", [_stop((10, 30, 115), 620, 7), _stop((20, 90, 220), 680, 7), _stop((20, 190, 205), 650, 7), _stop((0, 215, 255), 650, 7)]),
    ScenePreset("Dream", [_stop((150, 120, 230), 450, 8), _stop((245, 145, 190), 460, 8), _stop((135, 220, 230), 460, 8)]),
    ScenePreset("City Pop", [_stop((230, 30, 170), 720, 3), _stop((255, 120, 190), 700, 3), _stop((20, 220, 240), 720, 3), _stop((130, 40, 235), 720, 3)]),
)


def _rgb_to_hsv(rgb):
    import colorsys
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    return round(hue * 360), round(saturation * 1000), round(value * 1000)


def compile_scene(scene: ScenePreset, scene_num: int = 1, max_brightness: int = 1000) -> dict:
    if not 1 <= scene_num <= 8:
        raise ValueError("The DS22000 accepts scene numbers from 1 to 8")
    if not scene.stops:
        raise ValueError("A scene must contain at least one colour stop")
    if len(scene.stops) > 64:
        raise ValueError("A scene cannot contain more than 64 stops")
    max_brightness = max(0, min(1000, int(max_brightness)))
    units = []
    for stop in scene.stops:
        hue, saturation, value = _rgb_to_hsv(stop.color)
        stop_brightness = max(0, min(1000, int(stop.brightness)))
        # DP25 carries RGB value and dedicated-white brightness separately.
        # These scenes are RGB-only: putting the requested level in `bright`
        # makes the DS22000 light its CCT/white channel instead of dimming RGB.
        value = min(max_brightness, round(value * stop_brightness / 1000))
        duration = int(round(max(0, min(100, stop.transition_duration))))
        hold = int(round(max(0, min(100, stop.hold_duration))))
        mode = "static" if duration == 0 else "gradient"
        units.append({
            "unit_change_mode": mode,
            "unit_switch_duration": hold,
            "unit_gradient_duration": duration,
            "h": max(0, min(360, hue)),
            "s": max(0, min(1000, saturation)),
            "v": max(0, min(1000, value)),
            "bright": 0,
            "temperature": 0,
        })
    return {"scene_num": scene_num, "scene_units": units}


def encode_scene_data(scene_data: dict) -> str:
    """Encode scene_data_v2 for the DS22000's local DP25 protocol."""
    scene_num = int(scene_data.get("scene_num", 1))
    if not 1 <= scene_num <= 8:
        raise ValueError("The DS22000 accepts scene numbers from 1 to 8")
    units = scene_data.get("scene_units", [])
    if not units:
        raise ValueError("A scene must contain at least one colour stop")
    mode_values = {"static": 0, "jump": 1, "gradient": 2}
    encoded = [f"{scene_num:02x}"]
    for unit in units:
        mode = unit.get("unit_change_mode", "static")
        if mode not in mode_values:
            raise ValueError(f"Unsupported scene transition mode: {mode}")
        encoded.append(
            f"{max(0, min(100, int(unit.get('unit_switch_duration', 0)))):02x}"
            f"{max(0, min(100, int(unit.get('unit_gradient_duration', 0)))):02x}"
            f"{mode_values[mode]:02x}"
            f"{max(0, min(360, int(unit.get('h', 0)))):04x}"
            f"{max(0, min(1000, int(unit.get('s', 0)))):04x}"
            f"{max(0, min(1000, int(unit.get('v', 0)))):04x}"
            f"{max(0, min(1000, int(unit.get('bright', 0)))):04x}"
            f"{max(0, min(1000, int(unit.get('temperature', 0)))):04x}"
        )
    return "".join(encoded)


def load_custom_scenes(path: Path) -> list[ScenePreset]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return []
    return [ScenePreset.from_dict(item) for item in data if isinstance(item, dict)]


def save_custom_scenes(path: Path, scenes: list[ScenePreset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([scene.to_dict() for scene in scenes], indent=2))
