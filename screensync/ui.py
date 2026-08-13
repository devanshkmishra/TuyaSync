"""Minimal light-mode control surface for the Wipro ambient light."""

from __future__ import annotations

import json
import queue
import tkinter as tk
import webbrowser
from io import BytesIO
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from platformdirs import user_data_dir
from PIL import Image, ImageTk

from screensync.audio.factory import system_audio_backend
from screensync.light_profiles import LightProfile, LightProfileStore, ProfileStoreError
from screensync.light_service import LightService
from screensync.modes.album_art import AlbumArtMode, AlbumArtSettings
from screensync.modes.manager import ModeManager, ModeTransitionError
from screensync.modes.music import MusicMode, MusicSettings, PALETTES
from screensync.modes.scenes import ScenesMode
from screensync.now_playing.factory import spotify_backend
from screensync.scenes import BUILTIN_SCENES, ScenePreset, SceneStop, load_custom_scenes, save_custom_scenes
from screensync.screen_sync.ambient import RuntimeMetrics, ScreenProcessor, SyncSettings
from screensync.screen_sync.bulb_factory import BulbFactory
from screensync.screen_sync.config_manager import ConfigManager
from screensync.screen_sync.coordinator import Coordinator


APP_NAME = "TuyaSync"
APP_AUTHOR = "TuyaSync"
PRIMARY_ALGORITHMS = ("Legacy", "Saturated", "Edge", "Vibrant")
ALGORITHM_GUIDE = {
    "Legacy": ("Classic", "The original weighted average. Calm and familiar, but less vivid on mixed scenes; use it mainly to compare with the older behavior."),
    "Saturated": ("Recommended", "Favors colorful scene content and down-weights grey UI, subtitles, and isolated white pixels. The best starting point for most movies, games, and desktop use."),
    "Edge": ("Outer edges", "Reads mostly the outer part of the display, so centered text and application UI matter less. Often feels more like cinematic ambient lighting."),
    "Vibrant": ("Dominant color", "Chooses a strong quantized color instead of averaging everything together. Punchy for animation and colorful games; less faithful on deliberately mixed scenes."),
}
RESPONSE_GUIDE = {
    "Responsive": ("Fast", "Uses shorter transitions and reacts quickly to normal changes. Pick this when you want the light to follow cuts and movement closely."),
    "Balanced": ("Recommended", "Smooths small changes but accelerates on major scene cuts. This is the best everyday compromise between responsiveness and calmness."),
    "Cinematic": ("Smooth", "Uses longer transitions for a quieter, more blended feel. Pick this for films and slow content where instant changes feel distracting."),
}
DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "tuyasync-app-icon.png"
SETTINGS_PATH = DATA_DIR / "ambient-settings.json"
SCENES_PATH = DATA_DIR / "scenes.json"
TINYTUYA_GUIDE_URL = "https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys"
TUYA_IOT_URL = "https://iot.tuya.com"

COLORS = {
    "window": "#F5F5F7",
    "surface": "#FFFFFF",
    "surface_alt": "#F8F9FB",
    "text": "#1D1D1F",
    "secondary": "#6E6E73",
    "tertiary": "#8E8E93",
    "border": "#D9D9DE",
    "blue": "#007AFF",
    "blue_hover": "#147EFB",
    "blue_pressed": "#0064D2",
    "blue_soft": "#EAF3FF",
    "green": "#34C759",
    "green_soft": "#EAF8EE",
    "red": "#FF3B30",
    "red_soft": "#FFF0EF",
}

FONT = "SF Pro Text"
DISPLAY_FONT = "SF Pro Display"


def _rgb_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(value))) for value in rgb)


def _rgb_text(rgb) -> str:
    return "(%d, %d, %d)" % tuple(int(value) for value in rgb)


def _colour_swatch(parent, rgb, command, size=30):
    """Paint a colour preview directly; native macOS buttons ignore bg colours."""
    colour = _rgb_hex(rgb)
    swatch = tk.Canvas(parent, width=size, height=size, bg=COLORS["surface"], highlightthickness=0, cursor="hand2")
    swatch.create_oval(3, 3, size - 3, size - 3, fill=colour, outline=COLORS["border"], width=1)
    swatch.bind("<Button-1>", lambda _event: command())
    return swatch


def load_settings() -> SyncSettings:
    try:
        return SyncSettings.from_dict(json.loads(SETTINGS_PATH.read_text()))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return SyncSettings()


