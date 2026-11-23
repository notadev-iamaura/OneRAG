"""Save predictions for development-only comparisons without repeatedly running the encoder."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.korean_span_reader import KoreanSpanReader
from scripts.rag_growth_ko_eval import ReaderCorpus, retrieve
from scripts.rag_growth_local import file_sha256


def main() -> None:
    import torch

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panels", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--device", required=True, choices=["mps", "cpu"])
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    torch.set_num_threads(2)
    reader = KoreanSpanReader(args.model, device=args.device)
    corpus = ReaderCorpus(json.loads((args.panels / "dev.corpus.json").read_bytes()))
    weights = file_sha256(args.model / "model.safetensors")
    with args.output.open("x") as f:
        for case in json.loads((args.panels / "dev.questions.json").read_bytes()):
            documents = retrieve(corpus, case["question"], 3)
            record = {"id": case["id"], "model_sha256": weights,
                      "retrieved": [d["id"] for d in documents]}
            try:
                record["spans"] = [asdict(s) for s in reader.predict_spans(case["question"], documents)]
            except Exception as error:
                record["error"] = str(error)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()


if __name__ == "__main__":
    main()
