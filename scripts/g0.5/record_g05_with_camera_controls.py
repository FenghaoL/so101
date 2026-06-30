#!/usr/bin/env python
"""Run LeRobot v3 recording with the G0.5 camera contract applied at capture.

LeRobot 0.5.1's OpenCV camera dataclass no longer exposes exposure fields, but
the underlying OpenCV VideoCapture object still does.  This wrapper patches
the recorder process *before* it imports ``lerobot_record``: the controls are
therefore applied to the exact handles that will write the dataset, rather than
to a separate preview process.

The PowerShell launcher supplies UVC controls in ``G05_RECORD_CAMERA_CONTROLS``
and right-crop settings in ``G05_RECORD_CAMERA_CROPS``.  The crop is applied
after the native 640x480 frame is read and RGB-converted, so the fixed-camera
video, LeRobot metadata, and optional Rerun display all store the same square
480x480 image as the live G0.5 client.  A failed UVC ``set`` is logged, never
hidden; camera drivers are allowed to reject unsupported controls.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import cv2
import numpy as np


LOGGER = logging.getLogger("g05-record-camera-controls")


def _load_json_object(variable: str) -> dict[str, Any]:
    raw = os.environ.get(variable, "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{variable} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{variable} must be a JSON object")
    return data


def load_controls() -> dict[int, dict[str, float]]:
    data = _load_json_object("G05_RECORD_CAMERA_CONTROLS")
    controls: dict[int, dict[str, float]] = {}
    for index, value in data.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"camera control for {index!r} must be an object")
        controls[int(index)] = {str(key): float(item) for key, item in value.items() if item is not None}
    return controls


def load_crops() -> dict[int, int]:
    data = _load_json_object("G05_RECORD_CAMERA_CROPS")
    crops: dict[int, int] = {}
    for index, value in data.items():
        crop = int(value)
        if crop < 0:
            raise RuntimeError(f"camera crop for {index!r} must be non-negative")
        crops[int(index)] = crop
    return crops


def _camera_index(camera: Any) -> int | None:
    try:
        return int(camera.index_or_path)
    except (TypeError, ValueError):
        return None


def patch_lerobot_opencv(controls: dict[int, dict[str, float]], crops: dict[int, int]) -> None:
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
    from lerobot.robots.so_follower.so_follower import SOFollower

    original_configure = OpenCVCamera._configure_capture_settings
    original_postprocess = OpenCVCamera._postprocess_image
    original_camera_features = SOFollower._cameras_ft.fget
    if original_camera_features is None:
        raise RuntimeError("could not access SOFollower camera feature property")
    announced_crops: set[int] = set()

    def configure_with_controls(self: Any) -> None:
        original_configure(self)
        index = _camera_index(self)
        if index is None:
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

    def postprocess_with_crop(self: Any, image: np.ndarray) -> np.ndarray:
        processed = original_postprocess(self, image)
        index = _camera_index(self)
        crop_right = 0 if index is None else crops.get(index, 0)
        if not crop_right:
            return processed
        height, width, channels = processed.shape
        if not 0 < crop_right < width:
            raise RuntimeError(
                f"camera {index} crop-right={crop_right} is invalid for processed frame "
                f"{width}x{height}x{channels}"
            )
        if index not in announced_crops:
            LOGGER.info(
                "camera=%s recording crop: right=%s px; stored frame=%sx%s",
                index,
                crop_right,
                width - crop_right,
                height,
            )
            announced_crops.add(index)
        return np.ascontiguousarray(processed[:, : width - crop_right, :])

    def cropped_camera_features(robot: Any) -> dict[str, tuple]:
        features = dict(original_camera_features(robot))
        for camera_name, camera in robot.cameras.items():
            index = _camera_index(camera)
            crop_right = 0 if index is None else crops.get(index, 0)
            if not crop_right:
                continue
            height, width, channels = features[camera_name]
            if not 0 < crop_right < width:
                raise RuntimeError(
                    f"camera {index} crop-right={crop_right} is invalid for configured frame {width}x{height}"
                )
            features[camera_name] = (height, width - crop_right, channels)
        return features

    OpenCVCamera._configure_capture_settings = configure_with_controls
    OpenCVCamera._postprocess_image = postprocess_with_crop
    SOFollower._cameras_ft = property(cropped_camera_features)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    controls = load_controls()
    crops = load_crops()
    LOGGER.info("camera controls requested for indexes: %s", sorted(controls))
    LOGGER.info("camera crops requested for indexes: %s", crops)
    patch_lerobot_opencv(controls, crops)
    from lerobot.scripts.lerobot_record import main as lerobot_record_main

    lerobot_record_main()


if __name__ == "__main__":
    main()
