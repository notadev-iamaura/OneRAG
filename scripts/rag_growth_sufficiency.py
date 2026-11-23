"""Run the Korean passage sufficiency challenger on retrieved articles only."""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.passage_sufficiency import PassageSufficiency
from scripts.rag_growth_ko_eval import ReaderCorpus, retrieve
from scripts.rag_growth_local import file_sha256

WEIGHTS = "7b6ac5dbac2c1bad001f730b019d0e416ffdeb9e487a996fb36440323b605655"


def main() -> None:
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panels", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=("mps", "cpu"), default="cpu")
    args = parser.parse_args()
    torch.set_num_threads(2)
    if file_sha256(args.checkpoint / "model.safetensors") != WEIGHTS:
        raise ValueError("Unexpected passage sufficiency checkpoint")
    model = PassageSufficiency(args.checkpoint, args.device)
    corpus = ReaderCorpus(json.loads((args.panels / "dev.corpus.json").read_bytes()))
    with args.output.open("x") as stream:
        for row in json.loads((args.panels / "dev.questions.json").read_bytes()):
            docs = retrieve(corpus, row["question"], 2)
            scores = model.scores(row["question"], docs)
            stream.write(json.dumps({"id": row["id"], "ids": [d["id"] for d in docs], "scores": scores}) + "\n")
            stream.flush()


if __name__ == "__main__":
    main()
