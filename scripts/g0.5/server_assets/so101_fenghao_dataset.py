"""G0.5 dataset adapter for this one-arm, two-camera SO101 setup.

Install this file in the GalaxeaVLA server checkout at
``src/g05/data/so101_fenghao_dataset.py``.  It uses the upstream canonical
SO100/SO101 mapper for the raw LeRobot keys ``fixed`` and ``wrist`` and adds
exactly one local rule: crop the rightmost 91 pixels (round(640 / 7)) from
exterior frames.
The wrist image is deliberately never cropped.
"""

from __future__ import annotations

from typing import Any

import torch

from g05.data.so100_canonical_dataset import SO100CanonicalLerobotDatasetV3


class SO101FenghaoLerobotDatasetV3(SO100CanonicalLerobotDatasetV3):
    """Map fixed->exterior and wrist->wrist_right with exterior right crop."""

    def __init__(self, *args: Any, exterior_crop_right_px: int = 91, **kwargs: Any) -> None:
        if exterior_crop_right_px < 0:
            raise ValueError("exterior_crop_right_px must be non-negative")
        self.exterior_crop_right_px = int(exterior_crop_right_px)
        super().__init__(*args, **kwargs)

    def _get_image(self, meta: dict[str, Any], lerobot_sample: dict[str, Any]) -> torch.Tensor:
        image = super()._get_image(meta, lerobot_sample)
        if meta.get("key") != "exterior" or self.exterior_crop_right_px == 0:
            return image

        raw_shape = meta.get("raw_shape") or []
        final_shape = meta.get("shape") or []
        raw_width = int(raw_shape[-1]) if len(raw_shape) == 3 else 640
        final_width = raw_width - self.exterior_crop_right_px
        configured_width = int(final_shape[-1]) if len(final_shape) == 3 else final_width
        if final_width <= 0:
            raise ValueError(
                f"exterior crop {self.exterior_crop_right_px} leaves no pixels from raw width {raw_width}"
            )

        # Real LeRobot frames are [T,C,480,640] and need cropping.  Canonical
        # adapter dummy frames already use the configured cropped width, so do
        # not crop them a second time.
        if image.shape[-1] == raw_width:
            return image[..., :final_width]
        # The processor may later replace ``shape`` with its 256px model input
        # size.  Either configured dummy width is already a placeholder and
        # must not be cropped a second time.
        if image.shape[-1] in {configured_width, final_width}:
            return image
        raise ValueError(
            f"unexpected exterior width {image.shape[-1]}; expected raw {raw_width} "
            f"or cropped {final_width}"
        )
