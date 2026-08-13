"""Small dependency-free perceptual colour helpers for adaptive smoothing."""

from __future__ import annotations

import math


def _linear(channel: float) -> float:
    channel /= 255.0
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _srgb(channel: float) -> float:
    value = 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return max(0.0, min(255.0, value * 255.0))


def rgb_to_oklab(rgb) -> tuple[float, float, float]:
    red, green, blue = (_linear(float(value)) for value in rgb)
    l = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    m = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    s = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    l_, m_, s_ = math.cbrt(l), math.cbrt(m), math.cbrt(s)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_rgb(lab) -> tuple[float, float, float]:
    lightness, a, b = lab
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        _srgb(+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        _srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        _srgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    )


def distance(first, second) -> float:
    left, right = rgb_to_oklab(first), rgb_to_oklab(second)
    chroma = math.sqrt((left[1] - right[1]) ** 2 + (left[2] - right[2]) ** 2)
    luminance = abs(left[0] - right[0])
    return math.sqrt(chroma * chroma + (luminance * 1.15) ** 2)


def adaptive_time_constant(change: float, profile: str) -> float:
    profiles = {
        "Responsive": (0.18, 0.09, 0.035),
        "Balanced": (0.30, 0.15, 0.055),
        "Cinematic": (0.42, 0.24, 0.085),
    }
    slow, medium, fast = profiles.get(profile, profiles["Balanced"])
    if change <= 0.04:
        return slow
    if change <= 0.18:
        fraction = (change - 0.04) / 0.14
        return slow + (medium - slow) * fraction
    if change <= 0.36:
        fraction = (change - 0.18) / 0.18
        return medium + (fast - medium) * fraction
    return fast


def smooth(previous, target, dt: float, time_constant: float) -> tuple[float, float, float]:
    alpha = 1.0 if time_constant <= 0 else 1.0 - math.exp(-dt / time_constant)
    before, after = rgb_to_oklab(previous), rgb_to_oklab(target)
    mixed = tuple(before[index] + (after[index] - before[index]) * alpha for index in range(3))
    return oklab_to_rgb(mixed)
