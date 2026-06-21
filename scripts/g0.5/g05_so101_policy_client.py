#!/usr/bin/env python
"""Run a remote G0.5 SO-101 policy from the Windows robot laptop.

This is intentionally independent of the GalaxeaVLA Python environment.  It
uses the local LeRobot environment for COM24 and USB cameras, then exchanges
raw observations and actions with ``scripts/serve_policy.py`` on the GPU
server through WebSocket + msgpack.

The server must be started with ``eval_embodiment=so100``.  The name ``so100``
is the upstream G0.5 canonical 6-DoF SO-100/SO-101 embodiment label.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import cv2
import msgpack
import numpy as np


MOTORS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)

# Conversion required by the G0.5 SO-101 checkpoint.  The local LeRobot robot
# uses degrees for the five arm joints and [0, 100] for the gripper.
SIGNS = np.array([1, -1, 1, 1, 1, 1], dtype=np.float32)
OFFSETS = np.array([0, 90, 90, 0, 0, 0], dtype=np.float32)


def _msgpack_default(value: Any) -> Any:
    """Encode NumPy arrays in the exact format used by G0.5's server."""
    if isinstance(value, np.ndarray):
        if value.dtype.kind in ("V", "O", "c"):
            raise ValueError(f"Unsupported ndarray dtype: {value.dtype}")
        return {
            "__ndarray__": True,
            "data": value.tobytes(),
            "dtype": value.dtype.str,
            "shape": value.shape,
        }
    if isinstance(value, np.generic):
        return {"__npgeneric__": True, "data": value.item(), "dtype": value.dtype.str}
    raise TypeError(f"Cannot msgpack encode {type(value).__name__}")


def _decode_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key.decode() if isinstance(key, bytes) else key: _decode_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_decode_keys(item) for item in value]
    return value


def _msgpack_object_hook(value: dict[Any, Any]) -> Any:
    value = _decode_keys(value)
    if value.get("__ndarray__"):
        return np.ndarray(
            buffer=value["data"],
            dtype=np.dtype(value["dtype"]),
            shape=tuple(value["shape"]),
        )
    if value.get("__npgeneric__"):
        return np.dtype(value["dtype"]).type(value["data"])
    return value


def packb(value: Any) -> bytes:
    return msgpack.packb(value, default=_msgpack_default)


def unpackb(value: bytes) -> Any:
    return msgpack.unpackb(value, object_hook=_msgpack_object_hook)


def arm_to_model(state_arm: np.ndarray) -> np.ndarray:
    return SIGNS * state_arm + OFFSETS


def model_to_arm(action_model: np.ndarray) -> np.ndarray:
    return (action_model - OFFSETS) * SIGNS


def clip_target(target: np.ndarray, current: np.ndarray, max_step_deg: float) -> np.ndarray:
    """Limit the largest joint delta in a single action command."""
    delta = target - current
    largest = float(np.max(np.abs(delta)))
    if largest <= max_step_deg or largest == 0:
        return target
    return current + delta * (max_step_deg / largest)


def build_robot(args: argparse.Namespace):
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig
    from lerobot.robots.so101_follower.so101_follower import SO101Follower

    cameras = {
        "exterior": OpenCVCameraConfig(
            index_or_path=args.fixed_camera,
            width=args.width,
            height=args.height,
            fps=args.camera_fps,
            exposure=args.fixed_exposure,
        ),
        "wrist_right": OpenCVCameraConfig(
            index_or_path=args.wrist_camera,
            width=args.width,
            height=args.height,
            fps=args.camera_fps,
            exposure=args.wrist_exposure,
        ),
    }
    config = SO101FollowerConfig(
        port=args.robot_port,
        id=args.robot_id,
        cameras=cameras,
        use_degrees=True,
        # A second independent hardware-level bound, in addition to clip_target.
        max_relative_target=args.max_step_deg,
    )
    return SO101Follower(config)