class TuyaSyncApp:
    """Focused controls up front; detailed tuning is one level deeper."""

    MODE_LABELS = {"off": "Off", "screen": "Screen", "music": "Music", "album_art": "Album Art", "scenes": "Scenes"}
    MODE_BY_LABEL = {value: key for key, value in MODE_LABELS.items()}

    def __init__(
        self,
        root: tk.Tk,
        coordinator: Coordinator,
        mode_manager: ModeManager | None = None,
        music_mode: MusicMode | None = None,
        album_art_mode: AlbumArtMode | None = None,
        scenes_mode: ScenesMode | None = None,
        scenes: list[ScenePreset] | None = None,
        profile_store: LightProfileStore | None = None,
        config_manager: ConfigManager | None = None,
        bulb_factory: BulbFactory | None = None,
        startup_error: str | None = None,
    ):
        self.root = root
        self.coordinator = coordinator
        self.mode_manager = mode_manager or ModeManager((coordinator,), coordinator.clear_pending_output)
        self.music_mode = music_mode
        self.album_art_mode = album_art_mode
        self.scenes_mode = scenes_mode
        self.scenes = scenes or list(BUILTIN_SCENES)
        self.profile_store = profile_store
        self.config_manager = config_manager
        self.bulb_factory = bulb_factory
        self.startup_error = startup_error
        self.mode_var = tk.StringVar(value="Off")
        self.settings = coordinator.get_settings()
        self.monitor_options = ScreenProcessor.monitor_options() or [(1, "Display 1")]
        self.monitor_by_label = {label: index for index, label in self.monitor_options}
        self._fine_tune_window = None
        self._calibration_window = None
        self._diagnostics_window = None
        self._quick_window = None
        self._actions = queue.Queue()
        self.tray = None
        self._refresh_job = None
        self._scene_editor_window = None
        self._profile_manager_window = None
        self._profile_editor_window = None
        self._profile_guide_window = None
        self._album_art_photo = None
        self._active_scroll_canvas = None
        self._configure_theme()
        self._build()
        self._refresh_job = self.root.after(250, self.refresh)
        if self.profile_store is not None:
            self.root.after(350, self._show_profile_startup)

    def _show_profile_startup(self):
        if self.startup_error:
            messagebox.showerror("TuyaSync startup", self.startup_error, parent=self.root)
        if not self.profile_store.list_profiles():
            self.open_light_setup_guide()

    def _configure_theme(self):
        self.root.title("TuyaSync · Wipro DS22000")
        self.root.geometry("1160x820")
        self.root.minsize(960, 810)
        self.root.configure(bg=COLORS["window"])
        self.root.protocol("WM_DELETE_WINDOW", self.hide_settings)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Light.TCombobox", fieldbackground=COLORS["surface_alt"], background=COLORS["surface_alt"], foreground=COLORS["text"], bordercolor=COLORS["border"], arrowcolor=COLORS["secondary"], padding=(8, 6))
        style.map("Light.TCombobox", fieldbackground=[("readonly", COLORS["surface_alt"])], selectbackground=[("readonly", COLORS["surface_alt"])], selectforeground=[("readonly", COLORS["text"])])
        style.configure("Primary.TButton", background=COLORS["blue"], foreground="white", borderwidth=0, padding=(18, 9), font=(FONT, 10, "bold"))
        style.map("Primary.TButton", background=[("pressed", COLORS["blue_pressed"]), ("active", COLORS["blue_hover"])])
        style.configure("Stop.TButton", background=COLORS["red_soft"], foreground=COLORS["red"], borderwidth=0, padding=(18, 9), font=(FONT, 10, "bold"))
        style.map("Stop.TButton", background=[("pressed", "#FFD8D5"), ("active", "#FFE3E1")])
        style.configure("Quiet.TButton", background=COLORS["surface_alt"], foreground=COLORS["text"], borderwidth=0, padding=(11, 7), font=(FONT, 9, "bold"))
        style.map("Quiet.TButton", background=[("pressed", "#E3E5E9"), ("active", "#EEF0F3")])
        style.configure("Stepper.TButton", background=COLORS["surface_alt"], foreground=COLORS["text"], borderwidth=0, padding=(8, 3), font=(FONT, 11))
        style.map("Stepper.TButton", background=[("pressed", COLORS["blue_soft"]), ("active", "#EEF4FC")])
        style.configure("Minimal.TNotebook", background=COLORS["window"], borderwidth=0)
        style.configure("Minimal.TNotebook.Tab", background=COLORS["surface_alt"], foreground=COLORS["secondary"], padding=(16, 8), font=(FONT, 9, "bold"))
        style.map("Minimal.TNotebook.Tab", background=[("selected", COLORS["surface"])], foreground=[("selected", COLORS["blue"])])
        style.configure(
            "Screen.Vertical.TScrollbar",
            background=COLORS["border"],
            troughcolor=COLORS["window"],
            bordercolor=COLORS["window"],
            lightcolor=COLORS["window"],
            darkcolor=COLORS["window"],
            arrowcolor=COLORS["window"],
            relief="flat",
            width=8,
        )
        style.map(
            "Screen.Vertical.TScrollbar",
            background=[("active", COLORS["tertiary"]), ("pressed", COLORS["blue"])],
        )
        self.root.bind_all("<MouseWheel>", self._on_global_scroll, add="+")
        self.root.bind_all("<Button-4>", self._on_global_scroll, add="+")
        self.root.bind_all("<Button-5>", self._on_global_scroll, add="+")

    def _build(self):
        self._build_header()
        body = tk.Frame(self.root, bg=COLORS["window"])
        body.pack(fill="both", expand=True, padx=24, pady=(5, 24))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.page_host = body
        self.screen_page = tk.Frame(body, bg=COLORS["window"])
        self.screen_page.columnconfigure(0, weight=0, minsize=350)
        self.screen_page.columnconfigure(1, weight=1)
        self.screen_page.rowconfigure(0, weight=1)
        self.screen_page.grid(row=0, column=0, sticky="nsew")
        setup_scroll_host = tk.Frame(self.screen_page, bg=COLORS["window"])
        setup_scroll_host.grid(row=0, column=0, sticky="nsew")
        setup_scroll_host.rowconfigure(0, weight=1)
        setup_scroll_host.columnconfigure(0, weight=1)
        self.screen_scroll_canvas, setup_content = self._scrollable_content(setup_scroll_host, COLORS["window"], with_scrollbar=True)
        self._build_setup(setup_content)
        self._preserve_screen_setup_width(setup_content)
        self._bind_scroll_tree(setup_content, self.screen_scroll_canvas)
        self._build_status(self.screen_page)
        self._build_off_page(body)
        self._build_music_page(body)
        self._build_album_art_page(body)
        self._build_scenes_page(body)
        self._show_mode_page("off")

    def _build_header(self):
        header = tk.Frame(self.root, bg=COLORS["window"], height=62)
        header.pack(fill="x", padx=24, pady=(17, 4))
        header.pack_propagate(False)

        brand = tk.Frame(header, bg=COLORS["window"])
        brand.pack(side="left", fill="y")
        mark = tk.Canvas(brand, width=34, height=34, bg=COLORS["window"], highlightthickness=0)
        mark.pack(side="left", pady=5)
        mark.create_oval(3, 3, 31, 31, fill=COLORS["blue"], outline="")
        mark.create_oval(12, 12, 22, 22, fill=COLORS["surface"], outline="")
        names = tk.Frame(brand, bg=COLORS["window"])
        names.pack(side="left", padx=(10, 0), pady=3)
        tk.Label(names, text="TuyaSync", bg=COLORS["window"], fg=COLORS["text"], font=(DISPLAY_FONT, 21, "bold")).pack(anchor="w")
        tk.Label(names, text="Wipro DS22000  ·  local LAN", bg=COLORS["window"], fg=COLORS["secondary"], font=(FONT, 9)).pack(anchor="w")

        tools = tk.Frame(header, bg=COLORS["window"])
        tools.pack(side="right", fill="y")
        self.status_var = tk.StringVar(value="Ready")
        self.status_pill = tk.Frame(tools, bg="#ECEEF2", padx=9, pady=5)
        self.status_pill.pack(side="right", padx=(13, 0), pady=13)
        self.status_dot = tk.Canvas(self.status_pill, width=8, height=8, bg="#ECEEF2", highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 5))
        self.status_dot.create_oval(1, 1, 7, 7, fill=COLORS["tertiary"], outline="")
        self.status_label = tk.Label(self.status_pill, textvariable=self.status_var, bg="#ECEEF2", fg=COLORS["secondary"], font=(FONT, 9, "bold"))
        self.status_label.pack(side="left")
        self._button(tools, "Quit", self.quit).pack(side="right", pady=12)
        self._button(tools, "Diagnostics", self.open_diagnostics).pack(side="right", padx=(5, 0), pady=12)
        self._button(tools, "Calibration", self.open_calibration).pack(side="right", pady=12)
        self._button(tools, "Light", self.open_profile_manager).pack(side="right", padx=(0, 5), pady=12)
        self._button(tools, "Preferences", self.open_preferences).pack(side="right", padx=(0, 5), pady=12)
        self.mode_selector = ttk.Combobox(tools, textvariable=self.mode_var, values=tuple(self.MODE_LABELS.values()), state="readonly", width=11, style="Light.TCombobox")
        self.mode_selector.pack(side="right", padx=(0, 12), pady=13)
        self._protect_combobox_wheel(self.mode_selector)
        self.mode_selector.bind("<<ComboboxSelected>>", lambda _event: self._mode_selected())
        tk.Label(tools, text="Mode", bg=COLORS["window"], fg=COLORS["secondary"], font=(FONT, 9, "bold")).pack(side="right", padx=(0, 5), pady=13)

    def _button(self, parent, text, command, kind="quiet"):
        style = {"primary": "Primary.TButton", "stop": "Stop.TButton", "quiet": "Quiet.TButton"}[kind]
        return ttk.Button(parent, text=text, command=command, style=style)

    def _card(self, parent, **kwargs):
        return tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightcolor=COLORS["border"], highlightthickness=1, bd=0, **kwargs)

    def _preserve_screen_setup_width(self, content):
        """Keep the original Setup-card width after adding its scroll viewport."""
        content.update_idletasks()
        requested = content.winfo_reqwidth()
        self.screen_page.columnconfigure(0, minsize=max(350, requested + 18))

    def _scrollable_content(self, parent, background=None, with_scrollbar=False):
        background = background or COLORS["surface"]
        canvas = tk.Canvas(parent, bg=background, highlightthickness=0, bd=0)
        if with_scrollbar:
            parent.rowconfigure(0, weight=1)
            parent.columnconfigure(0, weight=1)
            canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="Screen.Vertical.TScrollbar")
            scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
            canvas.configure(yscrollcommand=scrollbar.set)
        else:
            canvas.pack(fill="both", expand=True)
        content = tk.Frame(canvas, bg=background)
        content.columnconfigure(0, weight=1)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")

        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        return canvas, content

    def _bind_scroll_tree(self, content, canvas):
        """Route wheel gestures from the whole scrollable settings surface."""
        def visit(widget):
            yield widget
            for child in widget.winfo_children():
                yield from visit(child)

        def scroll(event):
            if self._active_scroll_canvas is not canvas:
                return
            return self._scroll_canvas(event, canvas)

        widgets = [canvas, canvas.master, *visit(content)]
        seen = set()
        for widget in widgets:
            if widget in seen:
                continue
            seen.add(widget)
            if isinstance(widget, ttk.Combobox):
                continue
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(sequence, scroll, add="+")

    def _scroll_canvas(self, event, canvas):
        if canvas is None or not canvas.winfo_exists() or not canvas.winfo_ismapped():
            return
        try:
            x_root, y_root = event.x_root, event.y_root
            left, top = canvas.winfo_rootx(), canvas.winfo_rooty()
            right = left + canvas.winfo_width()
            bottom = top + canvas.winfo_height()
            if not left <= x_root < right or not top <= y_root < bottom:
                return
        except (AttributeError, tk.TclError):
            pass
        if getattr(event, "num", None) == 4:
            amount = -1
        elif getattr(event, "num", None) == 5:
            amount = 1
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return
            amount = -max(1, round(abs(delta) / 120)) if delta > 0 else max(1, round(abs(delta) / 120))
        canvas.yview_scroll(amount, "units")
        return "break"

    def _on_global_scroll(self, event):
        canvas = self._active_scroll_canvas
        if canvas is None or not canvas.winfo_exists() or not canvas.winfo_ismapped():
            return
        widget = getattr(event, "widget", None)
        if widget is not None:
            try:
                if widget.winfo_class() == "TCombobox":
                    return "break"
            except tk.TclError:
                return
        return self._scroll_canvas(event, canvas)

    @staticmethod
    def _protect_combobox_wheel(combo):
        def stop_wheel(_event):
            return "break"

        guard_tag = "TuyaSyncNoComboboxWheel"
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            combo.bind_class(guard_tag, sequence, stop_wheel)
        tags = combo.bindtags()
        if guard_tag not in tags:
            combo.bindtags((tags[0], guard_tag, *tags[1:]))
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            combo.bind(sequence, stop_wheel, add="+")

    def _heading(self, parent, title, subtitle):
        header = tk.Frame(parent, bg=COLORS["surface"])
        header.pack(fill="x", padx=20, pady=(18, 12))
        tk.Label(header, text=title, bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 17, "bold")).pack(anchor="w")
        tk.Label(header, text=subtitle, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).pack(anchor="w", pady=(3, 0))

    def _mode_page(self, parent):
        page = tk.Frame(parent, bg=COLORS["window"])
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)
        return page

    def _simple_stepper(self, parent, label, description, variable, minimum, maximum, step, fmt, callback):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", padx=20, pady=7)
        copy = tk.Frame(row, bg=COLORS["surface"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w")
        tk.Label(copy, text=description, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8), wraplength=210, justify="left").pack(anchor="w", pady=(2, 0))
        control = tk.Frame(row, bg=COLORS["surface_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
        control.pack(side="right", padx=(8, 0))
        value = tk.StringVar(value=fmt % variable.get())

        def update(delta):
            next_value = max(minimum, min(maximum, round(float(variable.get()) + delta, 4)))
            variable.set(next_value)
            value.set(fmt % next_value)
            callback()

        ttk.Button(control, text="−", command=lambda: update(-step), style="Stepper.TButton", width=2).pack(side="left")
        tk.Label(control, textvariable=value, width=7, bg=COLORS["surface_alt"], fg=COLORS["text"], font=(FONT, 9, "bold")).pack(side="left", padx=2)
        ttk.Button(control, text="+", command=lambda: update(step), style="Stepper.TButton", width=2).pack(side="left")

    def _build_off_page(self, parent):
        self.off_page = self._mode_page(parent)
        left = self._card(self.off_page)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self._heading(left, "Manual control", "Off releases automatic ownership; these controls act directly on the batten.")
        power = tk.Frame(left, bg=COLORS["surface"])
        power.pack(fill="x", padx=20, pady=(0, 13))
        self._button(power, "Power On", lambda: self._manual_command("turn_on"), "primary").pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(power, "Power Off", lambda: self._manual_command("turn_off"), "stop").pack(side="left", fill="x", expand=True, padx=(5, 0))

        colour = self._advanced_section(left, "Quick color", "Choose a color or open the native color picker.")
        swatches = tk.Frame(colour, bg=COLORS["surface"])
        swatches.pack(fill="x", padx=16, pady=(0, 7))
        for rgb in ((255, 55, 55), (255, 170, 30), (40, 215, 110), (35, 165, 255), (150, 70, 255), (255, 70, 190), (255, 255, 255)):
            _colour_swatch(swatches, rgb, lambda value=rgb: self._manual_colour(value)).pack(side="left", padx=3)
        self.manual_rgb = (255, 255, 255)
        self.manual_colour_label = tk.Label(colour, text="Current selection  ·  (255, 255, 255)", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9))
        self.manual_colour_label.pack(anchor="w", padx=16, pady=(0, 3))
        self._button(colour, "Open color picker…", self._choose_manual_colour).pack(fill="x", padx=16, pady=(0, 14))

        self.manual_brightness_var = tk.DoubleVar(value=100.0)
        self.manual_temperature_var = tk.DoubleVar(value=500.0)
        self._simple_stepper(left, "Brightness", "Scale the selected RGB colour.", self.manual_brightness_var, 1, 100, 5, "%.0f%%", self._manual_brightness)
        self._simple_stepper(left, "White temperature", "Use the dedicated white LEDs at this colour temperature.", self.manual_temperature_var, 0, 1000, 50, "%.0f", self._manual_white)

        right = self._card(self.off_page)
        right.grid(row=0, column=1, sticky="nsew")
        self._heading(right, "No automatic mode", "The light stays available without a producer sending new colours.")
        state = tk.Frame(right, bg=COLORS["surface_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
        state.pack(fill="x", padx=22, pady=(5, 16))
        self.off_state_var = tk.StringVar(value="Ready for a manual command")
        tk.Label(state, textvariable=self.off_state_var, bg=COLORS["surface_alt"], fg=COLORS["text"], font=(DISPLAY_FONT, 16, "bold")).pack(anchor="w", padx=18, pady=(18, 3))
        tk.Label(state, text="Switching to Off stops Screen, Music, Album Art, or a hardware scene. It does not power the lamp off by itself.", bg=COLORS["surface_alt"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=390, justify="left").pack(anchor="w", padx=18, pady=(0, 18))
        info = self._card(right)
        info.pack(fill="x", padx=22, pady=(0, 18))
        self._heading(info, "Device path", "All modes use the same persistent local controller.")
        tk.Label(info, text="Wipro DS22000\nTuya protocol 3.5\nDP28 gradient for realtime colours\nDP25 scene_data_v2 for hardware scenes", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 10), justify="left").pack(anchor="w", padx=20, pady=(0, 20))

    def _build_music_page(self, parent):
        self.music_page = self._mode_page(parent)
        settings = self.music_mode.settings if self.music_mode else MusicSettings()
        self.music_palette_var = tk.StringVar(value=settings.palette)
        self.music_colour_response_var = tk.StringVar(value=settings.colour_response)
        self.music_intensity_var = tk.DoubleVar(value=settings.intensity * 100)
        self.music_reactivity_var = tk.DoubleVar(value=settings.reactivity * 100)
        self.music_beat_var = tk.DoubleVar(value=settings.bass_impact * 100)
        self.music_min_brightness_var = tk.DoubleVar(value=settings.minimum_brightness * 100)
        self.music_max_brightness_var = tk.DoubleVar(value=settings.maximum_brightness * 100)

        left = self._card(self.music_page)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self._heading(left, "Music Sync", "Follow the beat of audio playing from this computer, not the microphone.")
        source = tk.Frame(left, bg=COLORS["surface_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
        source.pack(fill="x", padx=20, pady=(0, 14))
        self.music_status_var = tk.StringVar(value="System audio is ready" if self.music_mode else "System audio is unavailable")
        tk.Label(source, textvariable=self.music_status_var, bg=COLORS["surface_alt"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(source, text="macOS ScreenCaptureKit  ·  Windows WASAPI loopback", bg=COLORS["surface_alt"], fg=COLORS["secondary"], font=(FONT, 8)).pack(anchor="w", padx=14, pady=(0, 12))
        self._select_row(left, "Palette", "Colours follow the selected palette; choose whether beat changes jump or blend.", self.music_palette_var, tuple(PALETTES.keys()), self._apply_music_settings)
        self._select_row(left, "Colour response", "Immediate flash jumps on the beat. Smooth blend eases into the next palette colour.", self.music_colour_response_var, ("Immediate flash", "Smooth blend"), self._apply_music_settings)
        self._simple_stepper(left, "Intensity", "Overall strength of the music response.", self.music_intensity_var, 10, 100, 5, "%.0f%%", self._apply_music_settings)
        self._simple_stepper(left, "Reactivity", "How quickly colour and brightness follow changes.", self.music_reactivity_var, 10, 100, 5, "%.0f%%", self._apply_music_settings)
        self._simple_stepper(left, "Beat impact", "How strongly each detected beat lifts brightness.", self.music_beat_var, 0, 100, 5, "%.0f%%", self._apply_music_settings)
        self._simple_stepper(left, "Minimum brightness", "The resting level during quiet passages.", self.music_min_brightness_var, 1, 60, 1, "%.0f%%", self._apply_music_settings)
        self._simple_stepper(left, "Maximum brightness", "The ceiling for energetic music.", self.music_max_brightness_var, 10, 100, 1, "%.0f%%", self._apply_music_settings)
        actions = tk.Frame(left, bg=COLORS["surface"])
        actions.pack(fill="x", padx=20, pady=(10, 20))
        self._button(actions, "Start Music Sync", lambda: self._switch_mode("music"), "primary").pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(actions, "Stop", lambda: self._switch_mode("off"), "stop").pack(side="left", fill="x", expand=True, padx=(5, 0))

        right = self._card(self.music_page)
        right.grid(row=0, column=1, sticky="nsew")
        self._heading(right, "Beat response", "Choose whether each beat jumps or blends to the next palette colour; brightness also pulses.")
        self.music_visualizer = tk.Canvas(right, height=180, bg=COLORS["surface_alt"], highlightthickness=0)
        self.music_visualizer.pack(fill="x", padx=22, pady=(5, 16))
        self.music_band_labels = tk.Frame(right, bg=COLORS["surface"])
        self.music_band_labels.pack(fill="x", padx=22)
        self.music_band_vars = {}
        for name in ("Energy", "Beat", "Pulse"):
            item = tk.Frame(self.music_band_labels, bg=COLORS["surface"])
            item.pack(side="left", fill="x", expand=True)
            variable = tk.StringVar(value="0%")
            self.music_band_vars[name.lower()] = variable
            tk.Label(item, text=name, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8)).pack()
            tk.Label(item, textvariable=variable, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 11, "bold")).pack(pady=(2, 14))
        self.music_colour_swatch = tk.Canvas(right, width=76, height=76, bg=COLORS["surface"], highlightthickness=0)
        self.music_colour_swatch.pack(pady=(8, 4))
        self.music_analysis_var = tk.StringVar(value="Waiting for a beat")
        tk.Label(right, textvariable=self.music_analysis_var, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=380, justify="center").pack(pady=(4, 20))

    def _build_album_art_page(self, parent):
        self.album_art_page = self._mode_page(parent)
        self.album_art_page.columnconfigure(0, weight=0, minsize=390)
        self.album_art_page.columnconfigure(1, weight=1)
        settings = self.album_art_mode.settings if self.album_art_mode else AlbumArtSettings()
        self.album_art_intensity_var = tk.DoubleVar(value=settings.intensity * 100)
        self.album_art_paused_var = tk.DoubleVar(value=settings.paused_intensity * 100)
        self.album_art_palette_var = tk.StringVar(value=settings.palette_mode)
        self.album_art_colour_response_var = tk.StringVar(value=settings.colour_response)
        self.album_art_reactive_var = tk.BooleanVar(value=settings.music_reactive)
        self.album_art_reactivity_var = tk.DoubleVar(value=settings.reactivity * 100)
        self.album_art_beat_var = tk.DoubleVar(value=settings.beat_impact * 100)
        self.album_art_min_brightness_var = tk.DoubleVar(value=settings.minimum_brightness * 100)
        self.album_art_max_brightness_var = tk.DoubleVar(value=settings.maximum_brightness * 100)

        left_column = tk.Frame(self.album_art_page, bg=COLORS["window"])
        left_column.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left_column.columnconfigure(0, weight=1)
        left_column.rowconfigure(1, weight=1)

        album = self._card(left_column)
        album.pack(fill="x", pady=(0, 14))
        self._heading(album, "Album Art", "Local Spotify artwork, with no OAuth or developer account.")
        artwork_frame = tk.Frame(album, bg=COLORS["surface_alt"], width=220, height=220, highlightbackground=COLORS["border"], highlightthickness=1)
        artwork_frame.pack(padx=20, pady=(0, 16))
        artwork_frame.pack_propagate(False)
        self.album_art_image_label = tk.Label(artwork_frame, text="No artwork", bg=COLORS["surface_alt"], fg=COLORS["tertiary"], font=(FONT, 10))
        self.album_art_image_label.pack(fill="both", expand=True)
        self.album_track_var = tk.StringVar(value="No active Spotify track")
        self.album_artist_var = tk.StringVar(value="")
        self.album_name_var = tk.StringVar(value="")
        tk.Label(album, textvariable=self.album_track_var, bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 15, "bold"), wraplength=320, justify="center").pack(fill="x", padx=20)
        tk.Label(album, textvariable=self.album_artist_var, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 10)).pack(pady=(4, 0))
        tk.Label(album, textvariable=self.album_name_var, bg=COLORS["surface"], fg=COLORS["tertiary"], font=(FONT, 9)).pack(pady=(2, 18))

        palette = self._card(left_column)
        palette.pack(fill="both", expand=True)
        self._heading(palette, "Artwork palette", "One to three colours extracted from the current artwork.")
        self.album_art_swatch = tk.Canvas(palette, width=150, height=150, bg=COLORS["surface"], highlightthickness=0)
        self.album_art_swatch.pack(pady=(14, 10))
        self.album_art_colour_var = tk.StringVar(value="(—, —, —)")
        tk.Label(palette, textvariable=self.album_art_colour_var, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 12, "bold")).pack()
        self.album_art_status_var = tk.StringVar(value="Spotify metadata is ready" if self.album_art_mode else "Album Art is unavailable")
        tk.Label(palette, textvariable=self.album_art_status_var, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=330, justify="center").pack(pady=(10, 20))

        right = self._card(self.album_art_page)
        right.grid(row=0, column=1, sticky="nsew")
        self._heading(right, "Album Art controls", "Tune how the light responds while your track plays.")

        scroll_host = tk.Frame(right, bg=COLORS["surface"])
        scroll_host.pack(fill="both", expand=True, padx=(0, 8), pady=(0, 10))
        scroll_host.rowconfigure(0, weight=1)
        scroll_host.columnconfigure(0, weight=1)
        canvas, settings_content = self._scrollable_content(scroll_host, with_scrollbar=True)
        self.album_art_scroll_canvas = canvas

        palette_section = self._advanced_section(settings_content, "Palette", "Choose one colour, or let the light move through two or three artwork colours.")
        self._select_row(palette_section, "Artwork palette", "Single colour stays constant. Two or three colours can jump or blend on each beat.", self.album_art_palette_var, ("Single color", "Two colors", "Three colors"), self._apply_album_art_settings)
        self._circle_toggle(palette_section, "React to beats", "Use system audio for a continuous palette drift and short brightness accents.", self.album_art_reactive_var, self._apply_album_art_settings)

        response_section = self._advanced_section(settings_content, "Beat response", "Control how quickly and how visibly the light follows the music.")
        self._simple_stepper(response_section, "Responsiveness", "How quickly beat hits and brightness changes appear.", self.album_art_reactivity_var, 10, 100, 5, "%.0f%%", self._apply_album_art_settings)
        self._select_row(response_section, "Colour response", "Immediate flash jumps to the next artwork colour. Smooth blend eases into it.", self.album_art_colour_response_var, ("Immediate flash", "Smooth blend"), self._apply_album_art_settings)
        self._simple_stepper(response_section, "Intensity", "Overall light level while the track is playing.", self.album_art_intensity_var, 10, 100, 5, "%.0f%%", self._apply_album_art_settings)
        self._simple_stepper(response_section, "Beat impact", "How much brighter the light becomes on each beat.", self.album_art_beat_var, 0, 100, 5, "%.0f%%", self._apply_album_art_settings)

        brightness_section = self._advanced_section(settings_content, "Brightness", "Set the resting level and the ceiling used during album-art playback.")
        self._simple_stepper(brightness_section, "Minimum brightness", "The quiet-scene floor, so the light does not disappear between beats.", self.album_art_min_brightness_var, 0, 80, 5, "%.0f%%", self._apply_album_art_settings)
        self._simple_stepper(brightness_section, "Maximum brightness", "The brightest the light may become before Intensity is applied.", self.album_art_max_brightness_var, 10, 100, 5, "%.0f%%", self._apply_album_art_settings)
        self._simple_stepper(brightness_section, "Paused brightness", "The level held when Spotify is paused but the track is still selected.", self.album_art_paused_var, 0, 100, 5, "%.0f%%", self._apply_album_art_settings)

        actions = self._advanced_section(settings_content, "Playback", "Start or stop Album Art mode without changing your saved choices.")
        action_row = tk.Frame(actions, bg=COLORS["surface"])
        action_row.pack(fill="x", padx=16, pady=(4, 16))
        self._button(action_row, "Start Album Art", lambda: self._switch_mode("album_art"), "primary").pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(action_row, "Stop", lambda: self._switch_mode("off"), "stop").pack(side="left", fill="x", expand=True, padx=(5, 0))
        self._bind_scroll_tree(settings_content, canvas)
        self.root.after_idle(lambda: self.album_art_scroll_canvas.yview_moveto(0.0))

    def _build_scenes_page(self, parent):
        self.scenes_page = self._mode_page(parent)
        self.scene_var = tk.StringVar(value=self.scenes[0].name if self.scenes else "No scenes")
        self.scene_max_brightness_var = tk.DoubleVar(value=100.0)
        left = self._card(self.scenes_page)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self._heading(left, "Scenes", "Pick a ready-made mood or build your own colour sequence. The DS22000 performs the fades locally.")
        tk.Label(left, text="Preset", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9, "bold")).pack(anchor="w", padx=20, pady=(0, 5))
        self.scene_combo = ttk.Combobox(left, textvariable=self.scene_var, values=[scene.name for scene in self.scenes], state="readonly", style="Light.TCombobox")
        self.scene_combo.pack(fill="x", padx=20, pady=(0, 12))
        self._protect_combobox_wheel(self.scene_combo)
        self.scene_combo.bind("<<ComboboxSelected>>", lambda _event: self._scene_selection_changed())
        self.scene_summary_var = tk.StringVar(value="")
        tk.Label(left, textvariable=self.scene_summary_var, bg=COLORS["surface_alt"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=310, justify="left", padx=12, pady=12).pack(fill="x", padx=20, pady=(0, 14))
        self._simple_stepper(left, "Maximum brightness", "Ceiling applied to every colour in the selected scene.", self.scene_max_brightness_var, 10, 100, 5, "%.0f%%", self._apply_scene_settings)
        actions = tk.Frame(left, bg=COLORS["surface"])
        actions.pack(fill="x", padx=20, pady=(4, 20))
        self._button(actions, "Start Scene", lambda: self._switch_mode("scenes"), "primary").pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(actions, "Stop", lambda: self._switch_mode("off"), "stop").pack(side="left", fill="x", expand=True, padx=(5, 0))

        right = self._card(self.scenes_page)
        right.grid(row=0, column=1, sticky="nsew")
        self._heading(right, "Scene library", "Built-ins are ready to use; custom scenes are saved only on this computer.")
        self.scene_list = tk.Listbox(right, height=10, activestyle="none", exportselection=False, bg=COLORS["surface_alt"], fg=COLORS["text"], selectbackground=COLORS["blue_soft"], selectforeground=COLORS["blue"], highlightthickness=0, relief="flat", font=(FONT, 10))
        self.scene_list.pack(fill="both", expand=True, padx=22, pady=(0, 14))
        self.scene_list.bind("<<ListboxSelect>>", lambda _event: self._scene_list_selected())
        scene_buttons = tk.Frame(right, bg=COLORS["surface"])
        scene_buttons.pack(fill="x", padx=22, pady=(0, 20))
        self._button(scene_buttons, "New Scene", self.new_scene).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._button(scene_buttons, "Edit", self.edit_scene).pack(side="left", fill="x", expand=True, padx=4)
        self._button(scene_buttons, "Delete", self.delete_scene).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._refresh_scene_list(self.scene_var.get())

    def _show_mode_page(self, name):
        pages = {
            "off": self.off_page,
            "screen": self.screen_page,
            "music": self.music_page,
            "album_art": self.album_art_page,
            "scenes": self.scenes_page,
        }
        for page in pages.values():
            page.grid_remove()
        page = pages.get(name, self.off_page)
        page.grid()
        page.tkraise()
        self._active_scroll_canvas = {
            "screen": getattr(self, "screen_scroll_canvas", None),
            "album_art": getattr(self, "album_art_scroll_canvas", None),
        }.get(name)
        if self._active_scroll_canvas is not None:
            self._active_scroll_canvas.yview_moveto(0.0)
        self.mode_var.set(self.MODE_LABELS.get(name, "Off"))
        self._scene_selection_changed() if name == "scenes" else None

    def _mode_selected(self):
        name = self.MODE_BY_LABEL.get(self.mode_var.get(), "off")
        self._switch_mode(name)

    def _switch_mode(self, name, scene_override=None):
        if name == "music":
            self._apply_music_settings()
        elif name == "album_art":
            self._apply_album_art_settings()
        elif name == "scenes":
            scene = scene_override or self._selected_scene()
            if scene is None:
                self._show_mode_error("Choose a scene first")
                return
            if self.scenes_mode:
                self.scenes_mode.set_scene(scene, self._scene_slot(scene))
                self.scenes_mode.set_max_brightness(self.scene_max_brightness_var.get() * 10)
                if self.mode_manager.active_mode == "scenes":
                    try:
                        self.scenes_mode.apply()
                        self.live_status_var.set(f"Applied {scene.name} to the DS22000")
                    except Exception as error:
                        self._show_mode_error(str(error))
                    return
        try:
            self.mode_manager.switch_to(name)
        except ModeTransitionError as error:
            self._show_mode_error(str(error))
            self._show_mode_page(self.mode_manager.active_mode)
            return
        self._show_mode_page(name)
        messages = {
            "off": "No automatic mode owns the batten.",
            "screen": "Syncing screen colours over the local LAN.",
            "music": "Listening to system audio and following the mix.",
            "album_art": "Waiting for the current Spotify track.",
            "scenes": "The DS22000 is executing the selected DP25 scene.",
        }
        if hasattr(self, "live_status_var"):
            self.live_status_var.set(messages.get(name, "Ready"))
        if hasattr(self, "off_state_var"):
            self.off_state_var.set("Ready for a manual command" if name == "off" else f"{self.MODE_LABELS[name]} is active")

    def _show_mode_error(self, message):
        if hasattr(self, "live_status_var"):
            self.live_status_var.set(message)
        try:
            messagebox.showerror("TuyaSync", message, parent=self.root)
        except tk.TclError:
            pass

    def _apply_music_settings(self):
        if not self.music_mode:
            return
        minimum = min(self.music_min_brightness_var.get(), self.music_max_brightness_var.get()) / 100
        maximum = max(self.music_min_brightness_var.get(), self.music_max_brightness_var.get()) / 100
        self.music_mode.update_settings(MusicSettings(
            palette=self.music_palette_var.get(),
            colour_response=self.music_colour_response_var.get(),
            intensity=self.music_intensity_var.get() / 100,
            reactivity=self.music_reactivity_var.get() / 100,
            bass_impact=self.music_beat_var.get() / 100,
            minimum_brightness=minimum,
            maximum_brightness=maximum,
        ))

    def _apply_album_art_settings(self):
        if self.album_art_mode:
            current = self.album_art_mode.settings
            self.album_art_mode.update_settings(AlbumArtSettings(
                intensity=self.album_art_intensity_var.get() / 100,
                paused_intensity=self.album_art_paused_var.get() / 100,
                palette_mode=self.album_art_palette_var.get(),
                colour_response=self.album_art_colour_response_var.get(),
                music_reactive=bool(self.album_art_reactive_var.get()),
                reactivity=self.album_art_reactivity_var.get() / 100,
                beat_impact=self.album_art_beat_var.get() / 100,
                minimum_brightness=self.album_art_min_brightness_var.get() / 100,
                maximum_brightness=self.album_art_max_brightness_var.get() / 100,
            ))

    def _apply_scene_settings(self):
        if not self.scenes_mode:
            return
        scene = self._selected_scene()
        if scene is None:
            return
        self.scenes_mode.set_scene(scene, self._scene_slot(scene))
        self.scenes_mode.set_max_brightness(self.scene_max_brightness_var.get() * 10)
        if self.mode_manager.active_mode == "scenes":
            try:
                self.scenes_mode.apply()
                self.live_status_var.set(f"Applied {scene.name} to the DS22000")
            except Exception as error:
                self._show_mode_error(str(error))

    def _selected_scene(self):
        name = self.scene_var.get()
        return next((scene for scene in self.scenes if scene.name == name), None)

    def _scene_slot(self, scene):
        try:
            return min(8, self.scenes.index(scene) + 1)
        except ValueError:
            return 8

    def _scene_selection_changed(self):
        scene = self._selected_scene()
        if not scene:
            self.scene_summary_var.set("No scene selected")
            return
        self.scene_summary_var.set(f"{len(scene.stops)} colour stops  ·  {'loops on the fixture' if scene.loop else 'plays once'}\n" + "  →  ".join(_rgb_hex(stop.color) for stop in scene.stops))
        if self.scenes_mode:
            previous_scene = self.scenes_mode.scene
            self.scenes_mode.set_scene(scene, self._scene_slot(scene))
            self.scenes_mode.set_max_brightness(self.scene_max_brightness_var.get() * 10)
            if self.mode_manager.active_mode == "scenes" and previous_scene is not scene:
                try:
                    self.scenes_mode.apply()
                    self.live_status_var.set(f"Applied {scene.name} to the DS22000")
                except Exception as error:
                    self._show_mode_error(str(error))

    def _refresh_scene_list(self, selected_name=None):
        if not hasattr(self, "scene_list"):
            return
        self.scene_list.delete(0, "end")
        for scene in self.scenes:
            suffix = "  ·  custom" if not scene.builtin else ""
            self.scene_list.insert("end", scene.name + suffix)
        target = selected_name or self.scene_var.get()
        for index, scene in enumerate(self.scenes):
            if scene.name == target:
                self.scene_list.selection_set(index)
                self.scene_list.see(index)
                break
        self.scene_combo.configure(values=[scene.name for scene in self.scenes])
        if target in [scene.name for scene in self.scenes]:
            self.scene_var.set(target)
        self._scene_selection_changed()

    def _scene_list_selected(self):
        selection = self.scene_list.curselection()
        if not selection:
            return
        self.scene_var.set(self.scenes[selection[0]].name)
        self._scene_selection_changed()

    def new_scene(self):
        self._open_scene_editor(ScenePreset("My scene", [SceneStop((255, 70, 160), 700, 4, 0)], loop=True, builtin=False))

    def edit_scene(self):
        scene = self._selected_scene()
        if scene:
            self._open_scene_editor(ScenePreset(scene.name, list(scene.stops), scene.loop, builtin=False))

    def delete_scene(self):
        scene = self._selected_scene()
        if not scene or scene.builtin:
            self._show_mode_error("Built-in scenes cannot be deleted")
            return
        if not messagebox.askyesno("Delete scene", f"Delete {scene.name}?", parent=self.root):
            return
        self.scenes = [item for item in self.scenes if item.name != scene.name]
        save_custom_scenes(SCENES_PATH, [item for item in self.scenes if not item.builtin])
        self.scene_var.set(self.scenes[0].name if self.scenes else "No scenes")
        self._refresh_scene_list(self.scene_var.get())

    def _open_scene_editor(self, scene):
        if self._scene_editor_window and self._scene_editor_window.winfo_exists():
            self._scene_editor_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._scene_editor_window = window
        self._window_base(window, "Scene editor", "Design the sequence, preview it on the batten, then save it for later.", 840, 700)
        self._editor_scene = scene
        self._editor_stops = list(scene.stops)
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        top = tk.Frame(card, bg=COLORS["surface"])
        top.pack(fill="x", padx=16, pady=(16, 12))
        tk.Label(top, text="Name", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9, "bold")).pack(side="left")
        self.editor_name_var = tk.StringVar(value=scene.name)
        tk.Entry(top, textvariable=self.editor_name_var, bg=COLORS["surface_alt"], fg=COLORS["text"], relief="flat", highlightthickness=1, highlightbackground=COLORS["border"], font=(FONT, 10)).pack(side="left", fill="x", expand=True, padx=(10, 16), ipady=6)
        self.editor_loop_var = tk.BooleanVar(value=scene.loop)
        self._circle_toggle(top, "Loop", "Keep the hardware scene repeating while Scenes is active.", self.editor_loop_var, lambda: None)
        self.editor_timeline = tk.Canvas(card, height=78, bg=COLORS["surface_alt"], highlightthickness=0)
        self.editor_timeline.pack(fill="x", padx=16, pady=(0, 14))
        self.editor_timeline.bind("<Configure>", lambda _event: self._draw_editor_timeline())
        content = tk.Frame(card, bg=COLORS["surface"])
        content.pack(fill="both", expand=True, padx=16)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        self.editor_list = tk.Listbox(content, exportselection=False, activestyle="none", bg=COLORS["surface_alt"], fg=COLORS["text"], selectbackground=COLORS["blue_soft"], selectforeground=COLORS["blue"], highlightthickness=0, relief="flat", font=(FONT, 10))
        self.editor_list.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.editor_list.bind("<<ListboxSelect>>", lambda _event: self._load_editor_stop())
        controls = tk.Frame(content, bg=COLORS["surface"])
        controls.grid(row=0, column=1, sticky="nsew")
        self.editor_stop_title_var = tk.StringVar(value="Selected stop")
        tk.Label(controls, textvariable=self.editor_stop_title_var, bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 13, "bold")).pack(anchor="w", pady=(0, 3))
        tk.Label(controls, text="Click the colour chip to choose a new colour.", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).pack(anchor="w", pady=(0, 10))
        self.editor_colour_button = _colour_swatch(controls, (255, 70, 160), self._choose_editor_colour, size=54)
        self.editor_colour_button.pack(anchor="w", pady=(0, 12))
        self.editor_brightness_var = tk.IntVar(value=700)
        self.editor_transition_var = tk.DoubleVar(value=4.0)
        self.editor_hold_var = tk.DoubleVar(value=0.0)
        brightness_box = self._editor_spinbox(controls, "Brightness (0–1000)", self.editor_brightness_var, 0, 1000, 10)
        transition_box = self._editor_spinbox(controls, "Fade seconds", self.editor_transition_var, 0, 100, 1)
        hold_box = self._editor_spinbox(controls, "Hold seconds", self.editor_hold_var, 0, 100, 1)
        for box in (brightness_box, transition_box, hold_box):
            box.bind("<FocusOut>", lambda _event: self._commit_editor_fields())
            box.bind("<Return>", lambda _event: self._commit_editor_fields())
        editor_buttons = tk.Frame(card, bg=COLORS["surface"])
        editor_buttons.pack(fill="x", padx=16, pady=(14, 16))
        self._button(editor_buttons, "Add stop", self._add_editor_stop).pack(side="left")
        self._button(editor_buttons, "Remove", self._remove_editor_stop).pack(side="left", padx=6)
        self._button(editor_buttons, "Move up", lambda: self._move_editor_stop(-1)).pack(side="left")
        self._button(editor_buttons, "Move down", lambda: self._move_editor_stop(1)).pack(side="left", padx=6)
        self._button(editor_buttons, "Cancel", window.destroy).pack(side="right")
        self._button(editor_buttons, "Preview on light", self._preview_scene_editor).pack(side="right", padx=(0, 6))
        self._button(editor_buttons, "Save scene", lambda: self._save_scene_editor(window), "primary").pack(side="right", padx=(0, 6))
        self._refresh_editor_list(0)
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def _editor_spinbox(self, parent, label, variable, minimum, maximum, increment):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", pady=7)
        tk.Label(row, text=label, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).pack(anchor="w")
        spinbox = tk.Spinbox(row, textvariable=variable, from_=minimum, to=maximum, increment=increment, width=10, bg=COLORS["surface_alt"], fg=COLORS["text"], relief="flat", buttonbackground=COLORS["surface_alt"], highlightthickness=1, highlightbackground=COLORS["border"])
        spinbox.pack(anchor="w", pady=(4, 0), ipady=4)
        return spinbox

    def _editor_index(self):
        selection = self.editor_list.curselection()
        return selection[0] if selection else None

    def _refresh_editor_list(self, selected=None):
        self.editor_list.delete(0, "end")
        for index, stop in enumerate(self._editor_stops, start=1):
            self.editor_list.insert("end", f"{index:02d}  {_rgb_hex(stop.color)}  ·  {stop.transition_duration:.0f}s fade")
        self._draw_editor_timeline()
        if self._editor_stops:
            index = 0 if selected is None else max(0, min(len(self._editor_stops) - 1, selected))
            self.editor_list.selection_set(index)
            self.editor_list.activate(index)
            self._load_editor_stop()

    def _load_editor_stop(self):
        index = self._editor_index()
        if index is None:
            return
        stop = self._editor_stops[index]
        self.editor_stop_title_var.set(f"Stop {index + 1} of {len(self._editor_stops)}")
        self.editor_brightness_var.set(stop.brightness)
        self.editor_transition_var.set(stop.transition_duration)
        self.editor_hold_var.set(stop.hold_duration)
        self.editor_colour_button.itemconfigure(1, fill=_rgb_hex(stop.color))
        self._draw_editor_timeline()

    def _draw_editor_timeline(self):
        if not hasattr(self, "editor_timeline") or not self.editor_timeline.winfo_exists():
            return
        canvas = self.editor_timeline
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        if not self._editor_stops:
            canvas.create_text(width / 2, 39, text="Add a colour stop to begin", fill=COLORS["tertiary"], font=(FONT, 10))
            return
        gap = 8
        pill_width = max(46, (width - 32 - gap * (len(self._editor_stops) - 1)) / len(self._editor_stops))
        selected = self._editor_index()
        for index, stop in enumerate(self._editor_stops):
            x1 = 16 + index * (pill_width + gap)
            x2 = x1 + pill_width
            outline = COLORS["blue"] if index == selected else COLORS["border"]
            canvas.create_rectangle(x1, 18, x2, 58, fill=_rgb_hex(stop.color), outline=outline, width=2 if index == selected else 1)
            canvas.create_text((x1 + x2) / 2, 38, text=str(index + 1), fill="white", font=(FONT, 10, "bold"))
            if index < len(self._editor_stops) - 1:
                canvas.create_text(x2 + gap / 2, 38, text="›", fill=COLORS["tertiary"], font=(DISPLAY_FONT, 14, "bold"))

    def _commit_editor_fields(self):
        index = self._editor_index()
        if index is None:
            return
        try:
            brightness = int(float(self.editor_brightness_var.get()))
            transition = float(self.editor_transition_var.get())
            hold = float(self.editor_hold_var.get())
        except (TypeError, ValueError, tk.TclError):
            self._load_editor_stop()
            return
        old = self._editor_stops[index]
        self._editor_stops[index] = SceneStop(
            old.color,
            max(0, min(1000, brightness)),
            max(0.0, min(100.0, transition)),
            max(0.0, min(100.0, hold)),
        )
        self._refresh_editor_list(index)

    def _replace_editor_stop(self, **changes):
        index = self._editor_index()
        if index is None:
            return
        old = self._editor_stops[index]
        self._editor_stops[index] = SceneStop(changes.get("color", old.color), int(max(0, min(1000, self.editor_brightness_var.get()))), float(max(0, min(100, self.editor_transition_var.get()))), float(max(0, min(100, self.editor_hold_var.get()))))
        self._refresh_editor_list(index)

    def _choose_editor_colour(self):
        index = self._editor_index()
        if index is None:
            return
        colour = colorchooser.askcolor(color=_rgb_hex(self._editor_stops[index].color), parent=self._scene_editor_window)[0]
        if colour:
            rgb = tuple(int(value) for value in colour)
            self._replace_editor_stop(color=rgb)

    def _add_editor_stop(self):
        self._editor_stops.append(SceneStop((100, 180, 255), 650, 4, 0))
        self._refresh_editor_list(len(self._editor_stops) - 1)

    def _remove_editor_stop(self):
        index = self._editor_index()
        if index is not None and len(self._editor_stops) > 1:
            self._editor_stops.pop(index)
            self._refresh_editor_list(max(0, index - 1))

    def _move_editor_stop(self, direction):
        index = self._editor_index()
        target = index + direction if index is not None else None
        if target is None or target < 0 or target >= len(self._editor_stops):
            return
        self._editor_stops[index], self._editor_stops[target] = self._editor_stops[target], self._editor_stops[index]
        self._refresh_editor_list(target)

    def _save_scene_editor(self, window):
        self._commit_editor_fields()
        name = self.editor_name_var.get().strip() or "Custom scene"
        scene = ScenePreset(name, list(self._editor_stops), bool(self.editor_loop_var.get()), builtin=False)
        previous_name = self._editor_scene.name
        self.scenes = [item for item in self.scenes if item.name not in {name, previous_name}]
        self.scenes.append(scene)
        save_custom_scenes(SCENES_PATH, [item for item in self.scenes if not item.builtin])
        self.scene_var.set(name)
        self._refresh_scene_list(name)
        window.destroy()

    def _preview_scene_editor(self):
        self._commit_editor_fields()
        name = self.editor_name_var.get().strip() or "Preview"
        preview = ScenePreset(name, list(self._editor_stops), bool(self.editor_loop_var.get()), builtin=False)
        if not self.scenes_mode:
            return
        self.scenes_mode.set_scene(preview, 8)
        self.scenes_mode.set_max_brightness(self.scene_max_brightness_var.get() * 10)
        self._switch_mode("scenes", preview)
        if hasattr(self, "live_status_var"):
            self.live_status_var.set(f"Previewing {name} on the DS22000")

    def _manual_command(self, method, *args):
        self._switch_mode("off")
        results = self.coordinator.light_service.execute(method, *args)
        self.off_state_var.set("Manual command sent" if results and all(result == "sent" for result in results) else "Manual command failed")

    def _manual_colour(self, rgb):
        self.manual_rgb = tuple(int(value) for value in rgb)
        text = f"Current selection  ·  {_rgb_text(self.manual_rgb)}"
        self.manual_colour_label.configure(text=text)
        if hasattr(self, "quick_colour_label") and self.quick_colour_label.winfo_exists():
            self.quick_colour_label.configure(text=text)
        self._manual_brightness()

    def _choose_manual_colour(self):
        colour = colorchooser.askcolor(color=_rgb_hex(self.manual_rgb), parent=self.root)[0]
        if colour:
            self._manual_colour(tuple(int(value) for value in colour))

    def _manual_brightness(self):
        brightness = max(0.01, min(1.0, self.manual_brightness_var.get() / 100))
        self._manual_command("set_color", *LightService._scale_rgb(self.manual_rgb, brightness))

    def _manual_white(self):
        brightness = int(round(self.manual_brightness_var.get() * 10))
        temperature = int(round(self.manual_temperature_var.get()))
        self._manual_command("set_white", brightness, temperature)

    def _build_setup(self, body):
        panel = self._card(body)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self._heading(panel, "Setup", "Choose how TuyaSync should follow your display.")
        self._build_light_profile_card(panel)

        initial_algorithm = "Legacy" if self.settings.algorithm == "Saturated Average" else self.settings.algorithm
        self.algorithm_var = tk.StringVar(value=initial_algorithm if initial_algorithm in PRIMARY_ALGORITHMS else "Saturated")
        self.transport_var = tk.StringVar(value=self.settings.output_transport)
        self.response_profile_var = tk.StringVar(value=self.settings.response_profile)
        self.white_handling_var = tk.StringVar(value="Auto dedicated white" if self.settings.use_dedicated_white else "RGB only")
        self.monitor_var = tk.StringVar(value=next((label for index, label in self.monitor_options if index == self.settings.monitor_index), self.monitor_options[0][1]))
        self.update_rate_var = tk.DoubleVar(value=self.settings.update_rate)
        self.responsiveness_var = tk.DoubleVar(value=self.settings.responsiveness)
        self.saturation_boost_var = tk.DoubleVar(value=self.settings.saturation_boost)
        self.minimum_brightness_var = tk.DoubleVar(value=self.settings.minimum_brightness)
        self.maximum_brightness_var = tk.DoubleVar(value=self.settings.maximum_brightness)
        self.gamma_var = tk.DoubleVar(value=self.settings.brightness_gamma)
        self.black_threshold_var = tk.DoubleVar(value=self.settings.black_scene_threshold)
        self.black_bar_threshold_var = tk.DoubleVar(value=self.settings.black_bar_threshold)
        self.smoothing_var = tk.DoubleVar(value=self.settings.color_smoothing)
        self.attack_var = tk.DoubleVar(value=self.settings.brightness_attack)
        self.release_var = tk.DoubleVar(value=self.settings.brightness_release)
        self.black_delay_var = tk.DoubleVar(value=self.settings.black_off_delay)
        self.deadband_var = tk.DoubleVar(value=self.settings.color_deadband)
        self.analysis_width_var = tk.IntVar(value=self.settings.analysis_width)
        self.static_ui_weight_var = tk.DoubleVar(value=self.settings.static_ui_weight)
        self.white_background_weight_var = tk.DoubleVar(value=self.settings.white_background_weight)
        self.white_enter_delay_var = tk.DoubleVar(value=self.settings.white_enter_delay)
        self.white_exit_delay_var = tk.DoubleVar(value=self.settings.white_exit_delay)
        self.red_gain_var = tk.DoubleVar(value=self.settings.red_gain)
        self.green_gain_var = tk.DoubleVar(value=self.settings.green_gain)
        self.blue_gain_var = tk.DoubleVar(value=self.settings.blue_gain)
        self.output_saturation_var = tk.DoubleVar(value=self.settings.output_saturation)
        self.output_gamma_var = tk.DoubleVar(value=self.settings.output_gamma)
        self.ignore_bars_var = tk.BooleanVar(value=self.settings.ignore_black_bars)
        self.reduce_static_ui_var = tk.BooleanVar(value=self.settings.reduce_static_ui)
        self.turn_off_black_var = tk.BooleanVar(value=self.settings.turn_off_on_black)

        self._select_row(panel, "Algorithm", "Recommended: Saturated for most content.", self.algorithm_var, PRIMARY_ALGORITHMS, self._screen_choice_changed)
        self._select_row(panel, "Monitor", "Which display supplies the colour signal.", self.monitor_var, [label for _, label in self.monitor_options])
        self._select_row(panel, "Transport", "DP28 gradient is the production default for realtime color.", self.transport_var, ("DP24", "DP28"))
        self._select_row(panel, "Response", "Balanced is the best starting point.", self.response_profile_var, ("Responsive", "Balanced", "Cinematic"), self._screen_choice_changed)
        self._select_row(panel, "White handling", "RGB only is safest; Auto dedicated white is for stable neutral scenes.", self.white_handling_var, ("RGB only", "Auto dedicated white"))
        self._stepper(panel, "Maximum update rate", "Upper limit; calm scenes automatically send less.", self.update_rate_var, 1, 15, 1, "%.0f Hz")
        self._circle_toggle(panel, "Ignore black bars", "Exclude detected movie bars without cropping naturally dark scenes.", self.ignore_bars_var)

        divider = tk.Frame(panel, bg=COLORS["border"], height=1)
        divider.pack(fill="x", padx=20, pady=(17, 15))
        self._button(panel, "Explain choices…", self.open_screen_choice_guide).pack(fill="x", padx=20)
        self._button(panel, "Fine tune…", self.open_fine_tune).pack(fill="x", padx=20, pady=(6, 0))
        tk.Label(panel, text="Brightness curve, smoothing, black-scene safety, and white-LED routing.", bg=COLORS["surface"], fg=COLORS["tertiary"], font=(FONT, 9), wraplength=285, justify="left").pack(anchor="w", padx=20, pady=(8, 18))

    def _build_light_profile_card(self, parent):
        card = self._advanced_section(parent, "Light", "Move an existing light between computers or add a new one.")
        self.profile_summary_var = tk.StringVar(value="No light profile configured.")
        tk.Label(
            card,
            textvariable=self.profile_summary_var,
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            font=(FONT, 9),
            wraplength=285,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))
        buttons = tk.Frame(card, bg=COLORS["surface"])
        buttons.pack(fill="x", padx=16, pady=(0, 14))
        self._button(buttons, "Manage lights…", self.open_profile_manager, "primary").pack(side="left", fill="x", expand=True)
        self._button(buttons, "Import…", self.import_light_profile).pack(side="left", padx=(7, 0))
        self._refresh_profile_summary()

    def _refresh_profile_summary(self):
        if not hasattr(self, "profile_summary_var"):
            return
        if self.profile_store is None:
            self.profile_summary_var.set("Light profiles are unavailable in this session.")
            return
        profiles = self.profile_store.list_profiles()
        if not profiles:
            self.profile_summary_var.set("No light configured. Add the Device ID and Local Key once, or import a profile file from another computer.")
            return
        profile = profiles[0]
        address = profile.ip_address or "LAN address will be rediscovered"
        self.profile_summary_var.set(f"{profile.name}  ·  {profile.device_id}  ·  {address}")

    def _profile_display(self, profile: LightProfile) -> str:
        address = profile.ip_address or "discover automatically"
        return f"{profile.name}  ·  {profile.device_id}  ·  {address}"

    def _selected_profile(self):
        if self.profile_store is None:
            return None
        profiles = self.profile_store.list_profiles()
        if not profiles:
            return None
        selection = getattr(self, "_profile_listbox", None)
        index = selection.curselection()[0] if selection and selection.curselection() else 0
        return profiles[min(index, len(profiles) - 1)]

    def _refresh_profile_list(self):
        if not getattr(self, "_profile_listbox", None):
            self._refresh_profile_summary()
            return
        listbox = self._profile_listbox
        listbox.delete(0, tk.END)
        for profile in self.profile_store.list_profiles():
            listbox.insert(tk.END, self._profile_display(profile))
        if listbox.size():
            listbox.selection_set(0)
        self._refresh_profile_summary()

    def open_light_setup_guide(self):
        if self.profile_store is None:
            return
        if self._profile_guide_window and self._profile_guide_window.winfo_exists():
            self._profile_guide_window.deiconify()
            self._profile_guide_window.lift()
            return

        window = tk.Toplevel(self.root)
        self._profile_guide_window = window
        self._window_base(
            window,
            "Welcome to TuyaSync",
            "You need a light profile once. After that, TuyaSync talks to the light locally.",
            720,
            720,
        )
        scroll_host = tk.Frame(window, bg=COLORS["window"])
        scroll_host.pack(fill="both", expand=True, padx=22, pady=(2, 12))
        scroll_host.rowconfigure(0, weight=1)
        scroll_host.columnconfigure(0, weight=1)
        canvas, content = self._scrollable_content(scroll_host, COLORS["window"], with_scrollbar=True)
        previous_scroll_canvas = self._active_scroll_canvas
        self._active_scroll_canvas = canvas

        intro = self._card(content)
        intro.pack(fill="x", pady=(0, 12))
        self._heading(intro, "What TuyaSync needs", "The app cannot authenticate a new physical light from its IP address alone.")
        tk.Label(
            intro,
            text=(
                "For each physical Tuya light, enter its Device ID and Local Key. "
                "The IP address is optional because TuyaSync can rediscover it on the same LAN. "
                "Do not enter your Tuya account password or developer API secret here."
            ),
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            font=(FONT, 9),
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 18))

        existing = self._card(content)
        existing.pack(fill="x", pady=(0, 12))
        self._heading(existing, "Already configured this light elsewhere?", "Move the existing light without repeating Tuya setup.")
        tk.Label(
            existing,
            text=(
                "Export a .tuyasync-profile.json file from the other computer, copy it here, "
                "and import it. The file is plain JSON and contains the Local Key, so keep it private."
            ),
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            font=(FONT, 9),
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 10))
        self._button(existing, "Import profile…", lambda: (close(), self.import_light_profile()), "primary").pack(anchor="w", padx=20, pady=(0, 18))

        known = self._card(content)
        known.pack(fill="x", pady=(0, 12))
        self._heading(known, "Already have the two values?", "Enter the Device ID and Local Key you already obtained.")
        tk.Label(
            known,
            text="Leave the LAN address blank if you want automatic discovery.",
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            font=(FONT, 9),
        ).pack(anchor="w", padx=20, pady=(0, 10))
        self._button(known, "Enter light details…", lambda: (close(), self.open_profile_editor()), "primary").pack(anchor="w", padx=20, pady=(0, 18))

        obtain = self._card(content)
        obtain.pack(fill="x")
        self._heading(obtain, "Need to obtain the light details?", "This is a one-time credential-retrieval step for a new physical light.")
        instructions = (
            "1. Pair the light in the Smart Life or Tuya Smart mobile app.\n"
            "2. Create or use a Tuya IoT project and link the mobile-app account.\n"
            "3. On a computer with TinyTuya installed, run:\n"
            "   python -m tinytuya wizard\n"
            "4. The wizard uses the Tuya IoT project credentials to retrieve the "
            "registered light's Device ID and Local Key.\n"
            "5. Bring only those two light-specific values back to this form. "
            "TuyaSync itself does not use the Tuya cloud at runtime."
        )
        tk.Label(
            obtain,
            text=instructions,
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            font=(FONT, 9),
            wraplength=620,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))
        links = tk.Frame(obtain, bg=COLORS["surface"])
        links.pack(fill="x", padx=20, pady=(0, 18))
        self._button(links, "TinyTuya setup guide", lambda: webbrowser.open(TINYTUYA_GUIDE_URL)).pack(side="left")
        self._button(links, "Open Tuya IoT", lambda: webbrowser.open(TUYA_IOT_URL)).pack(side="left", padx=(7, 0))

        self._bind_scroll_tree(content, canvas)

        def close():
            self._active_scroll_canvas = previous_scroll_canvas
            self._profile_guide_window = None
            window.destroy()

        actions = tk.Frame(window, bg=COLORS["window"])
        actions.pack(fill="x", padx=22, pady=(0, 18))
        self._button(actions, "Manage profiles…", lambda: (close(), self.open_profile_manager())).pack(side="left")
        self._button(actions, "I’ll do this later", close).pack(side="right")

        window.protocol("WM_DELETE_WINDOW", close)

    def open_profile_manager(self):
        if self.profile_store is None:
            messagebox.showerror("Light profiles", "Light profile management is unavailable in this session.", parent=self.root)
            return
        if self._profile_manager_window and self._profile_manager_window.winfo_exists():
            self._refresh_profile_list()
            self._profile_manager_window.deiconify()
            self._profile_manager_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._profile_manager_window = window
        self._window_base(
            window,
            "Light profiles",
            "Profiles are readable local JSON files. Keep exported files private because they contain the Local Key.",
            720,
            450,
        )
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        listbox = tk.Listbox(
            card,
            bg=COLORS["surface_alt"],
            fg=COLORS["text"],
            selectbackground=COLORS["blue_soft"],
            selectforeground=COLORS["text"],
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["blue"],
            relief="flat",
            borderwidth=0,
            font=(FONT, 10),
            height=7,
        )
        listbox.pack(fill="both", expand=True, padx=16, pady=(16, 10))
        self._profile_listbox = listbox
        self._refresh_profile_list()

        buttons = tk.Frame(card, bg=COLORS["surface"])
        buttons.pack(fill="x", padx=16, pady=(0, 16))
        self._button(buttons, "How to get details…", self.open_light_setup_guide).pack(side="left")
        self._button(buttons, "Add light…", self.open_profile_editor, "primary").pack(side="left")
        self._button(buttons, "Import…", self.import_light_profile).pack(side="left", padx=(7, 0))
        self._button(buttons, "Export…", self.export_light_profile).pack(side="left", padx=(7, 0))
        self._button(buttons, "Remove", self.remove_light_profile, "stop").pack(side="right")

        def close():
            self._profile_manager_window = None
            self._profile_listbox = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close)

    def open_profile_editor(self):
        if self.profile_store is None:
            return
        if self._profile_editor_window and self._profile_editor_window.winfo_exists():
            self._profile_editor_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._profile_editor_window = window
        self._window_base(
            window,
            "Add light",
            "Enter credentials for a new Tuya light. The Local Key is saved in the local profile file.",
            560,
            570,
        )
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        fields = {}

        def field(label, description, key, show=None, default=""):
            row = tk.Frame(card, bg=COLORS["surface"])
            row.pack(fill="x", padx=16, pady=(12, 0))
            tk.Label(row, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(row, text=description, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8), wraplength=465, justify="left").pack(anchor="w", pady=(2, 4))
            variable = tk.StringVar(value=default)
            entry = ttk.Entry(row, textvariable=variable, show=show or "")
            entry.pack(fill="x")
            fields[key] = variable

        field("Profile name", "A friendly name shown when you move between computers.", "name", default="My Tuya light")
        field("Device ID", "The ID belonging to this physical light.", "device_id")
        field("Local Key", "The light's local credential. It will be saved in the local profile file.", "local_key", show="*")
        field("LAN address (optional)", "Leave this blank to let TuyaSync rediscover the light on the local network.", "ip_address")
        field("Protocol version", "The DS22000 normally uses 3.5.", "protocol", default="3.5")

        footer = tk.Frame(card, bg=COLORS["surface"])
        footer.pack(fill="x", side="bottom", padx=16, pady=16)
        self._button(footer, "Cancel", window.destroy).pack(side="left")
        self._button(footer, "How do I get these?", self.open_light_setup_guide).pack(side="left", padx=(7, 0))

        def save():
            try:
                profile = self.profile_store.save_profile(
                    name=fields["name"].get(),
                    device_id=fields["device_id"].get(),
                    local_key=fields["local_key"].get(),
                    ip_address=fields["ip_address"].get(),
                    protocol=fields["protocol"].get(),
                )
                if self.config_manager is not None:
                    self.config_manager.add_tuya_profile(profile)
                self._reload_bulbs()
            except (ProfileStoreError, ValueError) as error:
                messagebox.showerror("Could not save light", str(error), parent=window)
                return
            window.destroy()
            self._refresh_profile_list()
            messagebox.showinfo(
                "Light saved",
                "TuyaSync saved the plain local profile and is checking the light on your LAN. If the address was blank, discovery will fill it in automatically.",
                parent=self.root,
            )

        self._button(footer, "Save and connect", save, "primary").pack(side="right")
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def import_light_profile(self):
        if self.profile_store is None:
            return
        source = filedialog.askopenfilename(
            parent=self.root,
            title="Import TuyaSync light profile",
            filetypes=(("TuyaSync light profile", "*.tuyasync-profile.json"), ("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not source:
            return
        try:
            profile = self.profile_store.import_profile(source)
            if self.config_manager is not None:
                self.config_manager.add_tuya_profile(profile)
            self._reload_bulbs()
            self._refresh_profile_list()
            messagebox.showinfo("Light imported", f"{profile.name} is ready on this computer.", parent=self.root)
        except ProfileStoreError as error:
            messagebox.showerror("Could not import light", str(error), parent=self.root)

    def export_light_profile(self):
        profile = self._selected_profile()
        if profile is None:
            messagebox.showinfo("Export light", "Add or import a light profile first.", parent=self.root)
            return
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export TuyaSync light profile",
            defaultextension=".tuyasync-profile.json",
            initialfile=f"{profile.name}.tuyasync-profile.json",
            filetypes=(("TuyaSync light profile", "*.tuyasync-profile.json"), ("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not destination:
            return
        try:
            self.profile_store.export_profile(profile.profile_id, destination)
        except ProfileStoreError as error:
            messagebox.showerror("Could not export light", str(error), parent=self.root)
            return
        messagebox.showinfo("Light exported", "The plain profile file is ready to copy to the other computer. Keep it private because it contains the Local Key.", parent=self.root)

    def remove_light_profile(self):
        profile = self._selected_profile()
        if profile is None:
            return
        if not messagebox.askyesno(
            "Remove light profile",
            f"Remove {profile.name} from this computer? This deletes its saved Local Key from the local profile file.",
            parent=self.root,
        ):
            return
        try:
            self.profile_store.remove_profile(profile.profile_id)
            if self.config_manager is not None:
                self.config_manager.remove_profile(profile.profile_id)
            self._reload_bulbs()
            self._refresh_profile_list()
        except ProfileStoreError as error:
            messagebox.showerror("Could not remove light", str(error), parent=self.root)

    def _reload_bulbs(self):
        if self.bulb_factory is None:
            self._refresh_profile_summary()
            return
        try:
            self.mode_manager.stop()
            bulbs = self.bulb_factory.create_bulbs()
            self.coordinator.update_bulbs(bulbs)
            self.startup_error = None
        except (ProfileStoreError, RuntimeError) as error:
            messagebox.showerror("Could not connect light", str(error), parent=self.root)
        self._refresh_profile_summary()

    def _screen_choice_changed(self):
        self.apply_settings()

    def open_screen_choice_guide(self):
        window = tk.Toplevel(self.root)
        self._window_base(window, "Screen Sync choices", "These controls change how the screen is translated into one room-filling color.", 620, 650)
        scroll_host = tk.Frame(window, bg=COLORS["window"])
        scroll_host.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        scroll_host.rowconfigure(0, weight=1)
        scroll_host.columnconfigure(0, weight=1)
        canvas, content = self._scrollable_content(scroll_host, COLORS["window"], with_scrollbar=True)
        previous_scroll_canvas = self._active_scroll_canvas
        self._active_scroll_canvas = canvas

        algorithm = self._card(content)
        algorithm.pack(fill="x", pady=(0, 12))
        self._heading(algorithm, "Algorithm", "Choose what part of the image should define the room color.")
        for name, (title, copy) in ALGORITHM_GUIDE.items():
            row = tk.Frame(algorithm, bg=COLORS["surface"])
            row.pack(fill="x", padx=20, pady=(0, 10))
            label = f"{name}  ·  {title}" if title else name
            tk.Label(row, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(row, text=copy, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=530, justify="left").pack(anchor="w", pady=(2, 0))
        response = self._card(content)
        response.pack(fill="x")
        self._heading(response, "Response", "Choose how quickly the light should move between calculated colors.")
        for name, (title, copy) in RESPONSE_GUIDE.items():
            row = tk.Frame(response, bg=COLORS["surface"])
            row.pack(fill="x", padx=20, pady=(0, 10))
            label = f"{name}  ·  {title}" if title else name
            tk.Label(row, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(row, text=copy, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=530, justify="left").pack(anchor="w", pady=(2, 0))
        self._bind_scroll_tree(content, canvas)

        def close():
            self._active_scroll_canvas = previous_scroll_canvas
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close)

    def _select_row(self, parent, label, description, variable, values, callback=None):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", padx=20, pady=5)
        copy = tk.Frame(row, bg=COLORS["surface"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w")
        tk.Label(copy, text=description, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8), wraplength=185, justify="left").pack(anchor="w", pady=(2, 0))
        combo = ttk.Combobox(row, textvariable=variable, values=values, state="readonly", width=17, style="Light.TCombobox")
        combo.pack(side="right", padx=(8, 0))
        self._protect_combobox_wheel(combo)
        combo.bind("<<ComboboxSelected>>", lambda _event: (callback or self.apply_settings)())

    def _stepper(self, parent, label, description, variable, minimum, maximum, step, fmt):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", padx=20, pady=6)
        copy = tk.Frame(row, bg=COLORS["surface"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w")
        tk.Label(copy, text=description, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8), wraplength=185, justify="left").pack(anchor="w", pady=(2, 0))

        control = tk.Frame(row, bg=COLORS["surface_alt"], highlightbackground=COLORS["border"], highlightthickness=1)
        control.pack(side="right", padx=(8, 0))
        value = tk.StringVar(value=fmt % variable.get())

        def update(delta):
            next_value = max(minimum, min(maximum, round(float(variable.get()) + delta, 4)))
            variable.set(next_value)
            value.set(fmt % next_value)
            self.apply_settings()

        minus = ttk.Button(control, text="−", command=lambda: update(-step), style="Stepper.TButton", width=2)
        minus.pack(side="left")
        tk.Label(control, textvariable=value, width=7, bg=COLORS["surface_alt"], fg=COLORS["text"], font=(FONT, 9, "bold")).pack(side="left", padx=2)
        plus = ttk.Button(control, text="+", command=lambda: update(step), style="Stepper.TButton", width=2)
        plus.pack(side="left")

    def _circle_toggle(self, parent, label, description, variable, callback=None):
        row = tk.Frame(parent, bg=COLORS["surface"], cursor="hand2")
        row.pack(fill="x", padx=16, pady=6)
        indicator = tk.Canvas(row, width=22, height=22, bg=COLORS["surface"], highlightthickness=0)
        indicator.pack(side="left", padx=(0, 8))
        copy = tk.Frame(row, bg=COLORS["surface"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold"), cursor="hand2").pack(anchor="w")
        tk.Label(copy, text=description, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8), wraplength=250, justify="left", cursor="hand2").pack(anchor="w", pady=(2, 0))
        state_var = tk.StringVar()
        state_label = tk.Label(row, textvariable=state_var, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8, "bold"), cursor="hand2")
        state_label.pack(side="right")

        def draw():
            indicator.delete("all")
            active = bool(variable.get())
            if active:
                indicator.create_oval(2, 2, 20, 20, outline=COLORS["blue"], width=2, fill=COLORS["blue_soft"])
                indicator.create_oval(7, 7, 15, 15, outline="", fill=COLORS["blue"])
                state_var.set("On")
            else:
                indicator.create_oval(3, 3, 19, 19, outline=COLORS["border"], width=2, fill=COLORS["surface"])
                state_var.set("Off")

        def toggle(_event=None):
            variable.set(not variable.get())
            draw()
            (callback or self.apply_settings)()

        for widget in (row, indicator, copy, *copy.winfo_children()):
            widget.bind("<Button-1>", toggle)
        state_label.bind("<Button-1>", toggle)
        draw()

    def _sync_toggle(self, parent):
        row = tk.Frame(parent, bg=COLORS["surface"], cursor="hand2")
        row.pack(fill="x", padx=16, pady=(0, 14))
        indicator = tk.Canvas(row, width=28, height=28, bg=COLORS["surface"], highlightthickness=0)
        indicator.pack(side="left", padx=(0, 10))
        label = tk.Label(row, text="Ambient sync", bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 11, "bold"), cursor="hand2")
        label.pack(side="left")
        state = tk.StringVar()
        state_label = tk.Label(row, textvariable=state, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9, "bold"), cursor="hand2")
        state_label.pack(side="right")

        def draw():
            indicator.delete("all")
            if self.mode_manager.active_mode != "off":
                indicator.create_oval(2, 2, 26, 26, outline=COLORS["blue"], width=2, fill=COLORS["blue_soft"])
                indicator.create_oval(8, 8, 20, 20, outline="", fill=COLORS["blue"])
                state.set("On")
            else:
                indicator.create_oval(3, 3, 25, 25, outline=COLORS["border"], width=2, fill=COLORS["surface"])
                state.set("Off")

        def toggle(_event=None):
            self.stop() if self.mode_manager.active_mode != "off" else self.start()
            draw()

        for widget in (row, indicator, label, state_label):
            widget.bind("<Button-1>", toggle)
        self._draw_quick_sync = draw
        draw()

    def _build_status(self, body):
        main = self._card(body)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        header = tk.Frame(main, bg=COLORS["surface"])
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 17))
        tk.Label(header, text="Ambient sync", bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 19, "bold")).pack(anchor="w")
        tk.Label(header, text="Control how the batten responds to the selected display.", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 10)).pack(anchor="w", pady=(4, 0))

        state = tk.Frame(main, bg=COLORS["surface_alt"], highlightbackground="#E7E8EC", highlightthickness=1)
        state.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 18))
        state.columnconfigure(0, weight=1)
        state.columnconfigure(1, weight=1)
        state.rowconfigure(1, weight=1)

        summary = tk.Frame(state, bg=COLORS["surface_alt"])
        summary.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(22, 12))
        self.status_icon = tk.Canvas(summary, width=48, height=48, bg=COLORS["surface_alt"], highlightthickness=0)
        self.status_icon.pack(side="left", padx=(0, 13))
        self.status_icon.create_oval(4, 4, 44, 44, outline=COLORS["border"], width=2, fill=COLORS["surface"])
        self.status_icon.create_oval(18, 18, 30, 30, outline="", fill=COLORS["tertiary"])
        copy = tk.Frame(summary, bg=COLORS["surface_alt"])
        copy.pack(side="left", fill="x", expand=True)
        self.sync_state_title_var = tk.StringVar(value="Ready")
        tk.Label(copy, textvariable=self.sync_state_title_var, bg=COLORS["surface_alt"], fg=COLORS["text"], font=(DISPLAY_FONT, 16, "bold")).pack(anchor="w")
        self.live_status_var = tk.StringVar(value="Press Start Sync when you want to drive the batten.")
        tk.Label(copy, textvariable=self.live_status_var, bg=COLORS["surface_alt"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=390, justify="left").pack(anchor="w", pady=(3, 0))

        details = tk.Frame(state, bg=COLORS["surface"])
        details.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=20, pady=(0, 18))
        details.columnconfigure(1, weight=1)
        details.columnconfigure(3, weight=1)
        self.detail_vars = {}
        detail_specs = (("algorithm", "Algorithm"), ("monitor", "Monitor"), ("response", "Response"), ("vividness", "Transport"), ("rgb", "Current RGB"), ("brightness", "Brightness"))
        for index, (key, label) in enumerate(detail_specs):
            row, column = divmod(index, 2)
            row *= 2
            base = column * 2
            tk.Label(details, text=label, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 8)).grid(row=row, column=base, sticky="w", padx=(13, 8), pady=(11, 1))
            value = tk.StringVar(value="—")
            self.detail_vars[key] = value
            tk.Label(details, textvariable=value, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 9, "bold"), anchor="w").grid(row=row + 1, column=base, sticky="w", padx=(13, 8), pady=(0, 11))
        for column in range(4):
            details.columnconfigure(column, weight=1 if column in (1, 3) else 0)

        actions = tk.Frame(state, bg=COLORS["surface_alt"])
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 20))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self._button(actions, "Start Sync", self.start, "primary").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._button(actions, "Stop Sync", self.stop, "stop").grid(row=0, column=1, sticky="ew")

        self._build_metrics(main)

    def _metric_tile(self, parent, column, key, label):
        tile = tk.Frame(parent, bg=COLORS["surface_alt"], highlightbackground="#E6E7EB", highlightthickness=1)
        tile.grid(row=0, column=column, sticky="nsew", padx=4, pady=4)
        tk.Label(tile, text=label, bg=COLORS["surface_alt"], fg=COLORS["secondary"], font=(FONT, 8)).pack(anchor="w", padx=11, pady=(8, 1))
        variable = tk.StringVar(value="—")
        self.metric_vars[key] = variable
        tk.Label(tile, textvariable=variable, bg=COLORS["surface_alt"], fg=COLORS["text"], font=(FONT, 10, "bold")).pack(anchor="w", padx=11, pady=(0, 9))

    def _build_metrics(self, parent):
        metrics = self._card(parent)
        metrics.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 22))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)
        self.metric_vars = {}
        for column, (key, label) in enumerate((("capture_fps", "Capture"), ("lighting_hz", "Command rate"), ("final_brightness", "Brightness"), ("current_rgb", "Final RGB"))):
            self._metric_tile(metrics, column, key, label)
        self.device_footer = tk.StringVar(value="Device —  ·  latency —  ·  0 failed")
        tk.Label(metrics, textvariable=self.device_footer, bg=COLORS["surface"], fg=COLORS["tertiary"], font=(FONT, 8)).grid(row=1, column=0, columnspan=4, sticky="w", padx=9, pady=(3, 10))

    def apply_settings(self):
        settings = SyncSettings(
            algorithm=self.algorithm_var.get(),
            monitor_index=self.monitor_by_label.get(self.monitor_var.get(), 1),
            update_rate=float(self.update_rate_var.get()),
            output_transport=self.transport_var.get(),
            dp28_transition=self.settings.dp28_transition,
            capture_fps=max(15.0, float(self.update_rate_var.get()) * 3),
            analysis_width=int(self.analysis_width_var.get()),
            color_smoothing=float(self.smoothing_var.get()),
            responsiveness=float(self.responsiveness_var.get()),
            response_profile=self.response_profile_var.get(),
            saturation_boost=float(self.saturation_boost_var.get()),
            color_deadband=float(self.deadband_var.get()),
            minimum_brightness=float(self.minimum_brightness_var.get()),
            maximum_brightness=max(float(self.minimum_brightness_var.get()), float(self.maximum_brightness_var.get())),
            brightness_gamma=float(self.gamma_var.get()),
            black_scene_threshold=float(self.black_threshold_var.get()),
            black_bar_threshold=float(self.black_bar_threshold_var.get()),
            ignore_black_bars=bool(self.ignore_bars_var.get()),
            reduce_static_ui=bool(self.reduce_static_ui_var.get()),
            static_ui_weight=float(self.static_ui_weight_var.get()),
            white_background_weight=float(self.white_background_weight_var.get()),
            use_dedicated_white=self.white_handling_var.get() == "Auto dedicated white",
            white_enter_delay=float(self.white_enter_delay_var.get()),
            white_exit_delay=float(self.white_exit_delay_var.get()),
            turn_off_on_black=bool(self.turn_off_black_var.get()),
            black_off_delay=float(self.black_delay_var.get()),
            brightness_attack=float(self.attack_var.get()),
            brightness_release=float(self.release_var.get()),
            red_gain=float(self.red_gain_var.get()),
            green_gain=float(self.green_gain_var.get()),
            blue_gain=float(self.blue_gain_var.get()),
            output_saturation=float(self.output_saturation_var.get()),
            output_gamma=float(self.output_gamma_var.get()),
        )
        self.settings = settings
        self.coordinator.set_settings(settings)

    def _set_status(self, running, info=None):
        connected = bool((info or {}).get("connected"))
        if connected:
            background, foreground, dot, text = COLORS["green_soft"], "#227A3F", COLORS["green"], "Connected"
        else:
            background, foreground, dot, text = COLORS["red_soft"], "#A52B24", COLORS["red"], "Disconnected"
        self.status_var.set(text)
        self.status_pill.configure(bg=background)
        self.status_dot.configure(bg=background)
        self.status_dot.itemconfigure(1, fill=dot)
        self.status_label.configure(bg=background, fg=foreground)
        if hasattr(self, "sync_state_title_var"):
            self.sync_state_title_var.set("Syncing" if running else "Sync stopped")
            self.status_icon.configure(bg=COLORS["surface_alt"])
            self.status_icon.itemconfigure(1, outline=dot, fill=COLORS["surface"])
            self.status_icon.itemconfigure(2, fill=dot)

    def start(self):
        if not self.coordinator.bulbs:
            self.open_profile_manager()
            return
        self.apply_settings()
        self._switch_mode("screen")
        self._set_status(self.mode_manager.active_mode != "off", self.coordinator.device_info())

    def stop(self):
        self._switch_mode("off")
        self._set_status(False, self.coordinator.device_info())

    def enqueue(self, action: str) -> None:
        self._actions.put(action)

    def _drain_actions(self) -> bool:
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                return True
            if action == "start":
                self.start()
            elif action == "stop":
                self.stop()
            elif action.startswith("mode:"):
                self._switch_mode(action.split(":", 1)[1])
            elif action == "quick":
                self.open_quick_settings()
            elif action == "show":
                self.show_settings()
            elif action == "diagnostics":
                self.open_diagnostics()
            elif action == "quit":
                self.quit()
                return False

    def _refresh_music_page(self):
        if not self.music_mode:
            return
        status = self.music_mode.diagnostics()
        error = str(status.get("error") or status.get("last_error") or "")
        if error:
            self.music_status_var.set(error)
        elif self.mode_manager.active_mode == "music":
            self.music_status_var.set(f"Listening  ·  {status.get('backend', 'system audio')}")
        else:
            self.music_status_var.set("System audio is ready")
        meters = {
            "energy": float(status.get("normalized_energy", 0.0)),
            "beat": float(status.get("beat_strength", 0.0)),
            "pulse": float(getattr(self.music_mode, "_beat_flash", 0.0)),
        }
        for name, value in meters.items():
            self.music_band_vars[name].set(f"{value * 100:.0f}%")
        width = max(180, self.music_visualizer.winfo_width())
        height = max(120, self.music_visualizer.winfo_height())
        self.music_visualizer.delete("all")
        colours = ("#FF9F0A", COLORS["blue"], "#AF52DE")
        bar_width = width / 5
        for index, (name, value) in enumerate(meters.items(), start=1):
            x1 = index * bar_width
            x2 = x1 + bar_width
            y2 = height - 16
            y1 = y2 - max(4, min(height - 28, value * (height - 28)))
            self.music_visualizer.create_rectangle(x1, y1, x2, y2, fill=colours[index - 1], outline="")
        rgb = tuple(int(max(0, min(255, value))) for value in getattr(self.music_mode, "_last_colour", (128, 128, 128)))
        self.music_colour_swatch.delete("all")
        self.music_colour_swatch.create_oval(5, 5, 71, 71, fill=_rgb_hex(rgb), outline="")
        beat = "Beat detected" if status.get("beat") else "Between beats"
        self.music_analysis_var.set(
            f"{beat}  ·  beat {int(status.get('beat_count', 0))}  ·  "
            f"energy {float(status.get('normalized_energy', 0.0)) * 100:.0f}%  ·  {_rgb_text(rgb)}"
        )

    def _refresh_album_art_page(self):
        if not self.album_art_mode:
            return
        current = self.album_art_mode.current()
        if current.has_track:
            self.album_track_var.set(current.title or "Untitled track")
            self.album_artist_var.set(current.artist)
            self.album_name_var.set(current.album)
            if self.album_art_mode.settings.music_reactive and current.is_playing:
                response = self.album_art_mode.settings.colour_response
                response_copy = "immediate colour flashes" if response == "Immediate flash" else "smooth colour blends"
                self.album_art_status_var.set(f"Beat reactive  ·  {response_copy} + brightness pulse")
            else:
                self.album_art_status_var.set("Playing" if current.is_playing else "Paused  ·  holding the colour at reduced brightness")
        else:
            self.album_track_var.set("No active Spotify track")
            self.album_artist_var.set("")
            self.album_name_var.set("")
            self.album_art_status_var.set("Waiting for a local Spotify desktop track")
        diagnostics = self.album_art_mode.diagnostics()
        rgb = tuple(int(value) for value in diagnostics.get("current_rgb", diagnostics.get("extracted_rgb", (128, 128, 128))))
        palette = tuple(tuple(int(channel) for channel in colour) for colour in diagnostics.get("extracted_palette", (rgb,)))
        palette_mode = str(diagnostics.get("palette_mode", "Single color"))
        palette_index = int(diagnostics.get("palette_index", 0))
        self.album_art_colour_var.set(f"Current  {_rgb_text(rgb)}  ·  {palette_mode}")
        self.album_art_swatch.delete("all")
        self.album_art_swatch.create_oval(8, 8, 142, 142, fill=_rgb_hex(rgb), outline="")
        for index, colour in enumerate(palette):
            x1 = 16 + index * 36
            outline = COLORS["text"] if index == palette_index else COLORS["border"]
            self.album_art_swatch.create_oval(x1, 116, x1 + 24, 140, fill=_rgb_hex(colour), outline=outline, width=2)
        artwork = self.album_art_mode.artwork()
        if artwork:
            try:
                image = Image.open(BytesIO(artwork)).convert("RGB")
                image.thumbnail((210, 210), Image.Resampling.LANCZOS)
                self._album_art_photo = ImageTk.PhotoImage(image)
                self.album_art_image_label.configure(image=self._album_art_photo, text="")
            except Exception:
                self.album_art_image_label.configure(image="", text="Artwork unavailable")

    def show_settings(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_settings(self):
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.withdraw()
        self.root.withdraw()

    def open_quick_settings(self):
        if self._quick_window and self._quick_window.winfo_exists():
            self._quick_window.deiconify()
            self._quick_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._quick_window = window
        self._window_base(window, "TuyaSync", "Quick controls — closing this window does not stop sync.", 460, 650)
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        self.quick_status_var = tk.StringVar(value=self.MODE_LABELS.get(self.mode_manager.active_mode, "Off"))
        tk.Label(card, textvariable=self.quick_status_var, bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 16, "bold")).pack(anchor="w", padx=18, pady=(17, 10))
        self._sync_toggle(card)
        self._select_row(card, "Monitor", "Display used for ambient colour.", self.monitor_var, [label for _, label in self.monitor_options])
        self._select_row(card, "Algorithm", "Recommended: Saturated for most content.", self.algorithm_var, PRIMARY_ALGORITHMS, self._screen_choice_changed)
        self._stepper(card, "Maximum update rate", "Upper command-rate limit for active scenes.", self.update_rate_var, 1, 15, 1, "%.0f Hz")
        self._stepper(card, "Maximum brightness", "Upper limit while syncing.", self.maximum_brightness_var, 10, 100, 5, "%.0f%%")
        quick_colour = self._advanced_section(card, "Quick color", "Choose a color or open the native picker. Selecting one stops any automatic mode first.")
        swatches = tk.Frame(quick_colour, bg=COLORS["surface"])
        swatches.pack(fill="x", padx=16, pady=(0, 7))
        for rgb in ((255, 55, 55), (255, 170, 30), (40, 215, 110), (35, 165, 255), (150, 70, 255), (255, 70, 190), (255, 255, 255)):
            _colour_swatch(swatches, rgb, lambda value=rgb: self._manual_colour(value), size=28).pack(side="left", padx=2)
        self.quick_colour_label = tk.Label(quick_colour, text=f"Current selection  ·  {_rgb_text(self.manual_rgb)}", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9))
        self.quick_colour_label.pack(anchor="w", padx=16, pady=(0, 3))
        self._button(quick_colour, "Open color picker…", self._choose_manual_colour).pack(fill="x", padx=16, pady=(0, 14))
        self._button(card, "Explain screen choices…", self.open_screen_choice_guide).pack(fill="x", padx=20, pady=(0, 14))
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def refresh(self):
        if not self._drain_actions():
            return
        snapshot = self.coordinator.metrics_snapshot()
        info = self.coordinator.device_info()
        active_mode = self.mode_manager.active_mode
        running = active_mode != "off"
        self._set_status(running, info)
        if running and active_mode == "screen":
            self.live_status_var.set(str(info.get("message", "Syncing over the local LAN.")))
        elif active_mode == "off":
            self.live_status_var.set("No automatic mode owns the batten.")
        self.metric_vars["capture_fps"].set(f"{snapshot['capture_fps']:.1f} fps")
        self.metric_vars["lighting_hz"].set(f"{snapshot['lighting_hz']:.1f} Hz")
        self.metric_vars["final_brightness"].set(f"{snapshot['final_brightness'] * 100:.1f}%")
        self.metric_vars["current_rgb"].set(_rgb_text(snapshot["final_rgb"]))
        self.detail_vars["algorithm"].set(self.algorithm_var.get())
        self.detail_vars["monitor"].set(self.monitor_var.get())
        self.detail_vars["response"].set(self.response_profile_var.get())
        self.detail_vars["vividness"].set(self.transport_var.get())
        self.detail_vars["rgb"].set(_rgb_text(snapshot["final_rgb"]))
        self.detail_vars["brightness"].set(f"{snapshot['final_brightness'] * 100:.1f}%")
        self.device_footer.set(f"{str(info['state']).title()}  ·  {info['ip']}  ·  Tuya v{info['protocol']}  ·  latency {snapshot['average_latency_ms']:.1f} ms  ·  {snapshot['failed_commands']} failed")
        if self.tray:
            self.tray.refresh()
        if self._diagnostics_window and self._diagnostics_window.winfo_exists():
            self._refresh_diagnostics(snapshot, info)
        if self._calibration_window and self._calibration_window.winfo_exists():
            self._refresh_calibration(snapshot)
        if self._quick_window and self._quick_window.winfo_exists():
            connection = "Connected" if info.get("connected") else "Disconnected"
            sync = self.MODE_LABELS.get(active_mode, "Off") if running else "Sync stopped"
            self.quick_status_var.set(f"{sync} · {connection}")
            self._draw_quick_sync()
        self._refresh_music_page()
        self._refresh_album_art_page()
        self._refresh_job = self.root.after(250, self.refresh)

    def _window_base(self, window, title, subtitle, width, height):
        window.title(title)
        window.geometry(f"{width}x{height}")
        window.minsize(width - 80, height - 80)
        window.configure(bg=COLORS["window"])
        header = tk.Frame(window, bg=COLORS["window"])
        header.pack(fill="x", padx=22, pady=(20, 8))
        tk.Label(header, text=title, bg=COLORS["window"], fg=COLORS["text"], font=(DISPLAY_FONT, 18, "bold")).pack(anchor="w")
        tk.Label(header, text=subtitle, bg=COLORS["window"], fg=COLORS["secondary"], font=(FONT, 9)).pack(anchor="w", pady=(3, 0))

    def _advanced_section(self, parent, title, subtitle):
        card = self._card(parent)
        card.pack(fill="x", pady=(0, 12))
        header = tk.Frame(card, bg=COLORS["surface"])
        header.pack(fill="x", padx=16, pady=(13, 5))
        tk.Label(header, text=title, bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 13, "bold")).pack(anchor="w")
        tk.Label(header, text=subtitle, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).pack(anchor="w", pady=(2, 0))
        return card

    def open_fine_tune(self):
        if self._fine_tune_window and self._fine_tune_window.winfo_exists():
            self._fine_tune_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._fine_tune_window = window
        self._window_base(window, "Fine tune", "Advanced controls apply immediately while syncing.", 720, 820)
        notebook = ttk.Notebook(window, style="Minimal.TNotebook")
        notebook.pack(fill="both", expand=True, padx=22, pady=(2, 22))

        brightness_tab = tk.Frame(notebook, bg=COLORS["window"])
        notebook.add(brightness_tab, text="Colour & brightness")
        brightness = self._advanced_section(brightness_tab, "Brightness curve", "Set the floor, ceiling, and response of the ambient light.")
        self._stepper(brightness, "Minimum ambient", "The lowest brightness used for non-black scenes.", self.minimum_brightness_var, 0, 50, 1, "%.0f%%")
        self._stepper(brightness, "Maximum brightness", "The brightest the light is allowed to become.", self.maximum_brightness_var, 10, 100, 1, "%.0f%%")
        self._stepper(brightness, "Brightness gamma", "Shape how quickly brightness rises with screen intensity.", self.gamma_var, 0.4, 2.5, 0.05, "%.2f")
        self._stepper(brightness, "Brightness attack", "How quickly the light brightens after a change.", self.attack_var, 0.01, 1.0, 0.01, "%.2fs")
        self._stepper(brightness, "Brightness release", "How gently the light fades after a change.", self.release_var, 0.05, 2.0, 0.05, "%.2fs")
        colour = self._advanced_section(brightness_tab, "Colour transition", "Reduce abrupt changes without hiding the scene.")
        self._stepper(colour, "Colour smoothing", "How long colour changes take to settle.", self.smoothing_var, 0.01, 1.2, 0.01, "%.2fs")
        self._stepper(colour, "Colour deadband", "Ignore tiny RGB changes that would only create flicker.", self.deadband_var, 0, 30, 1, "%.0f")

        black_tab = tk.Frame(notebook, bg=COLORS["window"])
        notebook.add(black_tab, text="Black scenes")
        black = self._advanced_section(black_tab, "Black-scene detection", "Keep dark content and letterbox bars from affecting the light.")
        self._stepper(black, "Scene threshold", "Brightness below this value counts as a black scene.", self.black_threshold_var, 0, 60, 1, "%.0f")
        self._stepper(black, "Bar threshold", "Darkness used when finding black bars at the screen edges.", self.black_bar_threshold_var, 0, 60, 1, "%.0f")
        self._circle_toggle(black, "Ignore black bars", "Skip detected letterbox bars when calculating colour.", self.ignore_bars_var)
        self._circle_toggle(black, "Turn off on prolonged black", "Power the batten off after a sustained black scene.", self.turn_off_black_var)
        self._stepper(black, "Black-off delay", "How long a black scene must last before shutoff.", self.black_delay_var, 1, 20, 0.5, "%.1fs")

        hardware_tab = tk.Frame(notebook, bg=COLORS["window"])
        notebook.add(hardware_tab, text="Hardware")
        hardware = self._advanced_section(hardware_tab, "DS22000 output", "Use the dedicated white channel for neutral scenes.")
        self._select_row(hardware, "White output", "Route stable neutral scenes through dedicated white LEDs.", self.white_handling_var, ("RGB only", "Auto dedicated white"))
        self._stepper(hardware, "Enter white delay", "Neutral content must persist before switching channels.", self.white_enter_delay_var, 0.2, 2.0, 0.1, "%.1fs")
        self._stepper(hardware, "Exit white delay", "Colour must persist before returning to RGB.", self.white_exit_delay_var, 0.1, 1.5, 0.1, "%.1fs")
        self._select_row(hardware, "Analysis resolution", "Downsample immediately after capture for low latency.", self.analysis_width_var, (64, 96))
        weighting = self._advanced_section(hardware_tab, "Scene weighting", "Keep subtitles and static bright interfaces from overpowering the scene.")
        self._circle_toggle(weighting, "Reduce subtitles and static UI", "Prefer changing scene content over unmoving overlays.", self.reduce_static_ui_var)
        self._stepper(weighting, "Static content influence", "How much unmoving content contributes to the colour.", self.static_ui_weight_var, 0.05, 1.0, 0.05, "%.2f×")
        self._stepper(weighting, "White background influence", "How much large neutral white areas contribute.", self.white_background_weight_var, 0.02, 1.0, 0.02, "%.2f×")
        calibration_tab = tk.Frame(notebook, bg=COLORS["window"])
        notebook.add(calibration_tab, text="Calibration")
        calibration = self._advanced_section(calibration_tab, "Device calibration", "Correct the physical DS22000 output after screen analysis.")
        self._stepper(calibration, "Red gain", "Scale the batten's red channel.", self.red_gain_var, 0.5, 1.5, 0.05, "%.2f×")
        self._stepper(calibration, "Green gain", "Scale the batten's green channel.", self.green_gain_var, 0.5, 1.5, 0.05, "%.2f×")
        self._stepper(calibration, "Blue gain", "Scale the batten's blue channel.", self.blue_gain_var, 0.5, 1.5, 0.05, "%.2f×")
        self._stepper(calibration, "Output saturation", "Adjust colour richness at the device boundary.", self.output_saturation_var, 0.5, 1.5, 0.05, "%.2f×")
        self._stepper(calibration, "Output gamma", "Adjust final device intensity without changing analysis.", self.output_gamma_var, 0.5, 1.8, 0.05, "%.2f")
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def open_diagnostics(self):
        if self._diagnostics_window and self._diagnostics_window.winfo_exists():
            self._diagnostics_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._diagnostics_window = window
        self._window_base(window, "Diagnostics", "A live view of the capture, connection, and command path.", 900, 700)
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        self.diagnostic_vars = {}
        rows = (
            ("connection", "Connection state"), ("connection_message", "Connection detail"),
            ("capture_fps", "Capture FPS"), ("processing_fps", "Processing FPS"),
            ("requested_hz", "Requested max Hz"), ("lighting_hz", "Actual sent Hz"), ("transport", "Output transport"),
            ("raw_rgb", "Desired RGB"), ("smoothed_rgb", "Smoothed RGB"),
            ("final_rgb", "Final output RGB"), ("final_brightness", "Final brightness"),
            ("average_latency_ms", "Average command latency"), ("p95_latency_ms", "P95 command latency"),
            ("deadband_skips", "Deadband skips"), ("rate_limit_skips", "Rate-limit skips"),
            ("overwritten_states", "Overwritten stale states"), ("processing_failures", "Processing failures"),
            ("failed_commands", "Command failures"),
            ("device", "Device / protocol"), ("monitor", "Monitor"),
            ("retry", "Reconnect / failures"), ("last_error", "Last connection error"),
        )
        column_height = (len(rows) + 1) // 2
        for index, (key, label) in enumerate(rows):
            row, group = index % column_height, index // column_height
            label_column = group * 2
            tk.Label(card, text=label, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).grid(row=row, column=label_column, sticky="w", padx=(16, 8), pady=7)
            value = tk.StringVar(value="—")
            self.diagnostic_vars[key] = value
            tk.Label(card, textvariable=value, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold"), anchor="e").grid(row=row, column=label_column + 1, sticky="e", padx=(8, 16), pady=7)
            card.columnconfigure(label_column + 1, weight=1)
        tk.Label(card, text="Intentional skips are separate from command failures. The newest desired state replaces stale unsent states.", bg=COLORS["surface"], fg=COLORS["tertiary"], font=(FONT, 9), wraplength=800, justify="left").grid(row=column_height, column=0, columnspan=4, sticky="w", padx=16, pady=(16, 14))
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def _refresh_diagnostics(self, snapshot, info):
        self.diagnostic_vars["connection"].set("Connected" if info.get("connected") else str(info.get("state", "Disconnected")).title())
        self.diagnostic_vars["connection_message"].set(str(info.get("message", "—")))
        self.diagnostic_vars["capture_fps"].set(f"{snapshot['capture_fps']:.1f} fps")
        self.diagnostic_vars["processing_fps"].set(f"{snapshot['processing_fps']:.1f} fps")
        self.diagnostic_vars["requested_hz"].set(f"{self.update_rate_var.get():.1f} Hz")
        self.diagnostic_vars["lighting_hz"].set(f"{snapshot['lighting_hz']:.1f} Hz")
        self.diagnostic_vars["transport"].set(self.coordinator.get_settings().output_transport)
        self.diagnostic_vars["raw_rgb"].set(_rgb_text(snapshot["raw_rgb"]))
        self.diagnostic_vars["smoothed_rgb"].set(_rgb_text(snapshot["smoothed_rgb"]))
        self.diagnostic_vars["final_rgb"].set(_rgb_text(snapshot["final_rgb"]))
        self.diagnostic_vars["final_brightness"].set(f"{snapshot['final_brightness'] * 100:.1f}%")
        self.diagnostic_vars["average_latency_ms"].set(f"{snapshot['average_latency_ms']:.1f} ms")
        self.diagnostic_vars["p95_latency_ms"].set(f"{snapshot['p95_latency_ms']:.1f} ms")
        self.diagnostic_vars["deadband_skips"].set(str(snapshot["deadband_skips"]))
        self.diagnostic_vars["rate_limit_skips"].set(str(snapshot["rate_limit_skips"]))
        self.diagnostic_vars["overwritten_states"].set(str(snapshot["overwritten_states"]))
        self.diagnostic_vars["processing_failures"].set(str(snapshot["processing_failures"]))
        self.diagnostic_vars["failed_commands"].set(str(snapshot["failed_commands"]))
        self.diagnostic_vars["device"].set(f"{info['ip']} · Tuya {info['protocol']}")
        self.diagnostic_vars["monitor"].set(self.monitor_var.get())
        retry = float(info.get("retry_in", 0.0))
        self.diagnostic_vars["retry"].set(
            f"{retry:.1f}s · {info.get('failure_count', 0)} failures · "
            f"{info.get('reconnect_count', 0)} reconnects"
        )
        self.diagnostic_vars["last_error"].set(str(info.get("last_error") or "—")[:72])

    def open_calibration(self):
        if self._calibration_window and self._calibration_window.winfo_exists():
            self._calibration_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._calibration_window = window
        self._window_base(window, "Calibration / Debug", "Inspect the pipeline without showing the captured screen.", 650, 560)
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        tk.Label(card, text="Pipeline values", bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 2))
        tk.Label(card, text="The capture remains private; only calculated values are shown here.", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 15))
        self.calibration_vars = {}
        for row, (key, label) in enumerate((("raw_rgb", "Raw calculated RGB"), ("smoothed_rgb", "Smoothed RGB"), ("final_rgb", "Final RGB"), ("final_brightness", "Final brightness"), ("actual_command_rate", "Actual command rate"), ("region", "Selected region"), ("black", "Black scene")), start=2):
            tk.Label(card, text=label, bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9)).grid(row=row, column=0, sticky="w", padx=16, pady=7)
            value = tk.StringVar(value="—")
            self.calibration_vars[key] = value
            tk.Label(card, textvariable=value, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold"), anchor="e").grid(row=row, column=1, sticky="e", padx=16, pady=7)
            card.columnconfigure(1, weight=1)
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def _refresh_calibration(self, snapshot):
        self.calibration_vars["raw_rgb"].set(_rgb_text(snapshot["raw_rgb"]))
        self.calibration_vars["smoothed_rgb"].set(_rgb_text(snapshot["smoothed_rgb"]))
        self.calibration_vars["final_rgb"].set(_rgb_text(snapshot["final_rgb"]))
        self.calibration_vars["final_brightness"].set(f"{snapshot['final_brightness'] * 100:.1f}%")
        self.calibration_vars["actual_command_rate"].set(f"{snapshot['actual_command_rate']:.1f} Hz")
        self.calibration_vars["region"].set(f"{snapshot['selected_region']} in {snapshot['analysis_size']} · source {snapshot['source_size']}")
        self.calibration_vars["black"].set("Yes" if snapshot["is_black"] else "No")

    def open_preferences(self):
        window = tk.Toplevel(self.root)
        self._window_base(window, "Preferences", "Save your tuning for the next launch.", 560, 350)
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=22, pady=(2, 22))
        tk.Label(card, text="Your TuyaSync profile", bg=COLORS["surface"], fg=COLORS["text"], font=(DISPLAY_FONT, 14, "bold")).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(card, text="Settings are applied live. This file stores tuning values only, never Tuya credentials.", bg=COLORS["surface"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=490, justify="left").pack(anchor="w", padx=16, pady=(0, 14))
        tk.Label(card, text=f"Settings file\n{SETTINGS_PATH}", bg=COLORS["surface_alt"], fg=COLORS["secondary"], font=(FONT, 9), wraplength=490, justify="left", padx=12, pady=10).pack(fill="x", padx=16, pady=(0, 18))
        buttons = tk.Frame(card, bg=COLORS["surface"])
        buttons.pack(fill="x", side="bottom", padx=16, pady=16)
        self._button(buttons, "Reset defaults", lambda: self.reset_defaults(window)).pack(side="left")
        self._button(buttons, "Save Preferences", lambda: self.save_preferences(window), "primary").pack(side="right")
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def save_preferences(self, window=None):
        self.apply_settings()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(self.coordinator.get_settings().to_dict(), indent=2))
        if window:
            window.destroy()

    def reset_defaults(self, window=None):
        defaults = SyncSettings()
        self.algorithm_var.set("Legacy" if defaults.algorithm == "Saturated Average" else defaults.algorithm)
        self.monitor_var.set(next((label for index, label in self.monitor_options if index == defaults.monitor_index), self.monitor_options[0][1]))
        self.update_rate_var.set(defaults.update_rate)
        self.transport_var.set(defaults.output_transport)
        self.response_profile_var.set(defaults.response_profile)
        self.white_handling_var.set("Auto dedicated white" if defaults.use_dedicated_white else "RGB only")
        self.responsiveness_var.set(defaults.responsiveness)
        self.saturation_boost_var.set(defaults.saturation_boost)
        self.minimum_brightness_var.set(defaults.minimum_brightness)
        self.maximum_brightness_var.set(defaults.maximum_brightness)
        self.gamma_var.set(defaults.brightness_gamma)
        self.black_threshold_var.set(defaults.black_scene_threshold)
        self.black_bar_threshold_var.set(defaults.black_bar_threshold)
        self.smoothing_var.set(defaults.color_smoothing)
        self.attack_var.set(defaults.brightness_attack)
        self.release_var.set(defaults.brightness_release)
        self.black_delay_var.set(defaults.black_off_delay)
        self.deadband_var.set(defaults.color_deadband)
        self.analysis_width_var.set(defaults.analysis_width)
        self.static_ui_weight_var.set(defaults.static_ui_weight)
        self.white_background_weight_var.set(defaults.white_background_weight)
        self.white_enter_delay_var.set(defaults.white_enter_delay)
        self.white_exit_delay_var.set(defaults.white_exit_delay)
        self.red_gain_var.set(defaults.red_gain)
        self.green_gain_var.set(defaults.green_gain)
        self.blue_gain_var.set(defaults.blue_gain)
        self.output_saturation_var.set(defaults.output_saturation)
        self.output_gamma_var.set(defaults.output_gamma)
        self.ignore_bars_var.set(defaults.ignore_black_bars)
        self.reduce_static_ui_var.set(defaults.reduce_static_ui)
        self.turn_off_black_var.set(defaults.turn_off_on_black)
        self.apply_settings()
        if window:
            window.destroy()

    def quit(self):
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None
        self.mode_manager.stop()
        self.coordinator.light_service.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config_path = DATA_DIR / "config.ini"
    manager = ConfigManager(str(config_path))
    profile_store = LightProfileStore(DATA_DIR)
    startup_error = None
    factory = BulbFactory(manager, profile_store=profile_store)
    try:
        # Existing development installs may still have a raw Local Key in
        # config.ini. Convert it to the local profile file before creating
        # any controller. New packaged installs simply have no profiles yet.
        profile_store.migrate_config(manager)
        bulbs = factory.create_bulbs()
    except ProfileStoreError as error:
        startup_error = str(error)
        bulbs = []
    settings = load_settings()
    metrics = RuntimeMetrics()
    light_service = LightService(bulbs, metrics, settings)
    light_service.start()
    coordinator = Coordinator(bulbs, settings=settings, light_service=light_service)
    music_mode = album_art_mode = None
    try:
        music_mode = MusicMode(light_service, system_audio_backend())
    except Exception as error:
        print(f"TuyaSync music backend unavailable: {error}", flush=True)
    try:
        album_art_mode = AlbumArtMode(
            light_service,
            spotify_backend(),
            DATA_DIR / "album-art-cache",
            audio_backend=system_audio_backend(),
        )
    except Exception as error:
        print(f"TuyaSync album-art backend unavailable: {error}", flush=True)
    scenes = list(BUILTIN_SCENES) + load_custom_scenes(SCENES_PATH)
    scenes_mode = ScenesMode(light_service, scenes[0] if scenes else None)
    modes = [coordinator, scenes_mode]
    if music_mode:
        modes.append(music_mode)
    if album_art_mode:
        modes.append(album_art_mode)
    mode_manager = ModeManager(modes, light_service.clear)
    root = tk.Tk()
    try:
        with Image.open(APP_ICON_PATH) as icon:
            root_icon = ImageTk.PhotoImage(icon.resize((128, 128), Image.LANCZOS))
        root.iconphoto(True, root_icon)
        root._tuyasync_icon = root_icon
    except (OSError, tk.TclError):
        pass
    app = TuyaSyncApp(
        root,
        coordinator,
        mode_manager,
        music_mode,
        album_art_mode,
        scenes_mode,
        scenes,
        profile_store=profile_store,
        config_manager=manager,
        bulb_factory=factory,
        startup_error=startup_error,
    )
    try:
        from screensync.tray import TrayController
        app.tray = TrayController(app)
        app.tray.start()
    except Exception as error:
        print(f"TuyaSync tray unavailable: {error}", flush=True)
    root.mainloop()


if __name__ == "__main__":
    main()
