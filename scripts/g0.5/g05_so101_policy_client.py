#!/usr/bin/env python
"""Windows SO101 client and live dashboard for the G0.5 WebSocket policy.

The GPU server owns inference and the action-chunk cache.  This process owns
the physical robot and cameras.  A Tk dashboard runs in the main thread while
one worker thread owns every serial/camera/WebSocket operation, so the GUI never
opens a competing camera handle or writes to the robot directly.

Coordinate contract (LeRobot calibrated degree frame -> G0.5 SO100 model frame):
    q_model = [1,-1,1,1,1,1] * q_arm + [0,90,90,0,0,0]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import msgpack
import numpy as np


LOGGER = logging.getLogger("g05-so101")
MOTORS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
JOINT_COUNT = len(MOTORS)
SIGNS = np.asarray([1, -1, 1, 1, 1, 1], dtype=np.float32)
OFFSETS = np.asarray([0, 90, 90, 0, 0, 0], dtype=np.float32)

# dataset_stats.json global mean converted from G0.5 model frame to the local
# LeRobot degree frame.  It is a training-distribution centre, not a hardware
# calibration pose or a mechanical hard limit.
HOME_ARM = np.asarray([3.1, -34.3, 31.5, 55.9, -12.3, 13.4], dtype=np.float32)


def _msgpack_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.dtype.kind in ("V", "O", "c"):
            raise TypeError(f"unsupported ndarray dtype: {value.dtype}")
        return {
            "__ndarray__": True,
            "data": value.tobytes(),
            "dtype": value.dtype.str,
            "shape": value.shape,
        }
    if isinstance(value, np.generic):
        return {"__npgeneric__": True, "data": value.item(), "dtype": value.dtype.str}
    raise TypeError(f"cannot msgpack encode {type(value).__name__}")


def _decode_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key.decode() if isinstance(key, bytes) else key: _decode_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_decode_keys(item) for item in value]
    return value


def _msgpack_hook(value: dict[Any, Any]) -> Any:
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
    return msgpack.unpackb(value, object_hook=_msgpack_hook)


async def websocket_connect(uri: str):
    import websockets

    kwargs = {"max_size": None, "ping_interval": 30, "ping_timeout": 120, "proxy": None}
    try:
        return await websockets.connect(uri, **kwargs)
    except TypeError as exc:
        if "proxy" not in str(exc):
            raise
        kwargs.pop("proxy")
        return await websockets.connect(uri, **kwargs)


def get_state(observation: dict[str, Any]) -> np.ndarray:
    return np.asarray([observation[f"{motor}.pos"] for motor in MOTORS], dtype=np.float32)


def raw_arm_to_model(raw_arm: np.ndarray, args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray]:
    """Apply the temporary dashboard affine correction, then G0.5 conversion."""
    corrected_arm = raw_arm * args.joint_scales + args.joint_offsets
    return SIGNS * corrected_arm + OFFSETS, corrected_arm


def model_to_raw_arm(model_action: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    corrected_arm = (model_action - OFFSETS) * SIGNS
    return (corrected_arm - args.joint_offsets) / args.joint_scales


def clip_target(target: np.ndarray, current: np.ndarray, max_step_deg: float) -> np.ndarray:
    delta = target - current
    largest = float(np.max(np.abs(delta)))
    if largest == 0 or largest <= max_step_deg:
        return target
    return current + delta * (max_step_deg / largest)


def image_to_chw(
    image: Any,
    *,
    name: str,
    height: int,
    width: int,
    crop_right_px: int,
) -> np.ndarray:
    image = np.asarray(image)
    expected = (height, width, 3)
    if image.shape != expected:
        raise ValueError(f"{name} camera produced {image.shape}; expected RGB HWC {expected}")
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    if not 0 <= crop_right_px < width:
        raise ValueError(f"{name} crop-right must be in [0, {width - 1}], got {crop_right_px}")
    if crop_right_px:
        image = image[:, : width - crop_right_px, :]
    return np.ascontiguousarray(image.transpose(2, 0, 1))


def chw_to_rgb(chw: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(chw).transpose(1, 2, 0))


def server_preview(chw: np.ndarray) -> np.ndarray:
    rgb = chw_to_rgb(chw)
    return cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_LINEAR)


def build_model_images(observation: dict[str, Any], args: argparse.Namespace) -> dict[str, np.ndarray]:
    """Return the exact image geometry used by the G0.5 wire protocol.

    The returned images are uint8 RGB CHW.  This helper is used both for a
    real inference request and for the live dashboard preview, so the preview
    cannot accidentally show a different crop from the model input.
    """
    exterior = image_to_chw(
        observation["exterior"],
        name="exterior",
        height=args.height,
        width=args.width,
        crop_right_px=args.fixed_crop_right_px,
    )
    wrist = image_to_chw(
        observation["wrist_right"],
        name="wrist_right",
        height=args.height,
        width=args.width,
        crop_right_px=args.wrist_crop_right_px,
    )
    return {
        "exterior": exterior,
        "wrist_left": np.zeros((3, args.height, wrist.shape[2]), dtype=np.uint8),
        "wrist_right": wrist,
    }


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
            auto_exposure=args.fixed_auto_exposure,
            exposure=args.fixed_exposure,
        ),
        "wrist_right": OpenCVCameraConfig(
            index_or_path=args.wrist_camera,
            width=args.width,
            height=args.height,
            fps=args.camera_fps,
            auto_exposure=args.wrist_auto_exposure,
            exposure=args.wrist_exposure,
        ),
    }
    config = SO101FollowerConfig(
        port=args.robot_port,
        id=args.robot_id,
        cameras=cameras,
        use_degrees=True,
        # The official client does not set LeRobot's max_relative_target.  The
        # explicit client-side --max-step-deg cap below is the active limit.
        max_relative_target=None,
    )
    return SO101Follower(config)


def build_observation(
    observation: dict[str, Any], task: str, args: argparse.Namespace
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    raw_arm = get_state(observation)
    model_state, corrected_arm = raw_arm_to_model(raw_arm, args)
    images = build_model_images(observation, args)
    request = {
        "images": images,
        "state": {"right_arm": model_state},
        "task": task,
        "embodiment_type": "so100",
        "frequency": float(args.action_fps),
    }
    return request, raw_arm, corrected_arm, model_state


def dump_observation(request: dict[str, Any], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for key, chw in request["images"].items():
        rgb = chw_to_rgb(chw)
        h, w = rgb.shape[:2]
        cv2.imwrite(str(output / f"sent_{key}_rgb_{w}x{h}.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        cv2.imwrite(
            str(output / f"server_resize_preview_{key}_rgb_256x256.png"),
            cv2.cvtColor(server_preview(chw), cv2.COLOR_RGB2BGR),
        )
    metadata = {
        "task": request["task"],
        "frequency_hz": request["frequency"],
        "state_right_arm_model_frame": request["state"]["right_arm"].tolist(),
        "wire_format": "RGB uint8 CHW via msgpack/WebSocket",
        "server_image_preprocess": "Resize([256,256]), ToTensor, Normalize(mean=.5,std=.5)",
    }
    (output / "observation_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def format_joint_vector(vector: np.ndarray | None) -> str:
    if vector is None:
        return "waiting"
    return "  ".join(f"{name}={value:6.1f}" for name, value in zip(MOTORS, vector, strict=True))


@dataclass
class RuntimeState:
    args: argparse.Namespace
    command_queue: queue.Queue[tuple[str, Any]] = field(default_factory=queue.Queue)
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    status: str = "Starting local robot worker…"
    detail: str = ""
    connected: bool = False
    active: bool = False
    torque_enabled: bool = True
    task: str = ""
    handshake: dict[str, Any] | None = None
    raw_arm: np.ndarray | None = None
    corrected_arm: np.ndarray | None = None
    model_state: np.ndarray | None = None
    target_raw_arm: np.ndarray | None = None
    action_model: np.ndarray | None = None
    # "outbound" is the image set attached to the most recent actual policy
    # request.  "live_*" is a continuously refreshed camera preview in that
    # same crop/resize geometry; it is never confused with a sent request.
    outbound: dict[str, np.ndarray] = field(default_factory=dict)
    previews: dict[str, np.ndarray] = field(default_factory=dict)
    live_outbound: dict[str, np.ndarray] = field(default_factory=dict)
    live_previews: dict[str, np.ndarray] = field(default_factory=dict)
    live_image_seq: int = 0
    last_observation_sent_at: float | None = None
    last_timing: dict[str, Any] = field(default_factory=dict)
    chunk_step: int = 0
    action_steps: int = 0
    cards: deque[dict[str, Any]] = field(default_factory=deque)
    next_card_id: int = 1

    def update(self, **values: Any) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def append_card(self, card: dict[str, Any]) -> None:
        with self.lock:
            card["id"] = self.next_card_id
            self.next_card_id += 1
            self.cards.append(card)
            limit = int(self.args.dashboard_history)
            if limit > 0:
                while len(self.cards) > limit:
                    self.cards.popleft()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "detail": self.detail,
                "connected": self.connected,
                "active": self.active,
                "torque_enabled": self.torque_enabled,
                "task": self.task,
                "handshake": dict(self.handshake or {}),
                "raw_arm": None if self.raw_arm is None else self.raw_arm.copy(),
                "corrected_arm": None if self.corrected_arm is None else self.corrected_arm.copy(),
                "model_state": None if self.model_state is None else self.model_state.copy(),
                "target_raw_arm": None if self.target_raw_arm is None else self.target_raw_arm.copy(),
                "action_model": None if self.action_model is None else self.action_model.copy(),
                # Workers only replace complete immutable frame arrays; neither
                # the UI nor card renderer mutates them.  Returning references
                # avoids copying several megabytes of camera pixels per refresh.
                "outbound": dict(self.outbound),
                "previews": dict(self.previews),
                "live_outbound": dict(self.live_outbound),
                "live_previews": dict(self.live_previews),
                "live_image_seq": self.live_image_seq,
                "last_observation_sent_at": self.last_observation_sent_at,
                "last_timing": dict(self.last_timing),
                "chunk_step": self.chunk_step,
                "action_steps": self.action_steps,
                "cards": list(self.cards),
            }


class PolicyWorker(threading.Thread):
    """The only thread permitted to touch robot, cameras, and WebSocket."""

    def __init__(self, runtime: RuntimeState):
        super().__init__(daemon=True, name="G05PolicyWorker")
        self.runtime = runtime
        self.args = runtime.args
        self.robot = None
        self.websocket = None
        self.need_observation = True
        self.executed_steps = 0
        self.observation_dumped = False
        self.live_image_seq = 0
        self.last_live_camera_update = 0.0

    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # GUI stays alive and exposes the complete failure.
            LOGGER.exception("policy worker exited")
            self.runtime.update(status=f"Worker error: {type(exc).__name__}", detail=str(exc), connected=False)
        finally:
            if self.robot is not None:
                with contextlib.suppress(Exception):
                    self.robot.disconnect()
            self.runtime.update(connected=False, active=False)

    async def _run(self) -> None:
        uri = f"ws://{self.args.host}:{self.args.port}"
        self.runtime.update(status="Connecting SO101 follower and cameras…")
        self.robot = build_robot(self.args)
        self.robot.connect()
        self.runtime.update(
            connected=True,
            status=f"Connected to follower {self.args.robot_port}; connecting policy…",
            detail=uri,
        )

        if self.args.home_to_training_mean and not self.args.dry_run:
            await self._move_to_home()
            self.runtime.update(status="Home complete. Connecting policy server...", detail=uri)

        async with await websocket_connect(uri) as websocket:
            self.websocket = websocket
            handshake = unpackb(await asyncio.wait_for(websocket.recv(), timeout=self.args.timeout_s))
            if not isinstance(handshake, dict):
                raise RuntimeError(f"invalid G0.5 handshake: {handshake!r}")
            advertised = int(handshake.get("action_steps", 0))
            if self.args.expected_action_steps and advertised != self.args.expected_action_steps:
                raise RuntimeError(
                    f"server action_steps={advertised}, but client requires {self.args.expected_action_steps}. "
                    "Use matching server/client chunk settings."
                )
            self.runtime.update(
                handshake=handshake,
                action_steps=advertised,
                status="Ready — enter a prompt and press Start.",
                detail=f"server chunk={advertised}; control={self.args.action_fps:g} Hz",
            )
            if self.args.print_server_responses:
                print("\n[G0.5 raw server response | handshake]\n", repr(handshake), flush=True)

            if not self.args.dashboard and self.args.task:
                self.runtime.command_queue.put(("start", self.args.task))

            while not self.runtime.stop_event.is_set():
                await self._drain_commands()
                snap = self.runtime.snapshot()
                if not snap["active"]:
                    self._idle_camera_tick()
                    await asyncio.sleep(max(0.0, 1.0 / self.args.action_fps))
                    continue
                started = time.monotonic()
                await self._policy_tick()
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0, 1.0 / self.args.action_fps - elapsed))

    async def _drain_commands(self) -> None:
        while True:
            try:
                command, value = self.runtime.command_queue.get_nowait()
            except queue.Empty:
                return

            if command == "close":
                self.runtime.stop_event.set()
                return
            if command == "start":
                task = str(value).strip()
                if not task:
                    self.runtime.update(status="Start ignored: prompt is empty.")
                    continue
                if not self.runtime.snapshot()["torque_enabled"] and not self.args.dry_run:
                    self.runtime.update(status="Start blocked: torque is off. Press Torque On first.")
                    continue
                await self._reset_server_cache()
                self.need_observation = True
                self.executed_steps = 0
                self.runtime.update(chunk_step=0)
                await self._warmup(task)
                self.runtime.update(active=True, task=task, status=f"Running task: {task!r}", detail="requesting a new observation")
            elif command == "stop":
                self.runtime.update(active=False, status="Stopped by operator.", detail="server cache reset")
                await self._reset_server_cache()
                self.need_observation = True
                self.runtime.update(chunk_step=0)
            elif command == "reset":
                await self._reset_server_cache()
                self.need_observation = True
                self.runtime.update(chunk_step=0)
                self.runtime.update(status="Server action cache reset.", detail="next tick sends a new observation")
            elif command == "home":
                if self.args.dry_run:
                    self.runtime.update(status="Home blocked in dry-run. Restart with -EnableMotion to move the arm.")
                elif not self.runtime.snapshot()["torque_enabled"]:
                    self.runtime.update(status="Home blocked: torque is off.")
                else:
                    self.runtime.update(active=False)
                    await self._move_to_home()
                    await self._reset_server_cache()
                    self.need_observation = True
                    self.runtime.update(
                        chunk_step=0,
                        status="Home complete. Policy cache reset.",
                        detail="Press Start when ready.",
                    )
            elif command == "torque_off":
                self.runtime.update(active=False, status="Disabling motor torque…")
                await self._reset_server_cache()
                self.robot.bus.disable_torque()
                self.runtime.update(torque_enabled=False, status="Torque OFF — arm may now be moved by hand.")
            elif command == "torque_on":
                self.runtime.update(status="Enabling motor torque…")
                self.robot.bus.enable_torque()
                self.need_observation = True
                await self._reset_server_cache()
                self.runtime.update(torque_enabled=True, status="Torque ON — press Start or Home.")

    async def _reset_server_cache(self) -> None:
        if self.websocket is None:
            return
        await self.websocket.send(packb({"__reset__": True}))
        response = unpackb(await asyncio.wait_for(self.websocket.recv(), timeout=self.args.timeout_s))
        if not isinstance(response, dict) or not response.get("__reset__"):
            raise RuntimeError(f"unexpected reset-cache response: {response!r}")

    async def _warmup(self, task: str) -> None:
        """Warm CUDA/WebSocket without commanding the physical arm.

        It is intentionally opt-in. After the warm-up response the server
        cache is reset, so the first real policy tick uses a fresh observation.
        """
        for index in range(self.args.warmup_infers):
            observation = self.robot.get_observation()
            request, raw_arm, corrected_arm, model_state = build_observation(observation, task, self.args)
            self._publish_live_camera(observation)
            self._update_sent_images(request)
            self.runtime.update(raw_arm=raw_arm, corrected_arm=corrected_arm, model_state=model_state)
            self.runtime.update(status=f"Warmup inference {index + 1}/{self.args.warmup_infers} (no motion).")
            t0 = time.monotonic()
            await self.websocket.send(packb(request))
            response = await self._receive_response_with_live_preview()
            if not isinstance(response, dict) or "error" in response:
                raise RuntimeError(f"warmup response failed: {response!r}")
            self.runtime.update(
                detail=f"warmup round trip {(time.monotonic() - t0) * 1000.0:.0f} ms; resetting server cache",
            )
        if self.args.warmup_infers:
            await self._reset_server_cache()
            self.need_observation = True

    async def _move_to_home(self) -> None:
        self.runtime.update(status="Homing to official G0.5 training-mean pose…", detail=np.round(HOME_ARM, 1).tolist())
        deadline = time.monotonic() + self.args.home_timeout_s
        while time.monotonic() < deadline and not self.runtime.stop_event.is_set():
            observation = self.robot.get_observation()
            self._publish_live_camera(observation)
            current = get_state(observation)
            error = float(np.max(np.abs(HOME_ARM - current)))
            self.runtime.update(raw_arm=current, target_raw_arm=HOME_ARM.copy(), detail=f"home max joint error={error:.1f}°")
            if error <= self.args.home_tolerance_deg:
                self.runtime.update(status="Official G0.5 home reached.", detail=f"max joint error={error:.1f} deg")
                return
            target = current + np.clip(HOME_ARM - current, -self.args.home_step_deg, self.args.home_step_deg)
            self.robot.send_action({f"{motor}.pos": float(target[index]) for index, motor in enumerate(MOTORS)})
            await asyncio.sleep(self.args.home_step_interval_s)
        current = get_state(self.robot.get_observation())
        error = float(np.max(np.abs(HOME_ARM - current)))
        self.runtime.update(status="Official G0.5 home timed out.", detail=f"max joint error={error:.1f}° after {self.args.home_timeout_s:.0f}s")

    def _update_sent_images(self, request: dict[str, Any]) -> None:
        outbound = {key: chw_to_rgb(value) for key, value in request["images"].items() if key != "wrist_left"}
        previews = {key: server_preview(value) for key, value in request["images"].items() if key != "wrist_left"}
        self.runtime.update(outbound=outbound, previews=previews, last_observation_sent_at=time.monotonic())

    def _publish_live_camera(self, observation: dict[str, Any]) -> None:
        """Publish a low-rate live camera board without sending a policy request."""
        now = time.monotonic()
        interval = 1.0 / self.args.dashboard_camera_fps
        if now - self.last_live_camera_update < interval:
            return
        images = build_model_images(observation, self.args)
        outbound = {key: chw_to_rgb(value) for key, value in images.items() if key != "wrist_left"}
        previews = {key: server_preview(value) for key, value in images.items() if key != "wrist_left"}
        self.live_image_seq += 1
        self.last_live_camera_update = now
        self.runtime.update(
            live_outbound=outbound,
            live_previews=previews,
            live_image_seq=self.live_image_seq,
        )

    def _idle_camera_tick(self) -> None:
        """Keep the fixed dashboard camera board live before Start is pressed."""
        observation = self.robot.get_observation()
        raw_arm = get_state(observation)
        model_state, corrected_arm = raw_arm_to_model(raw_arm, self.args)
        self._publish_live_camera(observation)
        self.runtime.update(raw_arm=raw_arm, corrected_arm=corrected_arm, model_state=model_state)

    async def _receive_response_with_live_preview(self) -> Any:
        """Wait for a policy response while refreshing camera/UI state in one worker.

        There is still only one owner of the cameras, serial bus, and socket.
        Unlike a blocking ``await websocket.recv()``, this yields fresh camera
        frames during a slow first CUDA inference without opening a second
        camera handle or executing an extra policy request.
        """
        receive = asyncio.create_task(self.websocket.recv())
        deadline = time.monotonic() + self.args.timeout_s
        while not receive.done():
            if time.monotonic() >= deadline:
                receive.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receive
                raise TimeoutError(f"policy response exceeded {self.args.timeout_s:g} seconds")
            now = time.monotonic()
            if now - self.last_live_camera_update >= 1.0 / self.args.dashboard_camera_fps:
                observation = self.robot.get_observation()
                raw_arm = get_state(observation)
                model_state, corrected_arm = raw_arm_to_model(raw_arm, self.args)
                self._publish_live_camera(observation)
                self.runtime.update(raw_arm=raw_arm, corrected_arm=corrected_arm, model_state=model_state)
            await asyncio.sleep(0.01)
        return unpackb(await receive)

    async def _policy_tick(self) -> None:
        # Read once per control tick.  This keeps dashboard joint state live even
        # while the server is draining its 32-step action cache.
        tick_started = time.monotonic()
        observation = self.robot.get_observation()
        self._publish_live_camera(observation)
        raw_arm = get_state(observation)
        request: dict[str, Any]
        recompute = self.need_observation
        if recompute:
            task = self.runtime.snapshot()["task"]
            request, raw_arm, corrected_arm, model_state = build_observation(observation, task, self.args)
            self._update_sent_images(request)
            self.runtime.update(raw_arm=raw_arm, corrected_arm=corrected_arm, model_state=model_state)
            if self.args.dump_observation_dir and not self.observation_dumped:
                dump_observation(request, self.args.dump_observation_dir)
                self.observation_dumped = True
                LOGGER.info("Saved exact outbound observation to %s", self.args.dump_observation_dir)
        else:
            request = {}
            model_state, corrected_arm = raw_arm_to_model(raw_arm, self.args)
            self.runtime.update(raw_arm=raw_arm, corrected_arm=corrected_arm, model_state=model_state)

        request_ready = time.monotonic()
        t0 = request_ready
        await self.websocket.send(packb(request))
        response = await self._receive_response_with_live_preview()
        round_trip_ms = (time.monotonic() - t0) * 1000.0
        if not isinstance(response, dict):
            raise RuntimeError(f"invalid policy response: {response!r}")
        if self.args.print_server_responses:
            label = "recompute" if recompute else "cache"
            print(f"\n[G0.5 raw server response | {label}]\n{response!r}\ncot_text repr: {response.get('cot_text', '<field absent>')!r}", flush=True)
        if "error" in response:
            raise RuntimeError(f"server error: {response['error']}")
        action = response.get("action")
        if not isinstance(action, dict) or "right_arm" not in action:
            raise RuntimeError(f"server did not return right_arm action: {response!r}")
        action_model = np.asarray(action["right_arm"], dtype=np.float32).reshape(-1)
        if action_model.shape != (JOINT_COUNT,):
            raise RuntimeError(f"expected six action values, received {action_model.shape}")

        target_raw = clip_target(model_to_raw_arm(action_model, self.args), raw_arm, self.args.max_step_deg)
        self.need_observation = bool(response.get("need_obs", True))
        timing = dict(response.get("timing") or {})
        timing["client_prepare_ms"] = (request_ready - tick_started) * 1000.0
        timing["client_round_trip_ms"] = round_trip_ms
        timing["client_total_tick_ms"] = (time.monotonic() - tick_started) * 1000.0
        timing["mode"] = timing.get("mode", "recompute" if recompute else "cache")
        if recompute:
            self.chunk_step = 1
        else:
            self.chunk_step += 1
        timing["chunk_step"] = int(timing.get("chunk_step", self.chunk_step))
        timing["action_steps"] = int(timing.get("action_steps", self.runtime.snapshot()["action_steps"] or 0))
        self.runtime.update(
            action_model=action_model,
            target_raw_arm=target_raw,
            last_timing=timing,
            chunk_step=timing["chunk_step"],
            action_steps=timing["action_steps"],
        )

        if recompute:
            exterior = self.runtime.snapshot()["outbound"].get("exterior")
            cot = response.get("cot_text")
            card = {
                "task": self.runtime.snapshot()["task"],
                "image_rgb": None if exterior is None else exterior.copy(),
                "raw_arm": raw_arm.copy(),
                "model_state": self.runtime.snapshot()["model_state"],
                "action_model": action_model.copy(),
                "target_raw": target_raw.copy(),
                "cot": cot,
                "timing": timing,
                "action_steps": timing["action_steps"],
            }
            self.runtime.append_card(card)

        write_timing_log(
            self.args.timing_log,
            {
                "timestamp_unix_s": time.time(),
                "task": self.runtime.snapshot()["task"],
                "recompute": recompute,
                "need_observation_next": self.need_observation,
                "timing_ms": timing,
                "raw_arm_deg": raw_arm,
                "model_state": model_state,
                "action_model": action_model,
                "target_raw_deg": target_raw,
            },
        )

        if self.args.dry_run:
            if recompute or self.executed_steps % self.args.log_every == 0:
                LOGGER.info("dry-run target=%s need_obs=%s", np.round(target_raw, 1).tolist(), self.need_observation)
        else:
            self.robot.send_action({f"{motor}.pos": float(target_raw[index]) for index, motor in enumerate(MOTORS)})
            if recompute or self.executed_steps % self.args.log_every == 0:
                LOGGER.info("sent=%s need_obs=%s", np.round(target_raw, 1).tolist(), self.need_observation)

        self.executed_steps += 1
        if self.args.max_steps > 0 and self.executed_steps >= self.args.max_steps:
            self.runtime.update(active=False, status=f"Stopped at configured max steps ({self.args.max_steps}).")
            await self._reset_server_cache()
            self.need_observation = True


class UnifiedPolicyDashboard:
    """Persistent Tk dashboard; images update in place and cards scroll."""

    def __init__(self, runtime: RuntimeState, worker: PolicyWorker):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.runtime = runtime
        self.worker = worker
        self.root = tk.Tk()
        self.root.title("G0.5 | unified action stream")
        self.root.geometry("1440x980")
        self.root.minsize(1100, 760)
        self.photos: dict[str, Any] = {}
        self.card_widgets: dict[int, Any] = {}
        self.last_live_image_seq = -1
        self.last_camera_paint_at = 0.0
        self.task_var = tk.StringVar(value=runtime.args.task or "pick up the white block")
        self.status_var = tk.StringVar(value="Starting…")
        self.detail_var = tk.StringVar(value="")
        self.joint_vars = {key: tk.StringVar(value="waiting") for key in ("raw", "model", "target", "action")}
        self.input_labels: dict[str, Any] = {}
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        style = ttk.Style(self.root)
        with contextlib.suppress(Exception):
            style.theme_use("clam")
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="G0.5 • unified action stream", font=("Consolas", 17, "bold")).pack(anchor="w")
        ttk.Label(
            top,
            text=(
                "Embodiment: SO101 (right_arm slot) | "
                f"Control: {self.runtime.args.action_fps:g} Hz | "
                "Action: 6-D joint angle | "
                f"Server chunk: {self.runtime.args.expected_action_steps} ticks"
            ),
            font=("Consolas", 10),
        ).pack(anchor="w", pady=(3, 8))

        row = ttk.Frame(top)
        row.pack(fill="x")
        ttk.Label(row, text="USER · English task prompt", font=("Consolas", 10, "bold")).pack(anchor="w")
        entry_row = ttk.Frame(top)
        entry_row.pack(fill="x", pady=(2, 8))
        self.entry = ttk.Entry(entry_row, textvariable=self.task_var, font=("Segoe UI", 13))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _event: self._start())
        for text, command in (
            ("Start", self._start),
            ("Stop", lambda: self._command("stop")),
            ("Reset cache", lambda: self._command("reset")),
            ("Home", lambda: self._command("home")),
            ("Torque off", lambda: self._command("torque_off")),
            ("Torque on", lambda: self._command("torque_on")),
            ("Close", self._close),
        ):
            ttk.Button(entry_row, text=text, command=command).pack(side="left", padx=(7, 0))

        ttk.Label(top, textvariable=self.status_var, foreground="#b26500", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(top, textvariable=self.detail_var, foreground="#59636e", font=("Consolas", 9)).pack(anchor="w")

        joint_box = ttk.LabelFrame(top, text="JOINT OBSERVATION / ACTION", padding=6)
        joint_box.pack(fill="x", pady=(8, 0))
        for label, key in (
            ("LeRobot raw arm", "raw"),
            ("Corrected + sent model state", "model"),
            ("Decoded G0.5 model action", "action"),
            ("Actual local target after inverse + safety cap", "target"),
        ):
            line = ttk.Frame(joint_box)
            line.pack(fill="x")
            ttk.Label(line, text=f"{label:<48}", font=("Consolas", 9)).pack(side="left")
            ttk.Label(line, textvariable=self.joint_vars[key], font=("Consolas", 9)).pack(side="left", padx=8)

        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, padding=(10, 4, 10, 16))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._resize_scrollregion)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width))
        self.root.bind_all("<MouseWheel>", self._mousewheel, add="+")

        # This camera board is intentionally outside the Canvas below: wheel
        # scrolling cards must never move or hide the live camera view.
        camera_board = ttk.LabelFrame(
            top,
            text="LIVE MODEL CAMERA BOARD | live crop and server 256x256 resize",
            padding=6,
        )
        camera_board.pack(fill="x", pady=(8, 0))
        image_row = ttk.Frame(camera_board)
        image_row.pack(fill="x")
        for key, title in (
            (
                "exterior_out",
                "exterior | live right crop "
                f"({self.runtime.args.width - self.runtime.args.fixed_crop_right_px}x{self.runtime.args.height})",
            ),
            ("exterior_preview", "exterior | live server 256x256"),
            ("wrist_right_out", "wrist_right | live full frame"),
            ("wrist_right_preview", "wrist_right | live server 256x256"),
        ):
            box = ttk.LabelFrame(image_row, text=title, padding=5)
            box.pack(side="left", padx=(0, 8), pady=(0, 0), fill="both", expand=True)
            label = ttk.Label(box, text="Waiting for live camera...", anchor="center")
            label.pack(fill="both", expand=True)
            self.input_labels[key] = label

        ttk.Label(self.content, text="POLICY ACTION STREAM | retained recompute cards", font=("Consolas", 11, "bold")).pack(anchor="w", pady=(4, 0))
        self.cards_frame = ttk.Frame(self.content)
        self.cards_frame.pack(fill="both", expand=True, pady=(6, 0))

    def _resize_scrollregion(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _command(self, command: str) -> None:
        self.runtime.command_queue.put((command, None))

    def _start(self) -> None:
        task = self.task_var.get().strip()
        self.runtime.command_queue.put(("start", task))

    def _close(self) -> None:
        self.runtime.command_queue.put(("close", None))
        self.runtime.stop_event.set()
        self.root.after(40, self.root.destroy)

    def _to_photo(self, rgb: np.ndarray, *, width: int, height: int):
        # ImageTk avoids PNG encode + base64 decode on every frame.  That was
        # the main source of dashboard stutter in the previous implementation.
        from PIL import Image, ImageTk

        if rgb.shape[1] != width or rgb.shape[0] != height:
            rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
        return ImageTk.PhotoImage(Image.fromarray(rgb, mode="RGB"))

    def _set_image(self, key: str, image: np.ndarray | None, *, width: int, height: int) -> None:
        label = self.input_labels[key]
        if image is None:
            return
        photo = self._to_photo(image, width=width, height=height)
        label.configure(image=photo, text="")
        self.photos[key] = photo

    def _add_card(self, card: dict[str, Any]) -> None:
        ttk = self.ttk
        card_id = int(card["id"])
        frame = ttk.LabelFrame(self.cards_frame, text=f"RECOMPUTE #{card_id} · task: {card['task']}", padding=8)
        frame.pack(fill="x", pady=(0, 9))
        left = ttk.Frame(frame)
        left.pack(side="left", fill="y", padx=(0, 12))
        sensor = ttk.Label(left, text="No exterior frame")
        sensor.pack()
        if card.get("image_rgb") is not None:
            photo = self._to_photo(card["image_rgb"], width=280, height=280)
            sensor.configure(image=photo, text="")
            self.photos[f"card-{card_id}"] = photo
        ttk.Label(left, text="exterior · exact outbound crop", font=("Consolas", 8)).pack()

        right = ttk.Frame(frame)
        right.pack(side="left", fill="both", expand=True)
        timing = card.get("timing", {})
        server_ms = timing.get("server_recompute_total_ms") or timing.get("model_total_ms")
        timing_text = f"Round trip: {timing.get('client_round_trip_ms', float('nan')):.0f} ms"
        if server_ms is not None:
            timing_text += f" · server recompute: {float(server_ms):.0f} ms"
        ttk.Label(right, text=timing_text, font=("Consolas", 10, "bold")).pack(anchor="w")
        cot = card.get("cot")
        if cot:
            cot_text = str(cot)
        else:
            cot_text = "No cot_text field was returned by this checkpoint."
        ttk.Label(right, text=f"CoT/raw server text: {cot_text}", justify="left", wraplength=850).pack(anchor="w", pady=(6, 6))
        lines = [
            f"LeRobot raw state:  {np.round(card['raw_arm'], 1).tolist()}",
            f"Model state sent:   {np.round(card['model_state'], 1).tolist()}",
            f"Model action:       {np.round(card['action_model'], 1).tolist()}",
            f"Local target:       {np.round(card['target_raw'], 1).tolist()}",
            f"Server chunk: {card.get('action_steps', 0)} ticks · card appears once per full observation/recompute",
        ]
        ttk.Label(right, text="\n".join(lines), justify="left", font=("Consolas", 9)).pack(anchor="w")
        self.card_widgets[card_id] = frame

    def _refresh(self) -> None:
        snap = self.runtime.snapshot()
        state = "LIVE" if snap["active"] else "IDLE"
        torque = "TORQUE ON" if snap["torque_enabled"] else "TORQUE OFF"
        self.status_var.set(f"{state} · {torque} · {snap['status']}")
        age = "never"
        if snap["last_observation_sent_at"] is not None:
            age = f"{time.monotonic() - snap['last_observation_sent_at']:.2f}s ago"
        self.detail_var.set(
            f"last real server observation: {age} · chunk {snap['chunk_step']}/{snap['action_steps']} · {snap['detail']}"
        )
        self.joint_vars["raw"].set(format_joint_vector(snap["raw_arm"]))
        self.joint_vars["model"].set(format_joint_vector(snap["model_state"]))
        self.joint_vars["action"].set(format_joint_vector(snap["action_model"]))
        self.joint_vars["target"].set(format_joint_vector(snap["target_raw_arm"]))

        # Paint camera images only when the worker supplied a newer frame and
        # at the explicit camera-board rate.  UI/status refreshes can still run
        # at 15 Hz without redoing four image conversions every time.
        now = time.monotonic()
        camera_interval = 1.0 / self.runtime.args.dashboard_camera_fps
        if (
            snap["live_image_seq"] != self.last_live_image_seq
            and now - self.last_camera_paint_at >= camera_interval
        ):
            live = snap["live_outbound"]
            previews = snap["live_previews"]
            self._set_image("exterior_out", live.get("exterior"), width=260, height=260)
            self._set_image("exterior_preview", previews.get("exterior"), width=260, height=260)
            self._set_image("wrist_right_out", live.get("wrist_right"), width=260, height=195)
            self._set_image("wrist_right_preview", previews.get("wrist_right"), width=260, height=260)
            self.last_live_image_seq = snap["live_image_seq"]
            self.last_camera_paint_at = now
        card_ids = {int(card["id"]) for card in snap["cards"]}
        for card_id in list(self.card_widgets):
            if card_id not in card_ids:
                self.card_widgets.pop(card_id).destroy()
        for card in snap["cards"]:
            if int(card["id"]) not in self.card_widgets:
                self._add_card(card)
        self._resize_scrollregion()
        if self.runtime.stop_event.is_set() and not self.worker.is_alive():
            self.root.after(100, self.root.destroy)
            return
        self.root.after(max(20, int(1000.0 / self.runtime.args.dashboard_fps)), self._refresh)

    def run(self) -> None:
        self.worker.start()
        self.root.after(50, self._refresh)
        self.root.mainloop()
        self.runtime.stop_event.set()
        self.worker.join(timeout=3.0)


def write_timing_log(path: str | None, record: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=lambda value: value.tolist() if isinstance(value, np.ndarray) else str(value)) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--task", default="pick up the white block")
    parser.add_argument("--robot-port", default="COM24")
    parser.add_argument("--robot-id", default="fenghao_so101_follower")
    parser.add_argument("--fixed-camera", type=int, default=2)
    parser.add_argument("--wrist-camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    # 91 is round(640 / 7): retain the left 549 columns of a 640x480 exterior frame.
    parser.add_argument("--fixed-crop-right-px", type=int, default=91)
    parser.add_argument("--wrist-crop-right-px", type=int, default=0)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--fixed-auto-exposure", type=float, default=0.25)
    parser.add_argument("--wrist-auto-exposure", type=float, default=0.25)
    parser.add_argument("--fixed-exposure", type=float, default=-6.0)
    parser.add_argument("--wrist-exposure", type=float, default=-6.0)
    parser.add_argument("--action-fps", type=float, default=15.0)
    parser.add_argument("--max-step-deg", type=float, default=10.0)
    parser.add_argument("--max-steps", type=int, default=0, help="0 means run until operator stops it")
    parser.add_argument("--warmup-infers", type=int, default=0)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--expected-action-steps", type=int, default=32)
    parser.add_argument("--home-to-training-mean", action="store_true")
    parser.add_argument("--home-timeout-s", type=float, default=15.0)
    parser.add_argument("--home-tolerance-deg", type=float, default=2.0)
    parser.add_argument("--home-step-deg", type=float, default=5.0)
    parser.add_argument("--home-step-interval-s", type=float, default=0.02)
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--dashboard-fps", type=float, default=15.0)
    parser.add_argument(
        "--dashboard-camera-fps",
        type=float,
        default=10.0,
        help="live fixed camera-board refresh rate; policy control remains action-fps",
    )
    parser.add_argument("--dashboard-history", type=int, default=100, help="0 keeps all recompute cards")
    parser.add_argument("--display", action="store_true", help="Legacy OpenCV display; dashboard is preferred")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--dump-observation-dir", default=None)
    parser.add_argument("--timing-log", default=None)
    parser.add_argument("--print-server-responses", action="store_true")
    parser.add_argument("--joint-offsets", nargs=6, type=float, default=[0.0] * 6)
    parser.add_argument("--joint-scales", nargs=6, type=float, default=[1.0] * 6)
    parser.add_argument("--log-every", type=int, default=10)
    args = parser.parse_args()
    args.joint_offsets = np.asarray(args.joint_offsets, dtype=np.float32)
    args.joint_scales = np.asarray(args.joint_scales, dtype=np.float32)
    if args.action_fps <= 0 or args.camera_fps <= 0 or args.max_step_deg <= 0:
        parser.error("action-fps, camera-fps, and max-step-deg must be positive")
    if args.max_steps < 0 or args.warmup_infers < 0 or args.dashboard_history < 0:
        parser.error("max-steps, warmup-infers, and dashboard-history cannot be negative")
    if args.dashboard_fps <= 0 or args.dashboard_camera_fps <= 0 or args.timeout_s <= 0:
        parser.error("dashboard-fps, dashboard-camera-fps, and timeout-s must be positive")
    if np.any(args.joint_scales <= 0):
        parser.error("joint-scales must all be strictly positive")
    for name, crop in (("fixed-crop-right-px", args.fixed_crop_right_px), ("wrist-crop-right-px", args.wrist_crop_right_px)):
        if not 0 <= crop < args.width:
            parser.error(f"{name} must be in [0, {args.width - 1}]")
    if args.dashboard and args.display:
        parser.error("use either --dashboard or --display, not both")
    return args


def run_terminal(runtime: RuntimeState, worker: PolicyWorker) -> None:
    worker.start()
    if runtime.args.task:
        runtime.command_queue.put(("start", runtime.args.task))
    print("Terminal mode: Ctrl+C stops the policy. Use --dashboard for prompt/buttons/images.")
    try:
        while worker.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        runtime.command_queue.put(("close", None))
        runtime.stop_event.set()
        worker.join(timeout=3.0)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    runtime = RuntimeState(args=args, task=args.task)
    worker = PolicyWorker(runtime)
    if args.dashboard:
        UnifiedPolicyDashboard(runtime, worker).run()
    else:
        run_terminal(runtime, worker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