def get_state(observation: dict[str, Any]) -> np.ndarray:
    return np.asarray([observation[f"{motor}.pos"] for motor in MOTORS], dtype=np.float32)


def image_to_chw(
    image: Any,
    name: str,
    height: int,
    width: int,
    crop_right_px: int,
) -> np.ndarray:
    """Validate an RGB camera frame and optionally remove its right edge.

    Cameras still capture their native 640x480 image.  Cropping happens before
    serialization, so the policy server receives the cropped image and then
    applies its normal Resize([256, 256]) transform.
    """
    image = np.asarray(image)
    expected = (height, width, 3)
    if image.shape != expected:
        raise ValueError(
            f"{name} camera returned {image.shape}; G0.5 requires RGB HWC {expected}. "
            "Check camera index and 640x480 camera mode."
        )
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    if not 0 <= crop_right_px < width:
        raise ValueError(f"crop_right_px must be in [0, {width - 1}], got {crop_right_px}")
    if crop_right_px:
        image = image[:, : width - crop_right_px, :]
    return np.ascontiguousarray(image.transpose(2, 0, 1))


def build_observation(observation: dict[str, Any], task: str, args: argparse.Namespace) -> tuple[dict[str, Any], np.ndarray]:
    state_arm = get_state(observation)
    wrist_outbound_width = args.width - args.wrist_crop_right_px
    raw_observation = {
        "images": {
            "exterior": image_to_chw(
                observation["exterior"],
                "exterior",
                args.height,
                args.width,
                args.fixed_crop_right_px,
            ),
            # Physical SO-101 has no left wrist camera.  The checkpoint was
            # trained to tolerate this explicitly padded third camera slot. It
            # matches the real wrist image's raw shape before server resizing.
            "wrist_left": np.zeros((3, args.height, wrist_outbound_width), dtype=np.uint8),
            "wrist_right": image_to_chw(
                observation["wrist_right"],
                "wrist_right",
                args.height,
                args.width,
                args.wrist_crop_right_px,
            ),
        },
        "state": {"right_arm": arm_to_model(state_arm)},
        "task": task,
        "embodiment_type": "so100",
        "frequency": float(args.action_fps),
    }
    return raw_observation, state_arm


