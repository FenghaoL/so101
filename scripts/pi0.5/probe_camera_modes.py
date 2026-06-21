import argparse
import time

import cv2


def parse_mode(text: str) -> tuple[int, int]:
    width, height = text.lower().split("x")
    return int(width), int(height)


def test_mode(index: int, width: int, height: int, requested_fps: int, fourcc: str, seconds: int) -> None:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"camera={index} fourcc={fourcc} request={width}x{height}@{requested_fps} opened=false")
        return

    if fourcc != "DEFAULT":
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    cap.set(cv2.CAP_PROP_FPS, float(requested_fps))

    actual_width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
    actual_height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    actual_fps_prop = cap.get(cv2.CAP_PROP_FPS)
    actual_fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    actual_fourcc = "".join(chr((actual_fourcc_int >> (8 * i)) & 0xFF) for i in range(4))
    actual_fourcc_ascii = actual_fourcc.encode("unicode_escape").decode("ascii")

    warmup_end = time.perf_counter() + 0.5
    while time.perf_counter() < warmup_end:
        cap.read()

    start = time.perf_counter()
    end = start + seconds
    frames = 0
    failures = 0
    while time.perf_counter() < end:
        ok, _ = cap.read()
        if ok:
            frames += 1
        else:
            failures += 1

    elapsed = time.perf_counter() - start
    measured_fps = frames / elapsed if elapsed > 0 else 0.0
    cap.release()

    print(
        f"camera={index} fourcc={fourcc} request={width}x{height}@{requested_fps} "
        f"actual={actual_width}x{actual_height}@prop:{actual_fps_prop:.2f} "
        f"actual_fourcc={actual_fourcc_ascii!r} measured={measured_fps:.2f}fps "
        f"frames={frames} failures={failures}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-index", type=int, required=True)
    parser.add_argument("--modes", nargs="+", required=True)
    parser.add_argument("--requested-fps", nargs="+", type=int, required=True)
    parser.add_argument("--fourcc", nargs="+", required=True)
    parser.add_argument("--measure-seconds", type=int, required=True)
    args = parser.parse_args()

    for mode in args.modes:
        width, height = parse_mode(mode)
        for fourcc in args.fourcc:
            for fps in args.requested_fps:
                test_mode(args.camera_index, width, height, fps, fourcc, args.measure_seconds)


if __name__ == "__main__":
    main()
