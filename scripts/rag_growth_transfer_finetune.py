"""Supervise one local QA head and one final encoder block on native CLS and official token-span targets."""

import argparse
import os
import random
import sys
import time
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_cross_domain import MULTI_REV, MULTI_SHA
from scripts.rag_growth_transfer_rerank import files

SEED = 10571
MAX_SECONDS = 720
MAX_LENGTH = 320


def encode(tok, row):
    question = row["question"]
    qoff = tok(
        question,
        add_special_tokens=False,
        truncation=True,
        max_length=80,
        return_offsets_mapping=True,
    )["offset_mapping"]
    question = question[: qoff[-1][1]]
    b = tok(
        question,
        row["content"],
        truncation="only_second",
        max_length=MAX_LENGTH,
        stride=64,
        return_offsets_mapping=True,
        return_overflowing_tokens=True,
    )
    for i, ids in enumerate(b["input_ids"]):
        start = end = ids.index(tok.cls_token_id)
        if not row["impossible"]:
            answer = row["answers"][0]
            left = answer["answer_start"]
            right = left + len(answer["text"])
            context = [
                j
                for j, (seg, off) in enumerate(
                    zip(b.sequence_ids(i), b["offset_mapping"][i], strict=True)
                )
                if seg == 1 and off[1] > off[0]
            ]
            if (
                not context
                or b["offset_mapping"][i][context[0]][0] > left
                or b["offset_mapping"][i][context[-1]][1] < right
            ):
                continue
            active = [
                j
                for j in context
                if b["offset_mapping"][i][j][1] > left and b["offset_mapping"][i][j][0] < right
            ]
            if not active:
                continue
            start, end = active[0], active[-1]
        return ({k: b[k][i] for k in tok.model_input_names if k in b}, start, end)
    raise ValueError("Official positive span cannot fit a training window")


