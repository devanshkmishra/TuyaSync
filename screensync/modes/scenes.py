"""Hardware-executed DP25 scenes."""

from __future__ import annotations

import time

from screensync.light_service import LightService
from screensync.scenes import ScenePreset, compile_scene, encode_scene_data


class ScenesMode:
    name = "scenes"

    def __init__(self, light_service: LightService, scene: ScenePreset | None = None, scene_num: int = 1):
        self.light_service = light_service
        self.scene = scene
        self.scene_num = max(1, min(8, int(scene_num)))
        self.max_brightness = 1000
        self._running = False
        self._payload = None
        self._error = ""
        self._last_result = ""
        self._last_applied_at = 0.0

    def start(self) -> None:
        if self._running:
            return
        self.apply()

    def apply(self) -> None:
        if self.scene is None:
            raise RuntimeError("Choose a scene first")
        self._payload = compile_scene(self.scene, self.scene_num, self.max_brightness)
        try:
            results = self.light_service.execute("set_scene", self._payload)
            if not results or any(result != "sent" for result in results):
                self._last_result = ", ".join(results) if results else "no response"
                raise RuntimeError(f"The DS22000 did not accept the scene ({self._last_result})")
        except Exception as error:
            # A device can accept the mode switch before reporting a later
            # payload error; always leave a failed start in normal colour mode.
            self._error = str(error)
            self.light_service.execute("set_work_mode", "colour")
            raise
        self._running = True
        self._last_result = "sent"
        self._last_applied_at = time.time()
        self._error = ""

    def stop(self) -> None:
        if self._running:
            self.light_service.execute("set_work_mode", "colour")
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def reset_mode_state(self) -> None:
        self._payload = None
        self._error = ""
        self._last_result = ""
        self._last_applied_at = 0.0

    def set_scene(self, scene: ScenePreset, scene_num: int | None = None) -> None:
        self.scene = scene
        if scene_num is not None:
            self.scene_num = max(1, min(8, int(scene_num)))

    def set_max_brightness(self, value: float | int) -> None:
        self.max_brightness = max(0, min(1000, int(round(float(value)))))

    def diagnostics(self) -> dict[str, object]:
        return {
            "active_scene": self.scene.name if self._running and self.scene else "",
            "scene_num": self.scene_num,
            "max_brightness": self.max_brightness,
            "scene_units": len(self._payload.get("scene_units", [])) if self._payload else 0,
            "encoded_dp25_size": len(encode_scene_data(self._payload)) if self._payload else 0,
            "last_result": self._last_result,
            "last_applied_at": self._last_applied_at,
            "error": self._error,
        }