def dump_observation(raw_observation: dict[str, Any], output_dir: str | Path) -> Path:
    """Save the first actual outbound image payload and its server-resize preview.

    ``sent_*.png`` is exactly the RGB uint8 CHW image serialized by msgpack,
    merely transposed back to HWC to make it viewable.  The 256 px previews
    mirror the server's first transform, ``torchvision.transforms.Resize``.
    They do not include normalization because normalized [-1, 1] tensors aren't
    useful for human visual inspection.
    """
    import torch
    from torchvision.transforms import Resize

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    resize_256 = Resize([256, 256])

    for key, chw in raw_observation["images"].items():
        chw = np.ascontiguousarray(chw)
        rgb = np.transpose(chw, (1, 2, 0))
        height, width = rgb.shape[:2]
        cv2.imwrite(
            str(output_dir / f"sent_{key}_rgb_{width}x{height}.png"),
            cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        )

        # The server creates torch.uint8 [T, C, H, W], then applies the same
        # Resize([256, 256]) before converting to float and normalizing.
        resized_chw = resize_256(torch.from_numpy(chw).unsqueeze(0))[0].numpy()
        resized_rgb = np.transpose(resized_chw, (1, 2, 0))
        cv2.imwrite(
            str(output_dir / f"server_resize_preview_{key}_rgb_256x256.png"),
            cv2.cvtColor(resized_rgb, cv2.COLOR_RGB2BGR),
        )

    metadata = {
        "task": raw_observation["task"],
        "embodiment_type": raw_observation["embodiment_type"],
        "frequency_hz": raw_observation["frequency"],
        "state_right_arm_model_frame": raw_observation["state"]["right_arm"].tolist(),
        "wire_format": "RGB uint8 CHW, sent through msgpack/WebSocket",
        "outbound_image_sizes_wh": {
            key: [int(chw.shape[2]), int(chw.shape[1])]
            for key, chw in raw_observation["images"].items()
        },
        "server_first_image_transform": "torchvision.transforms.Resize([256, 256])",
        "server_following_image_transforms": "uint8 -> float32 / 255, then Normalize(mean=.5, std=.5)",
    }
    (output_dir / "observation_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return output_dir


def show_images(observation: dict[str, Any]) -> bool:
    """Show RGB frames as BGR. Return True when the user presses Escape."""
    for key in ("exterior", "wrist_right"):
        image = np.asarray(observation[key])
        cv2.imshow(f"G0.5 {key}", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    return (cv2.waitKey(1) & 0xFF) == 27


async def websocket_connect(uri: str):
    import websockets

    kwargs = {"max_size": None, "ping_interval": 30, "ping_timeout": 120, "proxy": None}
    try:
        return await websockets.connect(uri, **kwargs)
    except TypeError as exc:
        # Compatibility with older websockets releases that do not expose
        # the proxy argument.
        if "proxy" not in str(exc):
            raise
        kwargs.pop("proxy")
        return await websockets.connect(uri, **kwargs)


async def run(args: argparse.Namespace) -> None:
    uri = f"ws://{args.host}:{args.port}"
    robot = build_robot(args)
    logger = logging.getLogger("g05-so101")
    period_s = 1.0 / args.action_fps
    observation_dumped = False

    def dump_once(request: dict[str, Any]) -> None:
        nonlocal observation_dumped
        if args.dump_observation_dir and not observation_dumped:
            saved_dir = dump_observation(request, args.dump_observation_dir)
            print(f"Saved actual outbound observation and server resize previews to: {saved_dir}")
            observation_dumped = True

    try:
        robot.connect()
        print(f"Connected to follower at {args.robot_port}; policy endpoint: {uri}")
        print(f"Task: {args.task!r}")
        print("Press Ctrl+C to stop. Press Escape in a camera window to stop when display is enabled.")
        if args.dry_run:
            print("DRY RUN: model targets will be printed but never sent to COM24.")
        elif not args.no_wait:
            input("Workspace clear? Press Enter to start live G0.5 control... ")

        async with await websocket_connect(uri) as websocket:
            handshake = unpackb(await asyncio.wait_for(websocket.recv(), timeout=args.timeout_s))
            print(f"G0.5 server handshake: {handshake}")

            # A warmup performs an end-to-end image/state inference but sends
            # no action. Reset afterwards so its cached action cannot be used.
            for warmup_index in range(args.warmup_infers):
                observation = robot.get_observation()
                request, _ = build_observation(observation, args.task, args)
                dump_once(request)
                await websocket.send(packb(request))
                response = unpackb(await asyncio.wait_for(websocket.recv(), timeout=args.timeout_s))
                if "error" in response:
                    raise RuntimeError(f"Server warmup error: {response['error']}")
                print(f"warmup {warmup_index + 1}/{args.warmup_infers}: received action")

            if args.warmup_infers:
                await websocket.send(packb({"__reset__": True}))
                reset_response = unpackb(await asyncio.wait_for(websocket.recv(), timeout=args.timeout_s))
                if not reset_response.get("__reset__"):
                    raise RuntimeError(f"Unexpected reset response: {reset_response}")

            need_observation = True
            for step in range(args.max_steps):
                step_started = time.monotonic()
                observation: dict[str, Any] | None = None
                state_arm: np.ndarray | None = None

                if need_observation:
                    observation = robot.get_observation()
                    request, state_arm = build_observation(observation, args.task, args)
                    dump_once(request)
                else:
                    request = {}

                await websocket.send(packb(request))
                response = unpackb(await asyncio.wait_for(websocket.recv(), timeout=args.timeout_s))
                if "error" in response:
                    raise RuntimeError(f"Server error: {response['error']}")
                if "action" not in response or "right_arm" not in response["action"]:
                    raise RuntimeError(f"Malformed server response: {response}")

                action_model = np.asarray(response["action"]["right_arm"], dtype=np.float32).reshape(-1)
                if action_model.shape != (len(MOTORS),):
                    raise RuntimeError(f"Expected six G0.5 joint targets, received {action_model.shape}")

                if state_arm is None:
                    # Cached actions still need a current arm state for the
                    # client-side safety clamp.
                    state_arm = get_state(robot.get_observation())
                target_arm = clip_target(model_to_arm(action_model), state_arm, args.max_step_deg)
                need_observation = bool(response.get("need_obs", True))

                if args.dry_run:
                    print(
                        f"step={step:03d} dry-run target={np.round(target_arm, 1).tolist()} "
                        f"need_obs={need_observation}"
                    )
                else:
                    sent = robot.send_action(
                        {f"{motor}.pos": float(target_arm[index]) for index, motor in enumerate(MOTORS)}
                    )
                    if step % args.log_every == 0:
                        print(
                            f"step={step:03d} sent="
                            f"{[round(sent[f'{motor}.pos'], 1) for motor in MOTORS]} need_obs={need_observation}"
                        )

                if args.display and observation is not None and show_images(observation):
                    print("Escape pressed; stopping.")
                    break

                remaining = period_s - (time.monotonic() - step_started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
    finally:
        with contextlib.suppress(Exception):
            robot.disconnect()
        if args.display:
            cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--task", required=True, help="Use a short, concrete English instruction.")
    parser.add_argument("--robot-port", default="COM24")
    parser.add_argument("--robot-id", default="fenghao_so101_follower")
    parser.add_argument("--fixed-camera", type=int, default=2)
    parser.add_argument("--wrist-camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument(
        "--fixed-crop-right-px",
        "--crop-right-px",
        dest="fixed_crop_right_px",
        type=int,
        default=160,
        help=(
            "Pixels to remove from the right of the exterior camera before sending it. "
            "Default 160 converts native 640x480 into 480x480; --crop-right-px remains an alias."
        ),
    )
    parser.add_argument(
        "--wrist-crop-right-px",
        type=int,
        default=0,
        help="Pixels to remove from the right of the wrist camera. Default 0 preserves its full 640x480 view.",
    )
    parser.add_argument("--camera-fps", type=int, default=15)
    parser.add_argument(
        "--fixed-exposure",
        type=float,
        default=-5.0,
        help="OpenCV/DirectShow exposure for the exterior camera. Driver-specific; use the exposure probe first.",
    )
    parser.add_argument(
        "--wrist-exposure",
        type=float,
        default=-5.0,
        help="OpenCV/DirectShow exposure for the wrist camera. Driver-specific; use the exposure probe first.",
    )
    parser.add_argument("--action-fps", type=float, default=15.0)
    parser.add_argument("--max-step-deg", type=float, default=2.0)
    parser.add_argument("--max-steps", type=int, default=120)
    parser.add_argument("--warmup-infers", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument(
        "--dump-observation-dir",
        default=None,
        help="Save the first real outbound payload and 256x256 server-resize previews to this directory.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true", help="Do not request an Enter confirmation before live motion.")
    parser.add_argument("--no-display", dest="display", action="store_false")
    parser.set_defaults(display=True)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    if args.action_fps <= 0 or args.max_step_deg <= 0 or args.max_steps <= 0:
        raise ValueError("action-fps, max-step-deg, and max-steps must all be positive")
    for argument_name, crop_right_px in (
        ("fixed-crop-right-px", args.fixed_crop_right_px),
        ("wrist-crop-right-px", args.wrist_crop_right_px),
    ):
        if not 0 <= crop_right_px < args.width:
            raise ValueError(f"{argument_name} must be in [0, {args.width - 1}]")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped by user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
