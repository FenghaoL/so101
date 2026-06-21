import argparse
import time

import cv2
import numpy as np


def measure(index: int, auto_exposure: float | None, exposure: float | None, seconds: int) -> None:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"camera={index} opened=false")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640.0)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480.0)
    cap.set(cv2.CAP_PROP_FPS, 30.0)

    if auto_exposure is not None:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, float(auto_exposure))
    if exposure is not None:
        cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))

    actual_auto = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    actual_exposure = cap.get(cv2.CAP_PROP_EXPOSURE)
    actual_fps_prop = cap.get(cv2.CAP_PROP_FPS)

    warmup_end = time.perf_counter() + 1.0
    while time.perf_counter() < warmup_end:
        cap.read()

    start = time.perf_counter()
    end = start + seconds
    frames = 0
    failures = 0
    means: list[float] = []
    while time.perf_counter() < end:
        ok, frame = cap.read()
        if ok:
            frames += 1
            if frame is not None:
                means.append(float(np.mean(frame)))
        else:
            failures += 1

    elapsed = time.perf_counter() - start
    measured_fps = frames / elapsed if elapsed > 0 else 0.0
    mean_brightness = sum(means) / len(means) if means else 0.0
    cap.release()

    auto_label = "none" if auto_exposure is None else f"{auto_exposure:g}"
    exposure_label = "none" if exposure is None else f"{exposure:g}"
    print(
        f"camera={index} set_auto={auto_label} set_exposure={exposure_label} "
        f"actual_auto={actual_auto:.3f} actual_exposure={actual_exposure:.3f} "
        f"prop_fps={actual_fps_prop:.2f} measured={measured_fps:.2f}fps "
        f"mean_brightness={mean_brightness:.1f} frames={frames} failures={failures}"
    )


def parse_optional_float(text: str) -> float | None:
    if text.lower() == "none":
        return None
    return float(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-index", type=int, required=True)
    parser.add_argument("--auto-values", nargs="+", default=["none", "0.25", "0.75", "0", "1"])
    parser.add_argument("--exposure-values", nargs="+", default=["none", "-4", "-5", "-6", "-7", "-8"])
    parser.add_argument("--measure-seconds", type=int, default=4)
    args = parser.parse_args()

    for auto_text in args.auto_values:
        for exposure_text in args.exposure_values:
            measure(
                args.camera_index,
                parse_optional_float(auto_text),
                parse_optional_float(exposure_text),
                args.measure_seconds,
            )


if __name__ == "__main__":
    main()
