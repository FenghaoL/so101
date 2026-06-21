#!/usr/bin/env python
"""Run a remote OpenPI pi0.5 policy on the local SO101 follower."""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import logging
import pathlib
import sys
import time
from contextlib import suppress

import numpy as np


MOTORS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


def _slugify(text: str, max_len: int = 60) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)
    slug = "_".join(part for part in slug.split("_") if part)
    return slug[:max_len] or "rollout"


class RolloutRecorder:
    def __init__(self, args: argparse.Namespace):
        self.enabled = args.record
        self.args = args
        self.run_dir: pathlib.Path | None = None
        self._query_log = None
        self._step_log = None
        self._video_writers = {}
        self._started_at = _datetime.datetime.now().isoformat(timespec="seconds")
        self._t0 = time.perf_counter()

        self.query_states = []
        self.query_steps = []
        self.query_action_chunks = []
        self.step_actions = []
        self.step_sent_actions = []
        self.step_present_states = []
        self.step_query_indices = []
        self.step_chunk_indices = []

        if not self.enabled:
            return

        stamp = _datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = pathlib.Path(args.record_dir) / f"{stamp}_{_slugify(args.prompt)}"
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._query_log = (self.run_dir / "policy_queries.jsonl").open("w", encoding="utf-8")
        self._step_log = (self.run_dir / "executed_steps.jsonl").open("w", encoding="utf-8")

        metadata = {
            "started_at": self._started_at,
            "prompt": args.prompt,
            "host": args.host,
            "port": args.port,
            "robot_port": args.robot_port,
            "robot_id": args.robot_id,
            "motors": MOTORS,
            "control_hz": args.control_hz,
            "replan_every": args.replan_every,
            "max_steps": args.max_steps,
            "max_relative_target": args.max_relative_target,
            "warmup_infers": args.warmup_infers,
            "dry_run": args.dry_run,
            "record_step_state": args.record_step_state,
            "cameras": {
                "fixed": {
                    "index": args.fixed_camera,
                    "width": args.width,
                    "height": args.height,
                    "fps": args.camera_fps,
                    "exposure": args.fixed_exposure,
                },
                "wrist": {
                    "index": args.wrist_camera,
                    "width": args.width,
                    "height": args.height,
                    "fps": args.camera_fps,
                    "exposure": args.wrist_exposure,
                },
            },
            "notes": (
                "Videos contain the observations sent to the policy server, not every motor-control step. "
                "Action arrays are SO101 normalized motor targets in order listed by 'motors'."
            ),
        }
        (self.run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Recording rollout to: {self.run_dir}")

    def _elapsed_s(self) -> float:
        return time.perf_counter() - self._t0

    def record_query(self, query_index: int, step: int, obs: dict, state: np.ndarray, response: dict) -> None:
        if not self.enabled:
            return

        action_chunk = np.asarray(response["actions"], dtype=np.float32)
        server_timing = response.get("server_timing", {})
        entry = {
            "query_index": query_index,
            "step": step,
            "elapsed_s": self._elapsed_s(),
            "state": state.tolist(),
            "action_chunk_shape": list(action_chunk.shape),
            "action_chunk": action_chunk[:, : len(MOTORS)].tolist(),
            "server_timing": server_timing,
        }
        self._query_log.write(json.dumps(entry) + "\n")
        self._query_log.flush()
        self.query_states.append(state.copy())
        self.query_steps.append(step)
        self.query_action_chunks.append(action_chunk[:, : len(MOTORS)].copy())
        self._write_video_frame("fixed_policy_obs.avi", obs["fixed"])
        self._write_video_frame("wrist_policy_obs.avi", obs["wrist"])

    def record_step(
        self,
        step: int,
        query_index: int,
        chunk_index: int,
        action: np.ndarray,
        sent_action: dict[str, float] | None,
        present_state: np.ndarray | None,
    ) -> None:
        if not self.enabled:
            return

        action = np.asarray(action, dtype=np.float32)[: len(MOTORS)]
        sent = None
        if sent_action is not None:
            sent = [float(sent_action[f"{motor}.pos"]) for motor in MOTORS]
        present = None if present_state is None else np.asarray(present_state, dtype=np.float32).tolist()
        entry = {
            "step": step,
            "elapsed_s": self._elapsed_s(),
            "query_index": query_index,
            "chunk_index": chunk_index,
            "action": action.tolist(),
            "sent_action": sent,
            "present_state": present,
        }
        self._step_log.write(json.dumps(entry) + "\n")
        self._step_log.flush()
        self.step_actions.append(action.copy())
        self.step_sent_actions.append(np.asarray(sent if sent is not None else [np.nan] * len(MOTORS), dtype=np.float32))
        self.step_query_indices.append(query_index)
        self.step_chunk_indices.append(chunk_index)
        if present_state is not None:
            self.step_present_states.append(np.asarray(present_state, dtype=np.float32).copy())

    def _write_video_frame(self, name: str, rgb_image: np.ndarray) -> None:
        if not self.args.record_videos:
            return

        import cv2

        image = np.asarray(rgb_image)
        height, width = image.shape[:2]
        writer = self._video_writers.get(name)
        if writer is None:
            assert self.run_dir is not None
            fps = max(1.0, float(self.args.control_hz) / max(1, int(self.args.replan_every)))
            path = str(self.run_dir / name)
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
            if not writer.isOpened():
                logging.warning("Failed to open video writer for %s; skipping this video.", path)
                return
            self._video_writers[name] = writer
        writer.write(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    def close(self) -> None:
        if not self.enabled:
            return

        for writer in self._video_writers.values():
            writer.release()
        if self._query_log is not None:
            self._query_log.close()
        if self._step_log is not None:
            self._step_log.close()

        arrays = {}
        if self.query_states:
            arrays["query_steps"] = np.asarray(self.query_steps, dtype=np.int32)
            arrays["query_states"] = np.stack(self.query_states)
            arrays["query_action_chunks"] = np.stack(self.query_action_chunks)
        if self.step_actions:
            arrays["step_actions"] = np.stack(self.step_actions)
            arrays["step_sent_actions"] = np.stack(self.step_sent_actions)
            arrays["step_query_indices"] = np.asarray(self.step_query_indices, dtype=np.int32)
            arrays["step_chunk_indices"] = np.asarray(self.step_chunk_indices, dtype=np.int32)
        if self.step_present_states:
            arrays["step_present_states"] = np.stack(self.step_present_states)
        if arrays:
            assert self.run_dir is not None
            np.savez_compressed(self.run_dir / "rollout_arrays.npz", **arrays)

        ended = {
            "ended_at": _datetime.datetime.now().isoformat(timespec="seconds"),
            "duration_s": self._elapsed_s(),
            "num_policy_queries": len(self.query_steps),
            "num_executed_steps": len(self.step_actions),
        }
        assert self.run_dir is not None
        (self.run_dir / "summary.json").write_text(json.dumps(ended, indent=2), encoding="utf-8")
        print(f"Saved rollout recording to: {self.run_dir}")


def _add_openpi_client_to_path(openpi_root: pathlib.Path) -> None:
    client_src = openpi_root / "packages" / "openpi-client" / "src"
    if client_src.exists():
        sys.path.insert(0, str(client_src))


def _build_robot(args):
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig
    from lerobot.robots.so101_follower.so101_follower import SO101Follower

    max_relative_target = None if args.max_relative_target <= 0 else float(args.max_relative_target)
    cameras = {
        "fixed": OpenCVCameraConfig(
            index_or_path=args.fixed_camera,
            fps=args.camera_fps,
            width=args.width,
            height=args.height,
            exposure=args.fixed_exposure,
        ),
        "wrist": OpenCVCameraConfig(
            index_or_path=args.wrist_camera,
            fps=args.camera_fps,
            width=args.width,
            height=args.height,
            exposure=args.wrist_exposure,
        ),
    }
    config = SO101FollowerConfig(
        port=args.robot_port,
        id=args.robot_id,
        cameras=cameras,
        max_relative_target=max_relative_target,
        use_degrees=False,
    )
    return SO101Follower(config)


def _state_from_observation(obs: dict) -> np.ndarray:
    return np.asarray([obs[f"{motor}.pos"] for motor in MOTORS], dtype=np.float32)


def _read_robot_state_only(robot) -> np.ndarray:
    present = robot.bus.sync_read("Present_Position")
    return np.asarray([present[motor] for motor in MOTORS], dtype=np.float32)


def _action_to_dict(action: np.ndarray) -> dict[str, float]:
    action = np.asarray(action, dtype=np.float32).reshape(-1)[: len(MOTORS)].copy()
    action[:5] = np.clip(action[:5], -100.0, 100.0)
    action[5] = np.clip(action[5], 0.0, 100.0)
    return {f"{motor}.pos": float(value) for motor, value in zip(MOTORS, action, strict=True)}


def _policy_observation(obs: dict, prompt: str):
    from openpi_client import image_tools

    fixed = image_tools.convert_to_uint8(image_tools.resize_with_pad(obs["fixed"], 224, 224))
    wrist = image_tools.convert_to_uint8(image_tools.resize_with_pad(obs["wrist"], 224, 224))
    return {
        "observation/image": fixed,
        "observation/wrist_image": wrist,
        "observation/state": _state_from_observation(obs),
        "prompt": prompt,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Policy server IP or hostname.")
    parser.add_argument("--port", type=int, default=8000, help="Policy server websocket port.")
    parser.add_argument("--prompt", required=True, help="Task prompt. Use the exact prompt used during training.")
    parser.add_argument("--openpi-root", type=pathlib.Path, default=pathlib.Path(r"D:\workspace\Manipulation\openpi"))
    parser.add_argument("--robot-port", default="COM24")
    parser.add_argument("--robot-id", default="fenghao_so101_follower")
    parser.add_argument("--fixed-camera", type=int, default=2)
    parser.add_argument("--wrist-camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--camera-fps", type=int, default=20)
    parser.add_argument("--fixed-exposure", type=float, default=-5.0)
    parser.add_argument("--wrist-exposure", type=float, default=-5.0)
    parser.add_argument("--control-hz", type=float, default=18.0)
    parser.add_argument("--replan-every", type=int, default=4, help="How many actions to execute before requesting a new chunk.")
    parser.add_argument("--max-steps", type=int, default=360, help="Hard episode length limit.")
    parser.add_argument("--warmup-infers", type=int, default=2, help="Policy requests to run before sending actions.")
    parser.add_argument("--record", action="store_true", help="Record policy inputs, action chunks, executed actions, and timing.")
    parser.add_argument(
        "--record-dir",
        type=pathlib.Path,
        default=pathlib.Path(r"D:\workspace\Manipulation\so101\so101_policy_runs"),
    )
    parser.add_argument("--record-videos", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--record-step-state",
        action="store_true",
        help="Also read follower motor state after each sent action. Useful for debugging but adds serial I/O.",
    )
    parser.add_argument(
        "--max-relative-target",
        type=float,
        default=8.0,
        help="Per-step motor target clamp in SO101 normalized units. Set <=0 to disable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Receive actions but do not send them to the robot.")
    parser.add_argument("--no-wait", action="store_true", help="Start immediately instead of waiting for Enter.")
    parser.add_argument("--log-every", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _add_openpi_client_to_path(args.openpi_root)

    from openpi_client import websocket_client_policy

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    robot = _build_robot(args)
    client = websocket_client_policy.WebsocketClientPolicy(host=args.host, port=args.port)
    metadata = client.get_server_metadata()
    logging.info("Connected to policy server metadata: %s", metadata)

    action_chunk = None
    chunk_i = 0
    query_index = -1
    period_s = 1.0 / args.control_hz
    recorder = RolloutRecorder(args)

    try:
        robot.connect()
        print("\nPrompt:", args.prompt)
        print("Move the arm to the rollout start pose. Keep the big light on and the scene fixed.")
        if args.dry_run:
            print("DRY RUN: actions will be printed but not sent to the robot.")
        if not args.no_wait:
            input("Press Enter to run policy warmup without sending actions...")

        for warmup_i in range(args.warmup_infers):
            obs = robot.get_observation()
            response = client.infer(_policy_observation(obs, args.prompt))
            timing = response.get("server_timing")
            logging.info(
                "warmup %s/%s action_shape=%s server_timing=%s",
                warmup_i + 1,
                args.warmup_infers,
                np.asarray(response["actions"]).shape,
                timing,
            )

        if not args.no_wait:
            input("Warmup done. Press Enter to start policy control...")

        for step in range(args.max_steps):
            step_start = time.perf_counter()

            if action_chunk is None or chunk_i >= min(args.replan_every, len(action_chunk)):
                obs = robot.get_observation()
                state = _state_from_observation(obs)
                request = _policy_observation(obs, args.prompt)
                response = client.infer(request)
                action_chunk = np.asarray(response["actions"], dtype=np.float32)
                if action_chunk.ndim != 2 or action_chunk.shape[1] < len(MOTORS):
                    raise RuntimeError(f"Expected action chunk [T, >=6], got {action_chunk.shape}")
                query_index += 1
                chunk_i = 0
                timing = response.get("server_timing")
                if timing:
                    logging.info("server_timing=%s action_chunk_shape=%s", timing, action_chunk.shape)
                recorder.record_query(query_index, step, obs, state, response)

            current_chunk_i = chunk_i
            action = action_chunk[chunk_i]
            chunk_i += 1
            action_dict = _action_to_dict(action)
            sent = None
            present_state = None

            if args.dry_run:
                if step % args.log_every == 0:
                    print(f"step={step:04d} action={np.round(action[:6], 2)}")
            else:
                sent = robot.send_action(action_dict)
                if args.record and args.record_step_state:
                    present_state = _read_robot_state_only(robot)
                if step % args.log_every == 0:
                    print(f"step={step:04d} sent={[round(sent[f'{m}.pos'], 2) for m in MOTORS]}")
            recorder.record_step(step, query_index, current_chunk_i, action, sent, present_state)

            elapsed = time.perf_counter() - step_start
            if elapsed < period_s:
                time.sleep(period_s - elapsed)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        with suppress(Exception):
            robot.disconnect()
        recorder.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
