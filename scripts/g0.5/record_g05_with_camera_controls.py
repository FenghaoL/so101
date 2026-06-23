#!/usr/bin/env python
"""Run LeRobot v3 recording while applying Windows UVC controls to its cameras.

LeRobot 0.5.1's OpenCV camera dataclass no longer exposes exposure fields, but
the underlying OpenCV VideoCapture object still does.  This wrapper patches
the recorder process *before* it imports ``lerobot_record``: the controls are
therefore applied to the exact handles that will write the dataset, rather than
to a separate preview process.

The PowerShell launcher supplies the JSON control map in
``G05_RECORD_CAMERA_CONTROLS``.  A failed UVC ``set`` is logged, never hidden;
camera drivers are allowed to reject unsupported controls.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import cv2


LOGGER = logging.getLogger("g05-record-camera-controls")


def load_controls() -> dict[int, dict[str, float]]:
    raw = os.environ.get("G05_RECORD_CAMERA_CONTROLS", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("G05_RECORD_CAMERA_CONTROLS is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("G05_RECORD_CAMERA_CONTROLS must be a JSON object")
    controls: dict[int, dict[str, float]] = {}
    for index, value in data.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"camera control for {index!r} must be an object")
        controls[int(index)] = {str(key): float(item) for key, item in value.items() if item is not None}
    return controls


def patch_lerobot_opencv(controls: dict[int, dict[str, float]]) -> None:
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera

    original = OpenCVCamera._configure_capture_settings

    def configure_with_controls(self: Any) -> None:
        original(self)
        try:
            index = int(self.index_or_path)
        except (TypeError, ValueError):
            return
        requested = controls.get(index)
        if not requested:
            return
        capture = self.videocapture
        if capture is None:
            raise RuntimeError(f"camera {index} is not open while applying requested controls")

        properties = {
            "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
            "exposure": cv2.CAP_PROP_EXPOSURE,
            "gain": cv2.CAP_PROP_GAIN,
        }
        for name, value in requested.items():
            if name not in properties:
                raise RuntimeError(f"unsupported camera control {name!r} for camera {index}")
            success = bool(capture.set(properties[name], value))
            actual = float(capture.get(properties[name]))
            LOGGER.info(
                "camera=%s control=%s requested=%s actual=%s success=%s",
                index,
                name,
                value,
                actual,
                success,
            )
            if not success:
                LOGGER.warning("camera %s rejected %s=%s", index, name, value)

    OpenCVCamera._configure_capture_settings = configure_with_controls


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    controls = load_controls()
    LOGGER.info("camera controls requested for indexes: %s", sorted(controls))
    patch_lerobot_opencv(controls)
    from lerobot.scripts.lerobot_record import main as lerobot_record_main

    lerobot_record_main()


if __name__ == "__main__":
    main()
