"""Share a light profile with the TuyaSync Android app through a QR code."""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

import segno

from screensync.light_profiles import LightProfile, LightProfileStore, ProfileStoreError


def share_payload(profile: LightProfile) -> str:
    """Return the compact profile export that the Android app scans.

    It is the same format as a ``.tuyasync-profile.json`` export, minus the
    desktop-only fields, so the phone can read either one with a single parser.
    """
    return json.dumps(
        {
            "format": LightProfileStore.PROFILE_FORMAT,
            "version": LightProfileStore.EXPORT_VERSION,
            "profile": {
                "profile_id": profile.profile_id,
                "name": profile.name,
                "device_id": profile.device_id,
                "ip_address": profile.ip_address,
                "protocol": profile.protocol,
                "local_key": profile.local_key,
            },
        },
        separators=(",", ":"),
    )


def qr_png_bytes(text: str, scale: int = 8) -> bytes:
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=scale, border=3)
    return buffer.getvalue()


def qr_png_base64(text: str, scale: int = 8) -> str:
    return base64.b64encode(qr_png_bytes(text, scale)).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    from platformdirs import user_data_dir

    parser = argparse.ArgumentParser(description="Show a light profile as a QR code for the TuyaSync Android app.")
    parser.add_argument("--profile", help="Profile ID or device ID (default: the first saved light)")
    parser.add_argument("--png", type=Path, help="Write the QR code to this PNG file instead of the terminal")
    parser.add_argument("--data-dir", type=Path, default=Path(user_data_dir("TuyaSync", "TuyaSync")))
    args = parser.parse_args(argv)

    try:
        store = LightProfileStore(args.data_dir)
        profiles = store.list_profiles()
    except ProfileStoreError as error:
        print(error, file=sys.stderr)
        return 1
    if args.profile:
        profiles = [p for p in profiles if args.profile in (p.profile_id, p.device_id)]
    if not profiles:
        print("No matching light profile. Add the light in TuyaSync first.", file=sys.stderr)
        return 1

    payload = share_payload(profiles[0])
    if args.png:
        args.png.write_bytes(qr_png_bytes(payload))
        print(f"Wrote {args.png}. It contains the Local Key, so delete it after scanning.")
    else:
        segno.make(payload, error="m").terminal(compact=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
