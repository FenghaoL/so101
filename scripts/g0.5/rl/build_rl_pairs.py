#!/usr/bin/env python
"""Build trajectory-level DPO/TPO pairs from G0.5 SO101 RL labels."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            rows.append(row)
    return rows


def find_label_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    by_parent: dict[Path, Path] = {}
    for path in sorted(root.glob("**/rl_rollout_labels.jsonl")):
        by_parent[path.parent] = path
    for path in sorted(root.glob("**/rl_rollout_labels_prepared.jsonl")):
        by_parent[path.parent] = path
    return sorted(by_parent.values())


def episode_ref(row: dict[str, Any], dataset_dir_override: str | None) -> dict[str, Any]:
    dataset_dir = dataset_dir_override or row.get("prepared_dataset_dir") or row.get("dataset_dir")
    return {
        "episode_uid": row.get("episode_uid"),
        "dataset_dir": dataset_dir,
        "episode_index": int(row["episode_index"]),
        "source": row.get("source"),
        "success": bool(row.get("success")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-root", required=True, type=Path, help="A label JSONL file or a directory to scan.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--chosen-sources",
        default="autonomous,intervention,recovery,demo",
        help="Comma-separated sources allowed as chosen when success=true.",
    )
    parser.add_argument(
        "--rejected-sources",
        default="autonomous",
        help="Comma-separated sources allowed as rejected when success=false.",
    )
    parser.add_argument("--max-pairs-per-bucket", type=int, default=20)
    parser.add_argument(
        "--dataset-dir-override",
        default=None,
        help="Optional dataset_dir written into each pair, useful when labels were copied beside a prepared dataset.",
    )
    args = parser.parse_args()

    label_files = find_label_files(args.labels_root)
    if not label_files:
        raise SystemExit(f"No rl_rollout_labels.jsonl files found under {args.labels_root}")

    rows: list[dict[str, Any]] = []
    for path in label_files:
        for row in read_jsonl(path):
            row["_label_file"] = str(path)
            rows.append(row)

    chosen_sources = {item.strip() for item in args.chosen_sources.split(",") if item.strip()}
    rejected_sources = {item.strip() for item in args.rejected_sources.split(",") if item.strip()}
    buckets: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"chosen": [], "rejected": []})

    for row in rows:
        instruction = str(row.get("instruction") or "")
        init_config_id = str(row.get("init_config_id") or "")
        if not instruction or not init_config_id:
            continue
        source = str(row.get("source") or "")
        key = (instruction, init_config_id)
        if bool(row.get("success")) and source in chosen_sources:
            buckets[key]["chosen"].append(row)
        elif not bool(row.get("success")) and source in rejected_sources:
            buckets[key]["rejected"].append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pair_count = 0
    summary: list[dict[str, Any]] = []
    with args.output.open("w", encoding="utf-8") as handle:
        for (instruction, init_config_id), group in sorted(buckets.items()):
            local_count = 0
            for chosen in group["chosen"]:
                for rejected in group["rejected"]:
                    if local_count >= args.max_pairs_per_bucket:
                        break
                    pair = {
                        "format": "g05_so101_rl_pair/v1",
                        "instruction": instruction,
                        "init_config_id": init_config_id,
                        "chosen": episode_ref(chosen, args.dataset_dir_override),
                        "rejected": episode_ref(rejected, args.dataset_dir_override),
                    }
                    handle.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    local_count += 1
                    pair_count += 1
                if local_count >= args.max_pairs_per_bucket:
                    break
            summary.append(
                {
                    "instruction": instruction,
                    "init_config_id": init_config_id,
                    "chosen": len(group["chosen"]),
                    "rejected": len(group["rejected"]),
                    "pairs": local_count,
                }
            )

    summary_path = args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps({"pairs": pair_count, "buckets": summary}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {pair_count} pairs to {args.output}")
    print(f"Wrote summary to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
