"""Prepare a raw LeRobot v3 SO101 recording for G0.5 fine-tuning.

This tool never modifies the source dataset.  It creates a sibling dataset with
the same videos and metadata, transforms only the action/state parquet columns
into the G0.5 SO100 training frame, and writes an auditable manifest.

The fixed-camera crop is deliberately not baked into videos: the accompanying
G0.5 dataset adapter crops it at training load time.  Keeping raw videos intact
makes future camera-contract changes reversible.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


JOINT_NAMES = [
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
]
SIGNS = np.asarray([1, -1, 1, 1, 1, 1], dtype=np.float32)
OFFSETS = np.asarray([0, 90, 90, 0, 0, 0], dtype=np.float32)


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_info(root: Path) -> dict[str, Any]:
    path = root / "meta" / "info.json"
    if not path.is_file():
        die(f"missing LeRobot metadata: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"invalid JSON in {path}: {exc}")


def get_feature(info: dict[str, Any], key: str) -> dict[str, Any]:
    features = info.get("features", {})
    value = features.get(key)
    if not isinstance(value, dict):
        die(f"required feature {key!r} is absent from meta/info.json")
    return value


def validate_source(
    root: Path,
    *,
    expect_fps: int | None,
    fixed_crop_right_px: int,
    wrist_crop_right_px: int,
) -> tuple[dict[str, Any], list[Path]]:
    if not root.is_dir():
        die(f"source dataset directory does not exist: {root}")
    info = load_info(root)
    version = str(info.get("codebase_version", ""))
    if version != "v3.0":
        die(
            f"expected a LeRobot v3.0 dataset, got codebase_version={version!r}. "
            "Do not feed the old pi0.5/v2.1 recording directly to G0.5."
        )

    fps = info.get("fps")
    if not isinstance(fps, (int, float)):
        die("meta/info.json has no numeric fps")
    if expect_fps is not None and int(fps) != expect_fps:
        die(f"dataset fps is {fps}, expected {expect_fps}")

    for key in ("action", "observation.state"):
        feature = get_feature(info, key)
        if list(feature.get("shape", [])) != [6]:
            die(f"{key} must have shape [6], got {feature.get('shape')!r}")
        names = feature.get("names")
        if names is not None and list(names) != JOINT_NAMES:
            die(f"{key} joint order differs from G0.5 SO101 order: {names!r}")

    fixed = get_feature(info, "observation.images.fixed")
    wrist = get_feature(info, "observation.images.wrist")
    for name, feature in (("fixed", fixed), ("wrist", wrist)):
        shape = list(feature.get("shape", []))
        if shape != [480, 640, 3]:
            die(f"observation.images.{name} must be 480x640x3, got {shape!r}")

    if not 0 <= fixed_crop_right_px < 640:
        die("fixed crop-right pixels must be in [0, 639]")
    if not 0 <= wrist_crop_right_px < 640:
        die("wrist crop-right pixels must be in [0, 639]")

    parquet_files = sorted((root / "data").glob("**/*.parquet"))
    if not parquet_files:
        die(f"no episode parquet files found below {root / 'data'}")

    return info, parquet_files


def replace_joint_column(table: pa.Table, name: str) -> pa.Table:
    index = table.schema.get_field_index(name)
    if index < 0:
        die(f"parquet file is missing required column {name!r}")
    field = table.schema.field(index)
    values = np.asarray(table.column(index).combine_chunks().to_pylist(), dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 6:
        die(f"column {name!r} is expected to be [N, 6], got {values.shape}")
    values_model = values * SIGNS + OFFSETS
    transformed = pa.array(values_model.tolist(), type=field.type)
    return table.set_column(index, field, transformed)


def link_or_copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def prepare(source: Path, destination: Path, *, fixed_crop_right_px: int, wrist_crop_right_px: int) -> None:
    if destination.exists():
        die(f"destination already exists; refusing to overwrite: {destination}")
    if source.resolve() == destination.resolve():
        die("source and destination cannot be the same directory")

    destination.mkdir(parents=True)
    transformed_parquet = 0
    linked_files = 0
    copied_files = 0
    try:
        for file in source.rglob("*"):
            relative = file.relative_to(source)
            target = destination / relative
            if file.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if relative.parts and relative.parts[0] == "data" and file.suffix == ".parquet":
                table = pq.read_table(file)
                table = replace_joint_column(table, "observation.state")
                table = replace_joint_column(table, "action")
                target.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(table, target, compression="zstd")
                transformed_parquet += 1
            else:
                mode = link_or_copy(file, target)
                linked_files += mode == "hardlink"
                copied_files += mode == "copy"
    except Exception:
        print(
            f"Preparation stopped. Source is untouched; partial destination remains for inspection: {destination}",
            file=sys.stderr,
        )
        raise

    manifest = {
        "format": "g05_so101_prepared_dataset/v1",
        "source_dataset": str(source),
        "coordinate_frame": {
            "source": "LeRobot calibrated degrees",
            "destination": "G0.5 SO100 training/model frame",
            "joint_order": JOINT_NAMES,
            "formula": "q_model = signs * q_arm + offsets",
            "signs": SIGNS.tolist(),
            "offsets": OFFSETS.tolist(),
            "applied_to": ["observation.state", "action"],
        },
        "camera_contract": {
            "raw_fixed_key": "observation.images.fixed",
            "raw_wrist_key": "observation.images.wrist",
            "canonical_slots": {
                "fixed": "exterior",
                "wrist": "wrist_right",
                "wrist_left": "zero_padded",
            },
            "fixed_crop_right_px": fixed_crop_right_px,
            "wrist_crop_right_px": wrist_crop_right_px,
            "crop_implementation": "training adapter; source and prepared videos remain unmodified",
        },
        "files": {
            "transformed_episode_parquet": transformed_parquet,
            "hardlinked_unchanged_files": linked_files,
            "copied_unchanged_files": copied_files,
        },
    }
    (destination / "g05_preparation_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Raw LeRobot v3 dataset directory")
    parser.add_argument("--destination", type=Path, help="New G0.5 model-frame dataset directory")
    parser.add_argument("--expect-fps", type=int, default=15)
    # round(640 / 7): the fine-tuning exterior image retains 549 of 640 columns.
    parser.add_argument("--fixed-crop-right-px", type=int, default=91)
    parser.add_argument("--wrist-crop-right-px", type=int, default=0)
    parser.add_argument("--verify-only", action="store_true", help="Validate source schema without writing files")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned conversion without writing files")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    info, parquet_files = validate_source(
        source,
        expect_fps=args.expect_fps,
        fixed_crop_right_px=args.fixed_crop_right_px,
        wrist_crop_right_px=args.wrist_crop_right_px,
    )
    print("G0.5 SO101 dataset schema: PASS")
    print(f"  source:         {source}")
    print(f"  LeRobot format: {info['codebase_version']}")
    print(f"  fps:            {info['fps']}")
    print(f"  episode files:  {len(parquet_files)}")
    print("  fields:         action/state=[6], images=fixed+wrist")
    print(
        "  G0.5 frame:     q_model = [1,-1,1,1,1,1] * q_arm + [0,90,90,0,0,0]"
    )
    print(
        f"  image contract: fixed crop-right={args.fixed_crop_right_px}; wrist crop-right={args.wrist_crop_right_px}"
    )

    if args.verify_only:
        return 0
    if args.destination is None:
        die("--destination is required unless --verify-only is used")
    destination = args.destination.expanduser().resolve()
    if args.dry_run:
        print(f"DRY RUN: would create {destination} without changing {source}")
        return 0

    prepare(
        source,
        destination,
        fixed_crop_right_px=args.fixed_crop_right_px,
        wrist_crop_right_px=args.wrist_crop_right_px,
    )
    print(f"Prepared G0.5 model-frame dataset: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
