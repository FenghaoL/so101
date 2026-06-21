"""Set one SO-101 motor ID/baudrate while leaving the rest untouched.

Usage example:
    python scripts/setup_single_so101_motor.py --device follower --port COM24 --motor gripper

Important: physically connect the controller board to the target motor only.
Do not run this with the whole arm daisy-chain connected.
"""

from __future__ import annotations

import argparse

from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig
from lerobot.robots.so101_follower.so101_follower import SO101Follower
from lerobot.teleoperators.so101_leader.config_so101_leader import SO101LeaderConfig
from lerobot.teleoperators.so101_leader.so101_leader import SO101Leader


MOTORS = {
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["follower", "leader"], required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--motor", choices=sorted(MOTORS), required=True)
    parser.add_argument("--id", default=None, help="Optional LeRobot device id; not the motor id.")
    parser.add_argument("--initial-id", type=int, default=None, help="Skip scanning if the current motor ID is known.")
    parser.add_argument(
        "--initial-baudrate",
        type=int,
        default=None,
        help="Skip baudrate scanning if the current baudrate is known.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.device == "follower":
        device = SO101Follower(SO101FollowerConfig(port=args.port, id=args.id))
    else:
        device = SO101Leader(SO101LeaderConfig(port=args.port, id=args.id))

    target_id = device.bus.motors[args.motor].id
    print(f"Target: {args.device} {args.motor} -> ID {target_id} on {args.port}")
    print("Physically connect ONLY this motor to the controller board.")
    input("Press ENTER when only the target motor is connected...")

    try:
        device.bus.setup_motor(
            args.motor,
            initial_baudrate=args.initial_baudrate,
            initial_id=args.initial_id,
        )
        print(f"Done: {args.motor} motor id set to {target_id}.")
    finally:
        if device.bus.is_connected:
            device.bus.port_handler.closePort()


if __name__ == "__main__":
    main()