def run(args):
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    receipt = tr.load(args.output / "data.json")
    weights = files(args.base)
    if weights["model.safetensors"] != MULTI_SHA:
        raise ValueError("Unexpected pretrained checkpoint")
    for k, info in receipt["splits"].items():
        if tr.file_sha256(args.temp / (k + ".json")) != info["sha256"]:
            raise ValueError("Reserved data changed")
    cfg = {
        "weights": weights,
        "base_revision": MULTI_REV,
        "data_registration": tr.file_sha256(args.output / "data.json"),
        "training_code": tr.file_sha256(Path(__file__)),
        "seed": SEED,
        "device": args.device,
        "training_seconds_limit": MAX_SECONDS,
        "batch": 4,
        "epochs": 1,
        "optimizer": "AdamW, FP32, clip norm 1, weight decay .01, warmup 10%, linear decay to .1",
        "learning_rates": {"final_encoder_block": 2e-5, "qa_outputs": 5e-5},
        "max_length": MAX_LENGTH,
        "policy": "Search twelve documents by registered RRF. Keep at most five fine-tuned spans per document. "
        "Select the highest tuned span margin minus .5*log2(retrieval rank). If within two logit units "
        "of the calibrated threshold, defer to the frozen original top-six DeBERTa-large. Otherwise answer only "
        "above threshold. Select one threshold [-4,-2,0,2,4,6] on balanced article-disjoint official train calibration "
        "by max minimum source/stratum accuracy, then total rate, then nearest zero. Report train-validation separately. "
        "Eligible for sealed confirmation only when zero errors, no decrease in all four SQuAD/TyDi development "
        "strata and at least one additional success per domain. Do not evaluate partial training weights.",
        "packages": {k: version(k) for k in ("torch", "transformers", "safetensors")},
    }
    registered = args.output / "preregistration.json"
    if args.phase == "prepare":
        tr.dump(registered, cfg)
        return
    if tr.load(registered) != cfg or (args.output / "training-result.json").exists():
        raise ValueError("Training protocol changed or round already attempted")
    import torch
    from safetensors.torch import save_file
    from transformers import AutoModelForQuestionAnswering, AutoTokenizer

    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    if args.device == "mps":
        torch.mps.manual_seed(SEED)
    rng = random.Random(SEED)
    tok = AutoTokenizer.from_pretrained(args.base, local_files_only=True, use_fast=True)
    raw = tr.load(args.temp / "train.json")
    strata = defaultdict(list)
    for row in raw:
        strata[(row["source"], row["impossible"])].append(encode(tok, row))
    if sorted(map(len, strata.values())) != [128] * 4:
        raise ValueError("Expected 4 balanced strata with 128 examples each")
    for group in strata.values():
        rng.shuffle(group)
    batches = list(zip(*[strata[k] for k in sorted(strata)], strict=True))
    model = (
        AutoModelForQuestionAnswering.from_pretrained(
            args.base, local_files_only=True, use_safetensors=True
        )
        .float()
        .eval()
    )
    model.requires_grad_(False)
    last = model.deberta.encoder.layer[-1]
    head = model.qa_outputs
    for part in (last, head):
        part.requires_grad_(True)
        part.train()
    model.to(args.device)
    selected = {k: v for k, v in model.named_parameters() if v.requires_grad}
    initial_head = head.weight.detach().cpu().clone()
    initial_block = next(iter(last.parameters())).detach().cpu().clone()
    optimizer = torch.optim.AdamW(
        [{"params": last.parameters(), "lr": 2e-5}, {"params": head.parameters(), "lr": 5e-5}],
        weight_decay=0.01,
        foreach=False,
    )
    history = []
    start_time = time.monotonic()
    for i, batch in enumerate(batches):
        if time.monotonic() - start_time >= MAX_SECONDS:
            break
        features, starts, ends = zip(*batch, strict=True)
        padded = tok.pad(
            list(features), padding=True, pad_to_multiple_of=8, return_tensors="pt"
        ).to(args.device)
        factor = min((i + 1) / 13, max(0.1, (len(batches) - i) / (len(batches) - 13)))
        for group, lr in zip(optimizer.param_groups, (2e-5, 5e-5), strict=True):
            group["lr"] = lr * factor
        optimizer.zero_grad(set_to_none=True)
        loss = model(
            **padded,
            start_positions=torch.tensor(starts, device=args.device),
            end_positions=torch.tensor(ends, device=args.device),
        ).loss
        val = float(loss.detach().item())
        if not 0 <= val < 100:
            raise ValueError("Nonfinite or invalid QA loss")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(selected.values(), 1.0)
        if not torch.isfinite(norm).item():
            raise ValueError("Nonfinite update")
        optimizer.step()
        history.append(val)
        if (i + 1) % 16 == 0:
            print(
                "training step",
                i + 1,
                "/",
                len(batches),
                "elapsed",
                round(time.monotonic() - start_time, 1),
                flush=True,
            )
    elapsed = time.monotonic() - start_time
    complete = len(history) == len(batches) and elapsed <= MAX_SECONDS + 2
    result = {
        "complete": complete,
        "seconds": elapsed,
        "updates": len(history),
        "expected_updates": len(batches),
        "actual_training_examples": len(history) * 4,
        "loss_per_batch": history,
        "selected_layer_names": list(selected),
        "trainable_parameters": sum(v.numel() for v in selected.values()),
        "all_parameters": sum(v.numel() for v in model.parameters()),
        "protocol_sha256": tr.file_sha256(registered),
        "qa_head_max_change": float((head.weight.detach().cpu() - initial_head).abs().max()),
        "top_block_first_tensor_max_change": float(
            (next(iter(last.parameters())).detach().cpu() - initial_block).abs().max()
        ),
    }
    if complete:
        path = args.temp / "trained-adapter.safetensors"
        if path.exists():
            raise ValueError("Training adapter already exists")
        save_file({k: v.detach().cpu().contiguous() for k, v in selected.items()}, str(path))
        result["adapter_sha256"] = tr.file_sha256(path)
    tr.dump(args.output / "training-result.json", result)
    print({k: v for k, v in result.items() if k not in {"loss_per_batch", "selected_layer_names"}})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "train"))
    for k in ("base", "temp", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="mps")
    run(p.parse_args())
