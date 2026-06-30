#!/usr/bin/env python
"""Interactive SO101 data collector for G0.5 RL/preference data.

This is a local Windows tool.  The GPU server only performs policy inference;
this process owns the SO101 follower, the SO101 leader, both USB cameras, the
LeRobot v3 dataset writer, and the operator dashboard.

The dataset written here stays in the same raw LeRobot calibrated-degree frame
as the earlier G0.5 SFT recordings.  RL/DPO metadata is written as sidecar JSONL
files next to the dataset, rather than mutating LeRobot's parquet schema.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import queue
import shutil
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import msgpack
import numpy as np


LOGGER = logging.getLogger("g05-rl-collector")

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
HOME_ARM = np.asarray([3.1, -34.3, 31.5, 55.9, -12.3, 13.4], dtype=np.float32)

# These are deliberately small pose offsets around the G0.5 SO101 training-mean
# pose.  They label robot start-state buckets; they do not encode object pose.
INIT_BUCKETS: dict[str, list[float]] = {
    "A_mean_home": [0, 0, 0, 0, 0, 0],
    "B_pan_left": [-6, 0, 2, 0, 0, 0],
    "C_pan_right": [6, 0, 2, 0, 0, 0],
    "D_reach_forward": [0, -5, 7, -3, 0, 0],
    "E_reach_back": [0, 5, -5, 3, 0, 0],
    "F_failure_edge": [7, -7, 7, -5, 0, 0],
    "G_low_wrist": [0, -4, 5, -8, 0, 0],
    "H_rotated_wrist": [0, 0, 2, 0, 12, 0],
}


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


def format_full_server_packet(packet: Any) -> str:
    with np.printoptions(threshold=np.inf, linewidth=240):
        return repr(packet)


def print_full_server_packet(label: str, packet: Any) -> None:
    print(f"\n[G0.5 complete decoded server packet | {label}]\n{format_full_server_packet(packet)}", flush=True)


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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def append_jsonl(path: Path | str | None, record: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(jsonable(record), ensure_ascii=False) + "\n")


def get_state(observation: dict[str, Any]) -> np.ndarray:
    return np.asarray([observation[f"{motor}.pos"] for motor in MOTORS], dtype=np.float32)


def raw_arm_to_model(raw_arm: np.ndarray, args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray]:
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


def bucket_pose(bucket: str) -> np.ndarray:
    return HOME_ARM + np.asarray(INIT_BUCKETS.get(bucket, [0, 0, 0, 0, 0, 0]), dtype=np.float32)


def vector_to_action(vector: np.ndarray) -> dict[str, float]:
    return {f"{motor}.pos": float(vector[index]) for index, motor in enumerate(MOTORS)}


def action_dict_to_vector(action: dict[str, Any]) -> np.ndarray:
    return np.asarray([action[f"{motor}.pos"] for motor in MOTORS], dtype=np.float32)


def image_to_chw(image: Any, *, name: str) -> np.ndarray:
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"{name} camera produced {image.shape}; expected RGB HWC")
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(image.transpose(2, 0, 1))


def chw_to_rgb(chw: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(chw).transpose(1, 2, 0))


def server_preview(chw: np.ndarray) -> np.ndarray:
    return cv2.resize(chw_to_rgb(chw), (256, 256), interpolation=cv2.INTER_LINEAR)


def build_model_images(observation: dict[str, Any]) -> dict[str, np.ndarray]:
    # The recording camera patch already crops the fixed camera before LeRobot
    # sees it.  Do not crop again here.
    exterior = image_to_chw(observation["fixed"], name="fixed")
    wrist = image_to_chw(observation["wrist"], name="wrist")
    return {
        "exterior": exterior,
        "wrist_left": np.zeros((3, wrist.shape[1], wrist.shape[2]), dtype=np.uint8),
        "wrist_right": wrist,
    }


def build_policy_request(
    observation: dict[str, Any], task: str, args: argparse.Namespace
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    raw_arm = get_state(observation)
    model_state, corrected_arm = raw_arm_to_model(raw_arm, args)
    request = {
        "images": build_model_images(observation),
        "state": {"right_arm": model_state},
        "task": task,
        "embodiment_type": "so100",
        "frequency": float(args.action_fps),
    }
    return request, raw_arm, corrected_arm, model_state


def format_joint_vector(vector: np.ndarray | None) -> str:
    if vector is None:
        return "waiting"
    return "  ".join(f"{name}={float(value):6.1f}" for name, value in zip(MOTORS, vector, strict=True))


def import_local_camera_patch() -> Any:
    script_dir = Path(__file__).resolve().parents[1]
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from record_g05_with_camera_controls import patch_lerobot_opencv

    return patch_lerobot_opencv


def apply_camera_patch(args: argparse.Namespace) -> None:
    patch_lerobot_opencv = import_local_camera_patch()
    controls = {
        int(args.fixed_camera): {
            "auto_exposure": float(args.fixed_auto_exposure),
            "exposure": float(args.fixed_exposure),
        },
        int(args.wrist_camera): {
            "auto_exposure": float(args.wrist_auto_exposure),
            "exposure": float(args.wrist_exposure),
        },
    }
    crops = {int(args.fixed_camera): int(args.fixed_crop_right_px), int(args.wrist_camera): int(args.wrist_crop_right_px)}
    patch_lerobot_opencv(controls, crops)


def build_follower(args: argparse.Namespace):
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO101Follower

    cameras = {
        "fixed": OpenCVCameraConfig(
            index_or_path=args.fixed_camera,
            width=args.width,
            height=args.height,
            fps=args.camera_fps,
        ),
        "wrist": OpenCVCameraConfig(
            index_or_path=args.wrist_camera,
            width=args.width,
            height=args.height,
            fps=args.camera_fps,
        ),
    }
    config = SO101FollowerConfig(
        port=args.follower_port,
        id=args.follower_id,
        calibration_dir=Path(args.follower_calibration_dir),
        cameras=cameras,
        use_degrees=True,
        max_relative_target=None,
    )
    return SO101Follower(config)


def build_leader(args: argparse.Namespace):
    from lerobot.teleoperators.so_leader.config_so_leader import SO101LeaderConfig
    from lerobot.teleoperators.so_leader.so_leader import SO101Leader

    config = SO101LeaderConfig(
        port=args.leader_port,
        id=args.leader_id,
        calibration_dir=Path(args.leader_calibration_dir),
        use_degrees=True,
    )
    return SO101Leader(config)


def build_dataset(args: argparse.Namespace, robot: Any):
    from lerobot.datasets.feature_utils import combine_feature_dicts
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.datasets.pipeline_features import aggregate_pipeline_dataset_features, create_initial_features
    from lerobot.scripts.lerobot_record import make_default_processors

    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()
    dataset_features = combine_feature_dicts(
        aggregate_pipeline_dataset_features(
            pipeline=teleop_action_processor,
            initial_features=create_initial_features(action=robot.action_features),
            use_videos=True,
        ),
        aggregate_pipeline_dataset_features(
            pipeline=robot_observation_processor,
            initial_features=create_initial_features(observation=robot.observation_features),
            use_videos=True,
        ),
    )
    dataset = LeRobotDataset.create(
        args.dataset_repo_id,
        int(args.dataset_fps),
        root=args.dataset_root,
        robot_type=robot.name,
        features=dataset_features,
        use_videos=True,
        image_writer_processes=0,
        image_writer_threads=int(args.image_writer_threads_per_camera) * len(robot.cameras),
        batch_encoding_size=1,
        vcodec=args.video_codec,
        streaming_encoding=bool(args.streaming_encoding),
        encoder_queue_maxsize=int(args.encoder_queue_maxsize),
        encoder_threads=args.encoder_threads,
    )
    return dataset, teleop_action_processor, robot_action_processor, robot_observation_processor


@dataclass
class EpisodeSession:
    episode_index: int
    uid: str
    task: str
    init_config_id: str
    source: str
    failure_mode: str = ""
    notes: str = ""
    start_time: float = field(default_factory=time.monotonic)
    started_at: str = field(default_factory=now_iso)
    frame_count: int = 0
    control_counts: Counter[str] = field(default_factory=Counter)
    human_interval_start: int | None = None
    human_intervals: list[dict[str, int]] = field(default_factory=list)
    policy_recompute_count: int = 0

    def set_human(self, enabled: bool) -> None:
        if enabled and self.human_interval_start is None:
            self.human_interval_start = self.frame_count
        elif not enabled and self.human_interval_start is not None:
            self.human_intervals.append(
                {"start_frame": self.human_interval_start, "end_frame": self.frame_count}
            )
            self.human_interval_start = None

    def finish_intervals(self) -> None:
        if self.human_interval_start is not None:
            self.human_intervals.append(
                {"start_frame": self.human_interval_start, "end_frame": self.frame_count}
            )
            self.human_interval_start = None


@dataclass
class RuntimeState:
    args: argparse.Namespace
    command_queue: queue.Queue[tuple[str, Any]] = field(default_factory=queue.Queue)
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    status: str = "Starting local robot worker..."
    detail: str = ""
    connected: bool = False
    active: bool = False
    torque_enabled: bool = True
    control_mode: str = "policy"
    task: str = "Pick up the white block."
    init_config_id: str = "A_mean_home"
    source: str = "autonomous"
    episode_index: int | None = None
    episode_uid: str | None = None
    episode_frame_count: int = 0
    raw_arm: np.ndarray | None = None
    model_state: np.ndarray | None = None
    target_raw_arm: np.ndarray | None = None
    action_model: np.ndarray | None = None
    leader_arm: np.ndarray | None = None
    live_outbound: dict[str, np.ndarray] = field(default_factory=dict)
    live_previews: dict[str, np.ndarray] = field(default_factory=dict)
    live_image_seq: int = 0
    last_observation_sent_at: float | None = None
    last_timing: dict[str, Any] = field(default_factory=dict)
    chunk_step: int = 0
    action_steps: int = 0
    cards: deque[dict[str, Any]] = field(default_factory=deque)
    next_card_id: int = 1
    saved_episodes: int = 0
    discarded_episodes: int = 0

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
                "control_mode": self.control_mode,
                "task": self.task,
                "init_config_id": self.init_config_id,
                "source": self.source,
                "episode_index": self.episode_index,
                "episode_uid": self.episode_uid,
                "episode_frame_count": self.episode_frame_count,
                "raw_arm": None if self.raw_arm is None else self.raw_arm.copy(),
                "model_state": None if self.model_state is None else self.model_state.copy(),
                "target_raw_arm": None if self.target_raw_arm is None else self.target_raw_arm.copy(),
                "action_model": None if self.action_model is None else self.action_model.copy(),
                "leader_arm": None if self.leader_arm is None else self.leader_arm.copy(),
                "live_outbound": dict(self.live_outbound),
                "live_previews": dict(self.live_previews),
                "live_image_seq": self.live_image_seq,
                "last_observation_sent_at": self.last_observation_sent_at,
                "last_timing": dict(self.last_timing),
                "chunk_step": self.chunk_step,
                "action_steps": self.action_steps,
                "cards": list(self.cards),
                "saved_episodes": self.saved_episodes,
                "discarded_episodes": self.discarded_episodes,
            }


class RLCollectorWorker(threading.Thread):
    """The only thread allowed to touch robot, leader, cameras, dataset, socket."""

    def __init__(self, runtime: RuntimeState):
        super().__init__(daemon=True, name="G05RLCollectorWorker")
        self.runtime = runtime
        self.args = runtime.args
        self.robot = None
        self.leader = None
        self.dataset = None
        self.video_manager = None
        self.websocket = None
        self.episode: EpisodeSession | None = None
        self.need_observation = True
        self.chunk_step = 0
        self.live_image_seq = 0
        self.last_live_camera_update = 0.0
        self.teleop_leader_anchor: np.ndarray | None = None
        self.teleop_follower_anchor: np.ndarray | None = None
        self.background_policy_recv: asyncio.Task | None = None
        self.last_human_policy_obs_sent_at = 0.0
        self.teleop_action_processor = None
        self.robot_action_processor = None
        self.robot_observation_processor = None
        self._finalized = False

    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            LOGGER.exception("RL collector worker exited")
            self.runtime.update(status=f"Worker error: {type(exc).__name__}", detail=str(exc), connected=False)
        finally:
            self._safe_finalize()
            if self.leader is not None:
                with contextlib.suppress(Exception):
                    self.leader.disconnect()
            if self.robot is not None:
                with contextlib.suppress(Exception):
                    self.robot.disconnect()
            self.runtime.update(connected=False, active=False)

    def _safe_finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self.video_manager is not None:
            with contextlib.suppress(Exception):
                self.video_manager.__exit__(None, None, None)
            self.video_manager = None
        elif self.dataset is not None:
            with contextlib.suppress(Exception):
                self.dataset.finalize()

    async def _run(self) -> None:
        self._prepare_output_tree()
        apply_camera_patch(self.args)

        self.runtime.update(status="Creating SO101 follower, leader, and dataset writer...")
        self.robot = build_follower(self.args)
        self.leader = build_leader(self.args)
        (
            self.dataset,
            self.teleop_action_processor,
            self.robot_action_processor,
            self.robot_observation_processor,
        ) = build_dataset(self.args, self.robot)

        self._write_collection_contract()
        self._snapshot_calibrations()

        from lerobot.datasets.video_utils import VideoEncodingManager

        self.video_manager = VideoEncodingManager(self.dataset)
        self.video_manager.__enter__()

        self.runtime.update(status="Connecting follower, cameras, and leader...")
        self.robot.connect()
        self.leader.connect()
        self.runtime.update(connected=True, status="Hardware connected; connecting policy server...")

        uri = f"ws://{self.args.host}:{self.args.port}"
        async with await websocket_connect(uri) as websocket:
            self.websocket = websocket
            handshake = unpackb(await asyncio.wait_for(websocket.recv(), timeout=self.args.timeout_s))
            if not isinstance(handshake, dict):
                raise RuntimeError(f"invalid G0.5 handshake: {handshake!r}")
            advertised = int(handshake.get("action_steps", 0))
            if self.args.expected_action_steps and advertised != self.args.expected_action_steps:
                raise RuntimeError(
                    f"server action_steps={advertised}, client expected {self.args.expected_action_steps}"
                )
            if self.args.print_server_responses:
                print_full_server_packet("handshake", handshake)
            self.runtime.update(
                action_steps=advertised,
                status="Ready. Choose bucket/source, enter prompt, then Start episode.",
                detail=f"dataset={self.args.dataset_root}; server chunk={advertised}",
            )
            self._event("handshake", packet=handshake)

            while not self.runtime.stop_event.is_set():
                await self._drain_commands()
                snap = self.runtime.snapshot()
                if not snap["active"]:
                    self._idle_tick()
                    await asyncio.sleep(max(0.0, 1.0 / self.args.action_fps))
                    continue
                started = time.monotonic()
                await self._episode_tick()
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0, 1.0 / self.args.action_fps - elapsed))

    def _prepare_output_tree(self) -> None:
        root = Path(self.args.dataset_root)
        if root.exists():
            raise RuntimeError(f"Refusing to overwrite existing dataset root: {root}")
        root.parent.mkdir(parents=True, exist_ok=True)
        self.args.event_log = str(root / "rl_events.jsonl")
        self.args.label_log = str(root / "rl_rollout_labels.jsonl")
        self.args.timing_log = str(root / "rl_timing.jsonl")

    def _write_collection_contract(self) -> None:
        context_dir = Path(self.args.dataset_root) / "recording_context"
        context_dir.mkdir(parents=True, exist_ok=True)
        contract = {
            "format": "g05_so101_rl_collection/v1",
            "created_at": now_iso(),
            "task_default": self.args.task,
            "dataset_root": self.args.dataset_root,
            "dataset_repo_id": self.args.dataset_repo_id,
            "dataset_fps": self.args.dataset_fps,
            "action_fps": self.args.action_fps,
            "server": f"ws://{self.args.host}:{self.args.port}",
            "policy_checkpoint_label": self.args.policy_ckpt_label,
            "camera_contract": {
                "fixed_camera_index": self.args.fixed_camera,
                "wrist_camera_index": self.args.wrist_camera,
                "fixed_crop_right_px": self.args.fixed_crop_right_px,
                "wrist_crop_right_px": self.args.wrist_crop_right_px,
                "stored_fixed_shape": [480, 640 - self.args.fixed_crop_right_px, 3],
                "stored_wrist_shape": [480, 640 - self.args.wrist_crop_right_px, 3],
                "server_slots": {"fixed": "exterior", "wrist": "wrist_right", "wrist_left": "zero_padded"},
            },
            "joint_frame": {
                "raw_dataset": "LeRobot calibrated degrees",
                "model_frame_formula": "q_model = [1,-1,1,1,1,1] * q_raw + [0,90,90,0,0,0]",
                "joint_order": [f"{motor}.pos" for motor in MOTORS],
            },
            "control_modes": {
                "policy": "execute G0.5 right_arm actions",
                "teleop": "relative leader takeover; follower target = follower_anchor + leader_delta",
            },
            "init_buckets": {
                name: {"home_offset_deg": offset, "nominal_pose_deg": bucket_pose(name).tolist()}
                for name, offset in INIT_BUCKETS.items()
            },
        }
        (context_dir / "g05_rl_collection_contract.json").write_text(
            json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def _snapshot_calibrations(self) -> None:
        context_dir = Path(self.args.dataset_root) / "recording_context"
        for source in (
            Path(self.args.follower_calibration_dir) / f"{self.args.follower_id}.json",
            Path(self.args.leader_calibration_dir) / f"{self.args.leader_id}.json",
        ):
            if source.is_file():
                shutil.copy2(source, context_dir / source.name)
            else:
                LOGGER.warning("Calibration file not found for snapshotting: %s", source)

    def _event(self, kind: str, **payload: Any) -> None:
        record = {
            "time": now_iso(),
            "kind": kind,
            "episode_uid": None if self.episode is None else self.episode.uid,
            "episode_index": None if self.episode is None else self.episode.episode_index,
            **payload,
        }
        append_jsonl(self.args.event_log, record)

    async def _drain_commands(self) -> None:
        while True:
            try:
                command, value = self.runtime.command_queue.get_nowait()
            except queue.Empty:
                return
            if command == "close":
                self.runtime.stop_event.set()
                return
            if command == "start_episode":
                await self._start_episode(value)
            elif command == "end_episode":
                await self._end_episode(bool(value.get("success")), value)
            elif command == "discard_episode":
                await self._discard_episode(value)
            elif command == "mode":
                await self._switch_mode(str(value))
            elif command == "reanchor":
                self._anchor_teleop()
            elif command == "reset":
                await self._reset_server_cache()
                self.need_observation = True
                self.runtime.update(chunk_step=0, status="Server cache reset.", detail="next policy tick sends a fresh observation")
            elif command == "home":
                await self._move_to_pose(HOME_ARM, label="home")
            elif command == "bucket_home":
                await self._move_to_pose(bucket_pose(str(value)), label=f"bucket {value}")
            elif command == "torque_off":
                self.runtime.update(active=False, status="Disabling follower torque...")
                await self._reset_server_cache()
                self.robot.bus.disable_torque()
                self.runtime.update(torque_enabled=False, status="Torque OFF - follower can be moved by hand.")
            elif command == "torque_on":
                self.runtime.update(status="Enabling follower torque...")
                self.robot.bus.enable_torque()
                await self._reset_server_cache()
                self.need_observation = True
                self.runtime.update(torque_enabled=True, status="Torque ON.")

    async def _start_episode(self, value: dict[str, Any]) -> None:
        if self.episode is not None:
            self.runtime.update(status="Start ignored: an episode is already active.")
            return
        if not self.runtime.snapshot()["torque_enabled"] and not self.args.dry_run:
            self.runtime.update(status="Start blocked: follower torque is off.")
            return
        task = str(value.get("task") or self.args.task).strip()
        if not task:
            self.runtime.update(status="Start ignored: prompt is empty.")
            return
        source = str(value.get("source") or "autonomous").strip()
        init_config_id = str(value.get("init_config_id") or "A_mean_home").strip()
        initial_mode = str(value.get("control_mode") or ("teleop" if source in {"demo", "recovery"} else "policy"))
        episode_index = int(self.dataset.num_episodes)
        uid = f"{Path(self.args.dataset_root).name}_ep{episode_index:05d}"
        self.episode = EpisodeSession(
            episode_index=episode_index,
            uid=uid,
            task=task,
            init_config_id=init_config_id,
            source=source,
            failure_mode=str(value.get("failure_mode") or ""),
            notes=str(value.get("notes") or ""),
        )
        self.runtime.update(
            active=True,
            task=task,
            init_config_id=init_config_id,
            source=source,
            episode_index=episode_index,
            episode_uid=uid,
            episode_frame_count=0,
            status=f"Recording episode {episode_index} ({source}, {init_config_id})",
            detail="cache reset; first policy action will use a fresh observation",
            chunk_step=0,
            control_mode=initial_mode,
        )
        self.need_observation = True
        self.chunk_step = 0
        if initial_mode == "teleop":
            self._anchor_teleop()
            self.episode.set_human(True)
        await self._reset_server_cache()
        self._event("episode_start", task=task, source=source, init_config_id=init_config_id, mode=initial_mode)

    async def _end_episode(self, success: bool, value: dict[str, Any]) -> None:
        if self.episode is None:
            self.runtime.update(status="End ignored: no active episode.")
            return
        if self.episode.frame_count <= 0:
            self.runtime.update(status="End ignored: active episode has no recorded frames.")
            return
        self.episode.failure_mode = str(value.get("failure_mode") or self.episode.failure_mode or "")
        self.episode.notes = str(value.get("notes") or self.episode.notes or "")
        self.episode.finish_intervals()
        self.runtime.update(active=False, status="Saving episode...", detail="LeRobot is encoding/writing the episode")
        self.dataset.save_episode()
        label = self._episode_label(success=success)
        append_jsonl(self.args.label_log, label)
        self._event("episode_saved", success=success, label=label)
        saved = self.runtime.snapshot()["saved_episodes"] + 1
        self.runtime.update(
            saved_episodes=saved,
            status=f"Saved episode {label['episode_index']} success={success}",
            detail="Use reset/home or start the next bucket.",
            episode_index=None,
            episode_uid=None,
            episode_frame_count=0,
        )
        self.episode = None
        await self._reset_server_cache()
        self.need_observation = True

    async def _discard_episode(self, value: dict[str, Any]) -> None:
        if self.episode is None:
            self.runtime.update(status="Discard ignored: no active episode.")
            return
        uid = self.episode.uid
        frames = self.episode.frame_count
        self.dataset.clear_episode_buffer()
        self._event("episode_discarded", reason=str(value.get("reason") or ""), frames=frames)
        discarded = self.runtime.snapshot()["discarded_episodes"] + 1
        self.runtime.update(
            active=False,
            discarded_episodes=discarded,
            status=f"Discarded episode {uid}",
            detail="buffer cleared; LeRobot dataset was not advanced",
            episode_index=None,
            episode_uid=None,
            episode_frame_count=0,
        )
        self.episode = None
        await self._reset_server_cache()
        self.need_observation = True

    def _episode_label(self, *, success: bool) -> dict[str, Any]:
        assert self.episode is not None
        duration_s = time.monotonic() - self.episode.start_time
        return {
            "format": "g05_so101_rl_episode_label/v1",
            "episode_uid": self.episode.uid,
            "dataset_dir": str(Path(self.args.dataset_root).resolve()),
            "episode_index": self.episode.episode_index,
            "instruction": self.episode.task,
            "init_config_id": self.episode.init_config_id,
            "init_bucket_pose_deg": bucket_pose(self.episode.init_config_id).tolist(),
            "source": self.episode.source,
            "success": bool(success),
            "failure_mode": "" if success else self.episode.failure_mode,
            "notes": self.episode.notes,
            "frame_count": self.episode.frame_count,
            "duration_s": duration_s,
            "started_at": self.episode.started_at,
            "ended_at": now_iso(),
            "policy_ckpt": self.args.policy_ckpt_label,
            "policy_endpoint": f"ws://{self.args.host}:{self.args.port}",
            "human_control_intervals": self.episode.human_intervals,
            "control_source_counts": dict(self.episode.control_counts),
            "policy_recompute_count": self.episode.policy_recompute_count,
            "camera_contract": {
                "fixed_crop_right_px": self.args.fixed_crop_right_px,
                "wrist_crop_right_px": self.args.wrist_crop_right_px,
            },
        }

    async def _switch_mode(self, mode: str) -> None:
        if mode not in {"policy", "teleop"}:
            self.runtime.update(status=f"Unknown control mode: {mode}")
            return
        current = self.runtime.snapshot()["control_mode"]
        if current == mode:
            return
        if mode == "teleop":
            self._anchor_teleop()
            if self.episode is not None:
                self.episode.set_human(True)
            self.runtime.update(control_mode="teleop", status="Human/leader takeover active.")
            self._event("mode_switch", mode="teleop")
        else:
            if self.episode is not None:
                self.episode.set_human(False)
            self.runtime.update(control_mode="policy", status="Switching back to policy; waiting for fresh observation...")
            await self._finish_background_policy_recv()
            await self._reset_server_cache()
            self.need_observation = True
            self.chunk_step = 0
            self.runtime.update(chunk_step=0, detail="cache reset; next policy tick recomputes")
            self._event("mode_switch", mode="policy")

    def _anchor_teleop(self) -> None:
        if self.leader is None or self.robot is None:
            return
        leader_action = self.leader.get_action()
        observation = self.robot.get_observation()
        self.teleop_leader_anchor = action_dict_to_vector(leader_action)
        self.teleop_follower_anchor = get_state(observation)
        self.runtime.update(
            leader_arm=self.teleop_leader_anchor,
            raw_arm=self.teleop_follower_anchor,
            target_raw_arm=self.teleop_follower_anchor,
            status="Teleop anchor set.",
            detail="relative leader deltas now drive follower deltas",
        )
        self._event("teleop_anchor", leader=self.teleop_leader_anchor, follower=self.teleop_follower_anchor)

    async def _reset_server_cache(self) -> None:
        if self.websocket is None:
            return
        await self._finish_background_policy_recv()
        await self.websocket.send(packb({"__reset__": True}))
        response = unpackb(await asyncio.wait_for(self.websocket.recv(), timeout=self.args.timeout_s))
        if self.args.print_server_responses:
            print_full_server_packet("reset-cache", response)
        if not isinstance(response, dict) or not response.get("__reset__"):
            raise RuntimeError(f"unexpected reset-cache response: {response!r}")
        self._event("reset_cache", response=response)

    async def _finish_background_policy_recv(self) -> None:
        task = self.background_policy_recv
        if task is None:
            return
        self.background_policy_recv = None
        if not task.done():
            try:
                response = unpackb(await asyncio.wait_for(task, timeout=self.args.timeout_s))
            except Exception as exc:
                self._event("background_policy_error", error=repr(exc))
                return
        else:
            response = unpackb(task.result())
        self._handle_policy_response(response, recompute=True, execute=False, label="human-background")

    async def _move_to_pose(self, target_pose: np.ndarray, *, label: str) -> None:
        if self.args.dry_run:
            self.runtime.update(status=f"{label} blocked in dry-run.")
            return
        if self.runtime.snapshot()["active"]:
            self.runtime.update(status=f"{label} blocked while recording. End/discard the episode first.")
            return
        if not self.runtime.snapshot()["torque_enabled"]:
            self.runtime.update(status=f"{label} blocked: torque is off.")
            return
        self.runtime.update(status=f"Moving to {label} pose...", detail=np.round(target_pose, 1).tolist())
        deadline = time.monotonic() + self.args.home_timeout_s
        body_indices = list(range(JOINT_COUNT - 1)) if self.args.home_ignore_gripper else list(range(JOINT_COUNT))
        while time.monotonic() < deadline and not self.runtime.stop_event.is_set():
            observation = self.robot.get_observation()
            self._publish_live_camera(observation)
            current = get_state(observation)
            error = float(np.max(np.abs(target_pose[body_indices] - current[body_indices])))
            self.runtime.update(raw_arm=current, target_raw_arm=target_pose.copy(), detail=f"{label} max body error={error:.1f} deg")
            if error <= self.args.home_tolerance_deg:
                self.runtime.update(status=f"{label} pose reached.", detail=f"max body error={error:.1f} deg")
                return
            target = current + np.clip(target_pose - current, -self.args.home_step_deg, self.args.home_step_deg)
            self.robot.send_action(vector_to_action(target))
            await asyncio.sleep(self.args.home_step_interval_s)
        current = get_state(self.robot.get_observation())
        error = float(np.max(np.abs(target_pose[body_indices] - current[body_indices])))
        self.runtime.update(status=f"{label} pose timed out.", detail=f"max body error={error:.1f} deg")

    def _publish_live_camera(self, observation: dict[str, Any]) -> None:
        now = time.monotonic()
        if now - self.last_live_camera_update < 1.0 / self.args.dashboard_camera_fps:
            return
        images = build_model_images(observation)
        outbound = {key: chw_to_rgb(value) for key, value in images.items() if key != "wrist_left"}
        previews = {key: server_preview(value) for key, value in images.items() if key != "wrist_left"}
        self.live_image_seq += 1
        self.last_live_camera_update = now
        self.runtime.update(live_outbound=outbound, live_previews=previews, live_image_seq=self.live_image_seq)

    def _idle_tick(self) -> None:
        observation = self.robot.get_observation()
        raw_arm = get_state(observation)
        model_state, _ = raw_arm_to_model(raw_arm, self.args)
        leader = action_dict_to_vector(self.leader.get_action())
        self._publish_live_camera(observation)
        self.runtime.update(raw_arm=raw_arm, model_state=model_state, leader_arm=leader)

    async def _episode_tick(self) -> None:
        assert self.episode is not None
        tick_started = time.monotonic()
        observation = self.robot.get_observation()
        self._publish_live_camera(observation)
        raw_arm = get_state(observation)
        model_state, _ = raw_arm_to_model(raw_arm, self.args)
        mode = self.runtime.snapshot()["control_mode"]
        action_values: dict[str, float]
        target_raw: np.ndarray
        action_model: np.ndarray | None = None
        control_source = mode

        if mode == "teleop":
            await self._maybe_send_background_human_observation(observation)
            target_raw = self._teleop_target(raw_arm)
            action_values = vector_to_action(target_raw)
        else:
            target_raw, action_model = await self._policy_target(observation, raw_arm)
            action_values = vector_to_action(target_raw)
            control_source = "policy"

        robot_action_to_send = self.robot_action_processor((action_values, observation))
        if self.args.dry_run:
            recorded_action = robot_action_to_send
        else:
            self.robot.send_action(robot_action_to_send)
            recorded_action = robot_action_to_send

        if self.dataset is not None:
            from lerobot.datasets.feature_utils import build_dataset_frame
            from lerobot.utils.constants import ACTION, OBS_STR

            obs_processed = self.robot_observation_processor(observation)
            observation_frame = build_dataset_frame(self.dataset.features, obs_processed, prefix=OBS_STR)
            action_frame = build_dataset_frame(self.dataset.features, recorded_action, prefix=ACTION)
            self.dataset.add_frame({**observation_frame, **action_frame, "task": self.episode.task})

        self.episode.frame_count += 1
        self.episode.control_counts[control_source] += 1
        if control_source == "teleop":
            self.episode.set_human(True)
        elif mode == "policy":
            self.episode.set_human(False)

        timing = {
            "client_total_tick_ms": (time.monotonic() - tick_started) * 1000.0,
            "mode": control_source,
            "chunk_step": self.chunk_step,
            "action_steps": self.runtime.snapshot()["action_steps"],
        }
        self.runtime.update(
            raw_arm=raw_arm,
            model_state=model_state,
            action_model=action_model,
            target_raw_arm=target_raw,
            episode_frame_count=self.episode.frame_count,
            last_timing=timing,
        )
        append_jsonl(
            self.args.timing_log,
            {
                "time": now_iso(),
                "episode_uid": self.episode.uid,
                "episode_index": self.episode.episode_index,
                "frame": self.episode.frame_count - 1,
                "control_source": control_source,
                "raw_arm_deg": raw_arm,
                "model_state": model_state,
                "target_raw_deg": target_raw,
                "action_model": action_model,
                "timing_ms": timing,
            },
        )

    def _teleop_target(self, raw_arm: np.ndarray) -> np.ndarray:
        leader_action = self.leader.get_action()
        leader = action_dict_to_vector(leader_action)
        if self.teleop_leader_anchor is None or self.teleop_follower_anchor is None:
            self.teleop_leader_anchor = leader.copy()
            self.teleop_follower_anchor = raw_arm.copy()
        if self.args.absolute_teleop:
            target = leader
        else:
            target = self.teleop_follower_anchor + (leader - self.teleop_leader_anchor)
        target = clip_target(target, raw_arm, self.args.max_step_deg)
        self.runtime.update(leader_arm=leader, target_raw_arm=target)
        return target

    async def _policy_target(self, observation: dict[str, Any], raw_arm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        request: dict[str, Any]
        recompute = self.need_observation
        if recompute:
            request, raw_arm, _, model_state = build_policy_request(observation, self.episode.task, self.args)
            self._update_sent_images(request)
        else:
            request = {}
            model_state, _ = raw_arm_to_model(raw_arm, self.args)
        request_ready = time.monotonic()
        await self.websocket.send(packb(request))
        response = await self._recv_policy_response_with_live_updates()
        round_trip_ms = (time.monotonic() - request_ready) * 1000.0
        target_raw, action_model, timing = self._handle_policy_response(
            response,
            recompute=recompute,
            execute=True,
            label="recompute" if recompute else "cache",
            round_trip_ms=round_trip_ms,
            raw_arm=raw_arm,
            model_state=model_state,
        )
        self.runtime.update(last_timing=timing)
        return target_raw, action_model

    async def _recv_policy_response_with_live_updates(self) -> Any:
        """Wait for one policy packet without freezing the local camera dashboard."""
        assert self.websocket is not None
        receive_task = asyncio.create_task(self.websocket.recv())
        deadline = time.monotonic() + self.args.timeout_s
        last_probe = 0.0
        probe_interval = 1.0 / max(1.0, float(self.args.dashboard_camera_fps))
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                done, _pending = await asyncio.wait({receive_task}, timeout=min(0.05, remaining))
                if receive_task in done:
                    return unpackb(receive_task.result())

                now = time.monotonic()
                if now - last_probe < probe_interval:
                    continue
                last_probe = now
                with contextlib.suppress(Exception):
                    observation = self.robot.get_observation()
                    self._publish_live_camera(observation)
                    raw_arm = get_state(observation)
                    model_state, _ = raw_arm_to_model(raw_arm, self.args)
                    leader = action_dict_to_vector(self.leader.get_action())
                    self.runtime.update(raw_arm=raw_arm, model_state=model_state, leader_arm=leader)
        except Exception:
            if not receive_task.done():
                receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await receive_task
            raise

    def _handle_policy_response(
        self,
        response: Any,
        *,
        recompute: bool,
        execute: bool,
        label: str,
        round_trip_ms: float | None = None,
        raw_arm: np.ndarray | None = None,
        model_state: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        if self.args.print_server_responses:
            print_full_server_packet(label, response)
        if not isinstance(response, dict):
            raise RuntimeError(f"invalid policy response: {response!r}")
        if "error" in response:
            raise RuntimeError(f"server error: {response['error']}")
        action = response.get("action")
        if not isinstance(action, dict) or "right_arm" not in action:
            raise RuntimeError(f"server did not return right_arm action: {response!r}")
        action_model = np.asarray(action["right_arm"], dtype=np.float32).reshape(-1)
        if action_model.shape != (JOINT_COUNT,):
            raise RuntimeError(f"expected 6-D right_arm action, got {action_model.shape}")
        if raw_arm is None:
            raw_arm = self.runtime.snapshot()["raw_arm"]
        if model_state is None and raw_arm is not None:
            model_state, _ = raw_arm_to_model(raw_arm, self.args)
        target_raw = clip_target(model_to_raw_arm(action_model, self.args), raw_arm, self.args.max_step_deg)
        self.need_observation = bool(response.get("need_obs", True))
        if recompute:
            self.chunk_step = 1
        else:
            self.chunk_step += 1
        timing = dict(response.get("timing") or {})
        if round_trip_ms is not None:
            timing["client_round_trip_ms"] = round_trip_ms
        timing["mode"] = label
        timing["chunk_step"] = int(timing.get("chunk_step", self.chunk_step))
        timing["action_steps"] = int(timing.get("action_steps", self.runtime.snapshot()["action_steps"] or 0))
        self.runtime.update(
            action_model=action_model,
            target_raw_arm=target_raw,
            chunk_step=timing["chunk_step"],
            action_steps=timing["action_steps"],
        )
        if self.episode is not None and recompute:
            self.episode.policy_recompute_count += 1
        if recompute:
            exterior = self.runtime.snapshot()["live_outbound"].get("exterior")
            self.runtime.append_card(
                {
                    "task": None if self.episode is None else self.episode.task,
                    "image_rgb": None if exterior is None else exterior.copy(),
                    "raw_arm": None if raw_arm is None else raw_arm.copy(),
                    "model_state": None if model_state is None else model_state.copy(),
                    "action_model": action_model.copy(),
                    "target_raw": target_raw.copy(),
                    "cot": response.get("cot_text"),
                    "timing": timing,
                    "action_steps": timing["action_steps"],
                    "execute": execute,
                }
            )
        self._event(
            "policy_response",
            label=label,
            execute=execute,
            recompute=recompute,
            need_observation_next=self.need_observation,
            action_model=action_model,
            target_raw=target_raw,
            timing=timing,
        )
        return target_raw, action_model, timing

    def _update_sent_images(self, request: dict[str, Any]) -> None:
        outbound = {key: chw_to_rgb(value) for key, value in request["images"].items() if key != "wrist_left"}
        previews = {key: server_preview(value) for key, value in request["images"].items() if key != "wrist_left"}
        self.live_image_seq += 1
        self.runtime.update(
            live_outbound=outbound,
            live_previews=previews,
            live_image_seq=self.live_image_seq,
            last_observation_sent_at=time.monotonic(),
        )

    async def _maybe_send_background_human_observation(self, observation: dict[str, Any]) -> None:
        if not self.args.human_send_policy_observations:
            return
        if self.background_policy_recv is not None:
            if self.background_policy_recv.done():
                await self._finish_background_policy_recv()
            return
        now = time.monotonic()
        if now - self.last_human_policy_obs_sent_at < self.args.human_policy_observation_interval_s:
            return
        request, _raw, _corrected, _model = build_policy_request(observation, self.episode.task, self.args)
        self._update_sent_images(request)
        await self.websocket.send(packb(request))
        self.background_policy_recv = asyncio.create_task(self.websocket.recv())
        self.last_human_policy_obs_sent_at = now
        self._event("human_background_observation_sent")


class RLCollectorDashboard:
    def __init__(self, runtime: RuntimeState, worker: RLCollectorWorker):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.runtime = runtime
        self.worker = worker
        self.root = tk.Tk()
        self.root.title("G0.5 SO101 RL Collector")
        self.root.geometry("1500x1000")
        self.root.minsize(1160, 780)
        self.photos: dict[str, Any] = {}
        self.card_widgets: dict[int, Any] = {}
        self.last_live_image_seq = -1
        self.last_camera_paint_at = 0.0

        self.task_var = tk.StringVar(value=runtime.args.task)
        self.bucket_var = tk.StringVar(value=runtime.args.init_config_id)
        self.source_var = tk.StringVar(value=runtime.args.source)
        self.mode_var = tk.StringVar(value=runtime.args.start_control_mode)
        self.failure_var = tk.StringVar(value="miss_grasp")
        self.notes_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Starting...")
        self.detail_var = tk.StringVar(value="")
        self.joint_vars = {key: tk.StringVar(value="waiting") for key in ("raw", "model", "target", "action", "leader")}
        self.input_labels: dict[str, Any] = {}
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        style = ttk.Style(self.root)
        with contextlib.suppress(Exception):
            style.theme_use("clam")
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="G0.5 SO101 RL preference collector", font=("Consolas", 17, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                f"Dataset: {self.runtime.args.dataset_root} | "
                f"Control: {self.runtime.args.action_fps:g} Hz | "
                "LeRobot v3 raw degrees + RL sidecar labels"
            ),
            font=("Consolas", 9),
        ).pack(anchor="w", pady=(2, 8))

        prompt_row = ttk.Frame(header)
        prompt_row.pack(fill="x", pady=(0, 6))
        ttk.Label(prompt_row, text="Prompt", width=10).pack(side="left")
        self.entry = ttk.Entry(prompt_row, textvariable=self.task_var, font=("Segoe UI", 12))
        self.entry.pack(side="left", fill="x", expand=True)

        cfg_row = ttk.Frame(header)
        cfg_row.pack(fill="x", pady=(0, 6))
        ttk.Label(cfg_row, text="Bucket").pack(side="left")
        ttk.Combobox(cfg_row, textvariable=self.bucket_var, values=list(INIT_BUCKETS), width=22).pack(side="left", padx=(4, 12))
        ttk.Label(cfg_row, text="Source").pack(side="left")
        ttk.Combobox(
            cfg_row,
            textvariable=self.source_var,
            values=["autonomous", "intervention", "recovery", "demo", "eval"],
            width=16,
        ).pack(side="left", padx=(4, 12))
        ttk.Label(cfg_row, text="Start mode").pack(side="left")
        ttk.Combobox(cfg_row, textvariable=self.mode_var, values=["policy", "teleop"], width=10).pack(side="left", padx=(4, 12))
        ttk.Label(cfg_row, text="Failure").pack(side="left")
        ttk.Combobox(
            cfg_row,
            textvariable=self.failure_var,
            values=["miss_grasp", "bad_approach", "drop_after_grasp", "timeout", "collision_stop", "object_moved", "other", ""],
            width=18,
        ).pack(side="left", padx=(4, 12))
        ttk.Label(cfg_row, text="Notes").pack(side="left")
        ttk.Entry(cfg_row, textvariable=self.notes_var, width=34).pack(side="left", fill="x", expand=True, padx=(4, 0))

        button_row = ttk.Frame(header)
        button_row.pack(fill="x", pady=(0, 8))
        for text, command in (
            ("Start episode", self._start_episode),
            ("End SUCCESS", lambda: self._end_episode(True)),
            ("End FAILURE", lambda: self._end_episode(False)),
            ("Discard", self._discard_episode),
            ("Policy mode", lambda: self._command("mode", "policy")),
            ("Teleop mode", lambda: self._command("mode", "teleop")),
            ("Re-anchor teleop", lambda: self._command("reanchor")),
            ("Reset cache", lambda: self._command("reset")),
            ("Move bucket pose", lambda: self._command("bucket_home", self.bucket_var.get())),
            ("Home", lambda: self._command("home")),
            ("Torque off", lambda: self._command("torque_off")),
            ("Torque on", lambda: self._command("torque_on")),
            ("Close", self._close),
        ):
            ttk.Button(button_row, text=text, command=command).pack(side="left", padx=(0, 4))

        ttk.Label(header, textvariable=self.status_var, font=("Consolas", 10, "bold")).pack(anchor="w")
        ttk.Label(header, textvariable=self.detail_var, font=("Consolas", 9)).pack(anchor="w")

        joint_box = ttk.LabelFrame(header, text="joint state / command", padding=6)
        joint_box.pack(fill="x", pady=(8, 0))
        for name, label in (
            ("raw", "Follower raw"),
            ("leader", "Leader"),
            ("model", "Model state"),
            ("action", "Policy action"),
            ("target", "Executed target"),
        ):
            row = ttk.Frame(joint_box)
            row.pack(fill="x")
            ttk.Label(row, text=label, width=16, font=("Consolas", 9, "bold")).pack(side="left")
            ttk.Label(row, textvariable=self.joint_vars[name], font=("Consolas", 9)).pack(side="left", fill="x", expand=True)

        camera_box = ttk.LabelFrame(shell, text="LIVE MODEL INPUTS - exact recorded crop and server 256x256 resize", padding=8)
        camera_box.pack(fill="x", padx=10, pady=(0, 8))
        image_row = ttk.Frame(camera_box)
        image_row.pack(fill="x")
        for key, title in (
            ("exterior_out", "fixed/exterior | recorded outbound"),
            ("exterior_preview", "fixed/exterior | server 256x256"),
            ("wrist_right_out", "wrist | recorded outbound"),
            ("wrist_right_preview", "wrist | server 256x256"),
        ):
            box = ttk.LabelFrame(image_row, text=title, padding=5)
            box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            label = ttk.Label(box, text="Waiting for live camera...", anchor="center")
            label.pack(fill="both", expand=True)
            self.input_labels[key] = label

        body = ttk.Frame(shell)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._resize_scrollregion)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self._mousewheel)
        ttk.Label(self.content, text="POLICY ACTION STREAM - recompute cards", font=("Consolas", 11, "bold")).pack(anchor="w")
        self.cards_frame = ttk.Frame(self.content)
        self.cards_frame.pack(fill="both", expand=True, pady=(6, 0))

        self.root.bind("<Control-p>", lambda _event: self._command("mode", "policy"))
        self.root.bind("<Control-t>", lambda _event: self._command("mode", "teleop"))
        self.root.bind("<Control-r>", lambda _event: self._command("reset"))

    def _resize_scrollregion(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _command(self, command: str, value: Any = None) -> None:
        self.runtime.command_queue.put((command, value))

    def _episode_payload(self) -> dict[str, Any]:
        return {
            "task": self.task_var.get().strip(),
            "init_config_id": self.bucket_var.get().strip(),
            "source": self.source_var.get().strip(),
            "control_mode": self.mode_var.get().strip(),
            "failure_mode": self.failure_var.get().strip(),
            "notes": self.notes_var.get().strip(),
        }

    def _start_episode(self) -> None:
        self.runtime.command_queue.put(("start_episode", self._episode_payload()))

    def _end_episode(self, success: bool) -> None:
        payload = self._episode_payload()
        payload["success"] = bool(success)
        self.runtime.command_queue.put(("end_episode", payload))

    def _discard_episode(self) -> None:
        self.runtime.command_queue.put(("discard_episode", {"reason": self.notes_var.get().strip()}))

    def _close(self) -> None:
        self.runtime.command_queue.put(("close", None))
        self.runtime.stop_event.set()
        self.root.after(40, self.root.destroy)

    def _to_photo(self, rgb: np.ndarray, *, width: int, height: int):
        from PIL import Image, ImageTk

        if rgb.shape[1] != width or rgb.shape[0] != height:
            rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
        return ImageTk.PhotoImage(Image.fromarray(rgb, mode="RGB"))

    def _set_image(self, key: str, image: np.ndarray | None, *, width: int, height: int) -> None:
        if image is None:
            return
        photo = self._to_photo(image, width=width, height=height)
        label = self.input_labels[key]
        label.configure(image=photo, text="")
        self.photos[key] = photo

    def _add_card(self, card: dict[str, Any]) -> None:
        ttk = self.ttk
        card_id = int(card["id"])
        frame = ttk.LabelFrame(self.cards_frame, text=f"policy recompute #{card_id}", padding=8)
        frame.pack(fill="x", expand=True, pady=(0, 8))
        image = card.get("image_rgb")
        if image is not None:
            img_label = ttk.Label(frame)
            img_label.pack(side="left", padx=(0, 12))
            photo = self._to_photo(image, width=220, height=220)
            img_label.configure(image=photo)
            self.photos[f"card_{card_id}"] = photo
        right = ttk.Frame(frame)
        right.pack(side="left", fill="both", expand=True)
        timing = card.get("timing", {})
        executed = "executed" if card.get("execute") else "ignored/background"
        ttk.Label(
            right,
            text=f"{executed} | round trip {float(timing.get('client_round_trip_ms', float('nan'))):.0f} ms | chunk {card.get('action_steps', 0)}",
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w")
        cot = card.get("cot") or "No natural-language cot_text returned."
        ttk.Label(right, text=f"CoT/raw: {cot}", justify="left", wraplength=900).pack(anchor="w", pady=(4, 4))
        lines = [
            f"raw state:     {np.round(card['raw_arm'], 1).tolist() if card.get('raw_arm') is not None else 'n/a'}",
            f"model state:   {np.round(card['model_state'], 1).tolist() if card.get('model_state') is not None else 'n/a'}",
            f"model action:  {np.round(card['action_model'], 1).tolist()}",
            f"local target:  {np.round(card['target_raw'], 1).tolist()}",
        ]
        ttk.Label(right, text="\n".join(lines), justify="left", font=("Consolas", 9)).pack(anchor="w")
        self.card_widgets[card_id] = frame

    def _refresh(self) -> None:
        snap = self.runtime.snapshot()
        state = "REC" if snap["active"] else "IDLE"
        self.status_var.set(
            f"{state} | {snap['control_mode'].upper()} | torque={'ON' if snap['torque_enabled'] else 'OFF'} | "
            f"saved={snap['saved_episodes']} discarded={snap['discarded_episodes']} | {snap['status']}"
        )
        age = "never"
        if snap["last_observation_sent_at"] is not None:
            age = f"{time.monotonic() - snap['last_observation_sent_at']:.2f}s ago"
        ep = "none" if snap["episode_index"] is None else f"{snap['episode_index']} {snap['episode_uid']} frames={snap['episode_frame_count']}"
        self.detail_var.set(
            f"episode={ep} | bucket={snap['init_config_id']} source={snap['source']} | "
            f"last server obs={age} | chunk {snap['chunk_step']}/{snap['action_steps']} | {snap['detail']}"
        )
        self.joint_vars["raw"].set(format_joint_vector(snap["raw_arm"]))
        self.joint_vars["leader"].set(format_joint_vector(snap["leader_arm"]))
        self.joint_vars["model"].set(format_joint_vector(snap["model_state"]))
        self.joint_vars["action"].set(format_joint_vector(snap["action_model"]))
        self.joint_vars["target"].set(format_joint_vector(snap["target_raw_arm"]))

        now = time.monotonic()
        if (
            snap["live_image_seq"] != self.last_live_image_seq
            and now - self.last_camera_paint_at >= 1.0 / self.runtime.args.dashboard_camera_fps
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
        self.worker.join(timeout=5.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--task", default="Pick up the white block.")
    parser.add_argument("--policy-ckpt-label", default="")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--dataset-repo-id", required=True)
    parser.add_argument("--dataset-fps", type=int, default=15)
    parser.add_argument("--action-fps", type=float, default=15.0)
    parser.add_argument("--expected-action-steps", type=int, default=32)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--max-step-deg", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument("--follower-port", default="COM24")
    parser.add_argument("--leader-port", default="COM22")
    parser.add_argument("--follower-id", default="fenghao_so101_follower")
    parser.add_argument("--leader-id", default="fenghao_so101_leader")
    parser.add_argument(
        "--follower-calibration-dir",
        default=str(Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration" / "robots" / "so101_follower"),
    )
    parser.add_argument(
        "--leader-calibration-dir",
        default=str(Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration" / "teleoperators" / "so101_leader"),
    )
    parser.add_argument("--fixed-camera", type=int, default=2)
    parser.add_argument("--wrist-camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--fixed-crop-right-px", type=int, default=160)
    parser.add_argument("--wrist-crop-right-px", type=int, default=0)
    parser.add_argument("--fixed-auto-exposure", type=float, default=0.25)
    parser.add_argument("--wrist-auto-exposure", type=float, default=0.25)
    parser.add_argument("--fixed-exposure", type=float, default=-6.0)
    parser.add_argument("--wrist-exposure", type=float, default=-6.0)

    parser.add_argument("--init-config-id", default="A_mean_home")
    parser.add_argument("--source", default="autonomous")
    parser.add_argument("--start-control-mode", choices=["policy", "teleop"], default="policy")
    parser.add_argument("--absolute-teleop", action="store_true", help="Use leader absolute angles; default is safer relative takeover.")
    parser.add_argument("--human-send-policy-observations", action="store_true")
    parser.add_argument("--human-policy-observation-interval-s", type=float, default=2.13)

    parser.add_argument("--home-timeout-s", type=float, default=12.0)
    parser.add_argument("--home-tolerance-deg", type=float, default=4.0)
    parser.add_argument("--home-step-deg", type=float, default=5.0)
    parser.add_argument("--home-step-interval-s", type=float, default=0.02)
    parser.add_argument("--home-ignore-gripper", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--joint-offsets", nargs=6, type=float, default=[0.0] * 6)
    parser.add_argument("--joint-scales", nargs=6, type=float, default=[1.0] * 6)

    parser.add_argument("--dashboard-fps", type=float, default=15.0)
    parser.add_argument("--dashboard-camera-fps", type=float, default=10.0)
    parser.add_argument("--dashboard-history", type=int, default=100)
    parser.add_argument("--print-server-responses", action="store_true")
    parser.add_argument("--video-codec", default="libsvtav1")
    parser.add_argument("--image-writer-threads-per-camera", type=int, default=4)
    parser.add_argument("--streaming-encoding", action="store_true")
    parser.add_argument("--encoder-queue-maxsize", type=int, default=30)
    parser.add_argument("--encoder-threads", type=int, default=None)
    args = parser.parse_args()

    args.joint_offsets = np.asarray(args.joint_offsets, dtype=np.float32)
    args.joint_scales = np.asarray(args.joint_scales, dtype=np.float32)
    if args.action_fps <= 0 or args.dataset_fps <= 0 or args.camera_fps <= 0 or args.max_step_deg <= 0:
        parser.error("fps values and max-step-deg must be positive")
    if args.dataset_fps != int(args.action_fps):
        LOGGER.warning("dataset_fps=%s but action_fps=%s; G0.5 collection is normally 15/15", args.dataset_fps, args.action_fps)
    if args.fixed_crop_right_px < 0 or args.fixed_crop_right_px >= args.width:
        parser.error("fixed-crop-right-px must be in [0, width-1]")
    if args.wrist_crop_right_px < 0 or args.wrist_crop_right_px >= args.width:
        parser.error("wrist-crop-right-px must be in [0, width-1]")
    if args.dashboard_fps <= 0 or args.dashboard_camera_fps <= 0:
        parser.error("dashboard fps values must be positive")
    return args


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    runtime = RuntimeState(args=args, task=args.task, init_config_id=args.init_config_id, source=args.source)
    worker = RLCollectorWorker(runtime)
    RLCollectorDashboard(runtime, worker).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
