"""Screen sync: ambient colour from a display."""

from __future__ import annotations

from screensync.gui.controller import ALGORITHM_GUIDE, PRIMARY_ALGORITHMS, RESPONSE_GUIDE, AppController
from screensync.gui.pages.common import ModeHero, pct
from screensync.gui.widgets import Card, ChoiceRow, Page, Section, SegmentRow, SliderRow, ToggleRow, rgb_text

ALGORITHM_NAMES = {"Saturated": "Saturated", "Edge": "Edges", "Vibrant": "Vibrant", "Legacy": "Classic"}


def _seconds(value: float) -> str:
    return f"{value:.2f} s"


def _times(value: float) -> str:
    return f"{value:.2f}×"


class ScreenPage(Page):
    def __init__(self, controller: AppController):
        super().__init__("Screen", "The light follows the colours on your display, like bias lighting for your desk.")
        self.controller = controller
        s = controller.screen
        self.sliders: dict[str, SliderRow] = {}
        self.toggles: dict[str, ToggleRow] = {}

        self.hero = ModeHero(controller, "screen")
        self.add(self.hero)

        essentials = Card("Essentials")
        self.monitor = ChoiceRow("Display", "Which screen the colour comes from.", [text for _, text in controller.monitor_options], controller.monitor_label())
        self.monitor.changed.connect(self._monitor)
        essentials.add(self.monitor)
        self.algorithm = SegmentRow(
            "Colour style",
            [(key, ALGORITHM_NAMES[key]) for key in PRIMARY_ALGORITHMS],
            s.algorithm,
            lambda key: f"{ALGORITHM_GUIDE[key][0]}. {ALGORITHM_GUIDE[key][1]}",
        )
        self.algorithm.changed.connect(lambda value: controller.update_screen(algorithm=value))
        essentials.add(self.algorithm)
        self.response = SegmentRow(
            "Response",
            [(key, key) for key in RESPONSE_GUIDE],
            s.response_profile,
            lambda key: f"{RESPONSE_GUIDE[key][0]}. {RESPONSE_GUIDE[key][1]}",
        )
        self.response.changed.connect(lambda value: controller.update_screen(response_profile=value))
        essentials.add(self.response)
        essentials.add(self._slider("maximum_brightness", "Maximum brightness", "The brightest the light gets while following the screen.", 10, 100, 1, pct))
        essentials.add(self._toggle("ignore_black_bars", "Ignore black bars", "Leave letterbox bars out of the colour without cropping dark scenes."))
        self.add(essentials)

        motion = Section("Brightness and motion", "Shape how bright the light gets and how smoothly it moves.")
        motion.add(self._slider("minimum_brightness", "Minimum brightness", "The lowest level used for anything that isn't a black scene.", 0, 50, 1, pct))
        motion.add(self._slider("brightness_gamma", "Brightness curve", "Below 1 lifts dim scenes; above 1 keeps the light low until the screen is bright.", 0.4, 2.5, 0.05, lambda v: f"{v:.2f}"))
        motion.add(self._slider("brightness_attack", "Brighten speed", "How quickly the light brightens.", 0.01, 1.0, 0.01, _seconds))
        motion.add(self._slider("brightness_release", "Dim speed", "How gently the light fades.", 0.05, 2.0, 0.05, _seconds))
        motion.add(self._slider("color_smoothing", "Colour smoothing", "How long colour changes take to settle.", 0.01, 1.2, 0.01, _seconds))
        motion.add(self._slider("color_deadband", "Ignore tiny changes", "Skip colour changes smaller than this to prevent flicker.", 0, 30, 1, lambda v: f"{v:.0f}"))
        motion.add(self._slider("update_rate", "Maximum update rate", "Upper limit; calm scenes automatically send less.", 1, 15, 1, lambda v: f"{v:.0f} Hz"))
        self.add(motion)

        dark = Section("Dark scenes", "Keep black frames and letterboxing from affecting the light.")
        dark.add(self._slider("black_scene_threshold", "Black scene level", "Frames darker than this count as black.", 0, 60, 1, lambda v: f"{v:.0f}"))
        dark.add(self._slider("black_bar_threshold", "Black bar level", "How dark the screen edges must be to count as bars.", 0, 60, 1, lambda v: f"{v:.0f}"))
        dark.add(self._toggle("turn_off_on_black", "Turn off during long black scenes", "Power the light off when the screen stays black."))
        dark.add(self._slider("black_off_delay", "Turn-off delay", "How long a black scene must last first.", 1, 20, 0.5, lambda v: f"{v:.1f} s"))
        self.add(dark)

        overlays = Section("Subtitles and windows", "Stop text and bright static interfaces from overpowering the scene.")
        overlays.add(self._toggle("reduce_static_ui", "Reduce subtitles and static UI", "Prefer moving content over things that stay still."))
        overlays.add(self._slider("static_ui_weight", "Static content influence", None, 0.05, 1.0, 0.05, _times))
        overlays.add(self._slider("white_background_weight", "White background influence", "How much large white areas, like documents, count.", 0.02, 1.0, 0.02, _times))
        self.analysis = SegmentRow("Analysis detail", [("64", "Fast · 64 px"), ("96", "Detailed · 96 px")], str(s.analysis_width))
        self.analysis.changed.connect(lambda value: controller.update_screen(analysis_width=int(value)))
        overlays.add(self.analysis)
        self.add(overlays)

        white = Section("White LEDs and output", "Hardware options for the DS22000.")
        white.add(self._toggle("use_dedicated_white", "Use white LEDs for neutral scenes", "Switches to the dedicated white channel when the screen is steady and colourless."))
        white.add(self._slider("white_enter_delay", "Switch to white after", None, 0.2, 2.0, 0.1, lambda v: f"{v:.1f} s"))
        white.add(self._slider("white_exit_delay", "Switch back to colour after", None, 0.1, 1.5, 0.1, lambda v: f"{v:.1f} s"))
        self.transport = SegmentRow(
            "Colour command",
            [("DP28", "Gradient (DP28)"), ("DP24", "Direct (DP24)")],
            s.output_transport,
            lambda key: "Recommended. Smooth realtime colour with on-device gradients." if key == "DP28" else "Sends plain colour values. Use only if gradients misbehave.",
        )
        self.transport.changed.connect(lambda value: controller.update_screen(output_transport=value))
        white.add(self.transport)
        self.add(white)
        self.finish()

        controller.screenSettingsChanged.connect(self.sync)

    def _slider(self, key, title, description, minimum, maximum, step, fmt) -> SliderRow:
        row = SliderRow(title, description, minimum, maximum, getattr(self.controller.screen, key), step, fmt)
        row.valueChanged.connect(lambda value, k=key: self.controller.update_screen(**{k: value}))
        self.sliders[key] = row
        return row

    def _toggle(self, key, title, description) -> ToggleRow:
        row = ToggleRow(title, description, bool(getattr(self.controller.screen, key)))
        row.toggled.connect(lambda checked, k=key: self.controller.update_screen(**{k: checked}))
        self.toggles[key] = row
        return row

    def _monitor(self, text: str) -> None:
        index = next((value for value, label in self.controller.monitor_options if label == text), 1)
        self.controller.update_screen(monitor_index=index)

    def sync(self) -> None:
        s = self.controller.screen
        for key, row in self.sliders.items():
            row.set_value(getattr(s, key))
        for key, row in self.toggles.items():
            row.set_checked(bool(getattr(s, key)))
        self.monitor.set_value(self.controller.monitor_label())
        self.algorithm.set_value(s.algorithm)
        self.response.set_value(s.response_profile)
        self.analysis.set_value(str(s.analysis_width))
        self.transport.set_value(s.output_transport)

    def on_mode(self, mode: str) -> None:
        self.hero.set_running(mode == "screen")

    def refresh(self, snapshot: dict, info: dict) -> None:
        running = self.controller.active_mode == "screen"
        rgb = snapshot.get("final_rgb", (0, 0, 0))
        level = float(snapshot.get("final_brightness", 0.0))
        self.hero.orb.set_state(rgb, level, running)
        s = self.controller.screen
        if running:
            display = self.controller.monitor_label().split(" — ")[0]
            if snapshot.get("is_black"):
                state = "Black scene · holding"
            else:
                state = f"{rgb_text(rgb)} at {level * 100:.0f}%"
            self.hero.set_text(
                f"Following {display}",
                f"{state}\n{ALGORITHM_NAMES[s.algorithm]} · {s.response_profile} · {snapshot.get('lighting_hz', 0.0):.1f} updates/s · {snapshot.get('capture_fps', 0.0):.0f} fps",
            )
        else:
            self.hero.set_text("Screen sync is off", f"{ALGORITHM_NAMES.get(s.algorithm, s.algorithm)} style · {s.response_profile} response · {self.controller.monitor_label()}")
