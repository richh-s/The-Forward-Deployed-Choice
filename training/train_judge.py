"""
Train the Tenacious-Bench preference judge critic using SimPO on Qwen2.5-1.5B.

Algorithm: SimPO (Meng, Xia & Chen, NeurIPS 2024)
  - Reference-free (no frozen π_ref needed)
  - Length-normalized reward (average log-prob)
  - Target reward margin γ = 0.3 (paper default 0.5; see hyperparams.json for calibration)

Hardware target: Colab T4 (16 GB VRAM) via Unsloth

Usage:
  python training/train_judge.py --config training/hyperparams.json
  python training/train_judge.py --dry-run  # validate data loading only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return json.load(f)


def load_preference_pairs(pairs_path: str) -> list[dict]:
    pairs = []
    with open(pairs_path) as f:
        for line in f:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))
    log.info("Loaded %d preference pairs from %s", len(pairs), pairs_path)
    return pairs


def format_pairs_for_trl(pairs: list[dict]) -> list[dict]:
    """Convert Tenacious preference pairs to TRL CPOTrainer format."""
    formatted = []
    for p in pairs:
        formatted.append(
            {
                "prompt": p["prompt"],
                "chosen": p["chosen"],
                "rejected": p["rejected"],
            }
        )
    return formatted


def run_training(config: dict, dry_run: bool = False) -> None:
    try:
        from unsloth import FastLanguageModel
        from trl import CPOConfig, CPOTrainer
        import torch
    except ImportError as e:
        log.error("Unsloth or TRL not installed: %s", e)
        log.error("Install with: pip install unsloth trl torch")
        sys.exit(1)

    pairs_path = config["data"]["train_path"]
    pairs = load_preference_pairs(pairs_path)
    formatted = format_pairs_for_trl(pairs)

    if dry_run:
        log.info("DRY RUN: loaded %d pairs, first pair keys: %s", len(formatted), list(formatted[0].keys()))
        return

    model_name = config["backbone"]
    lora_cfg = config["lora"]
    simpo_cfg = config["simpo"]
    train_cfg = config["training"]

    log.info("Loading model: %s", model_name)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=train_cfg["max_length"],
        dtype=None,
        load_in_4bit=False,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_cfg["r"],
        target_modules=lora_cfg["target_modules"],
        lora_alpha=lora_cfg["lora_alpha"],
        lora_dropout=lora_cfg["lora_dropout"],
        bias=lora_cfg["bias"],
        use_gradient_checkpointing="unsloth",
        random_state=train_cfg["seed"],
    )

    from datasets import Dataset

    dataset = Dataset.from_list(formatted)
    split = dataset.train_test_split(test_size=0.1, seed=train_cfg["seed"])
    train_dataset = split["train"]
    eval_dataset = split["test"]

    training_args = CPOConfig(
        output_dir="training/model_weights",
        num_train_epochs=train_cfg["num_train_epochs"],
        per_device_train_batch_size=train_cfg["per_device_train_batch_size"],
        gradient_accumulation_steps=train_cfg["gradient_accumulation_steps"],
        learning_rate=train_cfg["learning_rate"],
        lr_scheduler_type=train_cfg["lr_scheduler_type"],
        warmup_ratio=train_cfg["warmup_ratio"],
        fp16=train_cfg.get("fp16", True),
        optim=train_cfg["optim"],
        seed=train_cfg["seed"],
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        # SimPO-specific
        loss_type=simpo_cfg["loss_type"],
        beta=simpo_cfg["beta"],
        cpo_alpha=simpo_cfg["gamma"],
        report_to="none",
    )

    trainer = CPOTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
    )

    log.info("Starting SimPO training (γ=%.1f, backbone=%s)", simpo_cfg["gamma"], model_name)
    trainer.train()

    output_dir = Path("training/model_weights")
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    log.info("Model saved to %s", output_dir)

    # write training summary
    summary = {
        "backbone": model_name,
        "algorithm": "SimPO",
        "gamma": simpo_cfg["gamma"],
        "epochs": train_cfg["num_train_epochs"],
        "train_pairs": len(train_dataset),
        "eval_pairs": len(eval_dataset),
        "output_dir": str(output_dir),
    }
    with open("training/training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    log.info("Training complete: %s", summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Tenacious-Bench judge critic (SimPO)")
    parser.add_argument("--config", default="training/hyperparams.json")
    parser.add_argument("--dry-run", action="store_true", help="Load data only, do not train")
    args = parser.parse_args()

    config = load_config(args.config)
    run_training(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
