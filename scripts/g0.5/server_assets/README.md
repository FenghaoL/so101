# Files to install into the GalaxeaVLA GPU checkout

These are deliberately stored on the laptop first.  Copy them to the GPU
checkout, preserving these destinations:

```text
server_assets/so101_fenghao_dataset.py -> src/g05/data/so101_fenghao_dataset.py
server_assets/so101_fenghao.yaml        -> configs/data/so101_fenghao.yaml
server_assets/so101_fenghao_task.yaml   -> configs/task/so101_fenghao.yaml
server_assets/finetune_g05_so101.sh     -> scripts/g0.5/finetune_g05_so101.sh
```

The dataset must be the **prepared** copy produced by
`prepare_g05_so101_dataset.py`, not the raw recording.  Set:

```bash
export G05_SO101_DATASET_DIR=/absolute/path/to/run_g05_model_frame
export G05_SO101_PRETRAINED_CKPT=$PWD/checkpoints/g05-so101/checkpoints/model_state_dict.pt
export G05_OUTPUT_DIR=$PWD/outputs
bash scripts/g0.5/finetune_g05_so101.sh --dry-run model.max_steps=1
```

The first real run computes fresh statistics from the prepared dataset and
writes `dataset_stats.json` into its output directory.  Serve the resulting
fine-tuned checkpoint with that output statistics file.  Do not replace the
zero-shot checkpoint's `dataset_stats.json`.
