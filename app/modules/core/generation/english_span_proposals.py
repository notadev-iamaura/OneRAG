"""Produce alternative English answers with exact offsets from a locally loaded extractive reader."""

from collections.abc import Mapping, Sequence
from typing import Any

from .english_span_reader import EnglishSpanReader
from .korean_span_reader import SpanAnswer, _cited_span


def window_spans(
    starts: Any,
    ends: Any,
    offsets: list[list[int]],
    segments: list[int | None],
    body: str,
    limit: int,
) -> list[tuple[float, int, int]]:
    import numpy as np

    if not np.isfinite(starts).all() or not np.isfinite(ends).all():
        raise ValueError("Nonfinite span proposal logits")
    pos = np.array([i for i, k in enumerate(segments) if k == 1 and offsets[i][1] > offsets[i][0]])
    if not len(pos):
        return []
    left = np.arange(len(pos))[:, None]
    right = left + np.arange(min(40, len(pos)))
    logits = starts[pos, None] + ends[pos[np.minimum(right, len(pos) - 1)]] - (starts[0] + ends[0])
    logits[right >= len(pos)] = -np.inf
    result, seen = [], set()
    for flat in np.argsort(-logits, axis=None, kind="stable"):
        i, w = np.unravel_index(flat, logits.shape)
        score = float(logits[i, w])
        if not np.isfinite(score):
            break
        a, b = offsets[pos[i]][0], offsets[pos[i + w]][1]
        if not 0 <= a < b <= len(body):
            raise ValueError("Proposal offset outside original document")
        while a < b and body[a].isspace():
            a += 1
        while a < b and body[b - 1].isspace():
            b -= 1
        key = body[a:b].casefold()
        if key and key not in seen:
            seen.add(key)
            result.append((score, a, b))
            if len(result) == limit:
                break
    return result


class EnglishSpanProposer(EnglishSpanReader):
    def propose(
        self, question: str, documents: Sequence[Mapping[str, Any]], limit: int = 5
    ) -> list[list[SpanAnswer]]:
        import torch

        if not 1 <= limit <= 10 or not question.strip():
            raise ValueError("A nonempty question and 1–10 proposals per passage are required")
        if not documents:
            return []
        question_offsets = self.tokenizer(
            question,
            add_special_tokens=False,
            truncation=True,
            max_length=96,
            return_offsets_mapping=True,
        )["offset_mapping"]
        if not question_offsets:
            raise ValueError("Question has no tokens")
        q = question[: question_offsets[-1][1]]
        bodies, ids = [], []
        for d in documents:
            source = (
                (d.get("metadata") or {}).get("document_id") or d.get("document_id") or d.get("id")
            )
            body = d.get("content")
            if not source or not isinstance(body, str) or not body.strip():
                raise ValueError("Invalid source document")
            ids.append(str(source))
            bodies.append(body)
        batch = self.tokenizer(
            [q] * len(bodies),
            bodies,
            truncation="only_second",
            max_length=self.max_length,
            stride=96,
            padding=True,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            return_tensors="pt",
        )
        offsets = batch.pop("offset_mapping").tolist()
        mapping = batch.pop("overflow_to_sample_mapping").tolist()
        pools: list[list[tuple[float, int, int]]] = [[] for _ in bodies]
        with torch.inference_mode():
            for i in range(0, len(mapping), 4):
                output = self.model(**{k: v[i : i + 4].to(self.device) for k, v in batch.items()})
                for j, (start, end) in enumerate(
                    zip(
                        output.start_logits.float().cpu().numpy(),
                        output.end_logits.float().cpu().numpy(),
                        strict=True,
                    )
                ):
                    k = i + j
                    doc = mapping[k]
                    pools[doc].extend(
                        window_spans(
                            start, end, offsets[k], batch.sequence_ids(k), bodies[doc], limit
                        )
                    )
        result = []
        for doc, pool in enumerate(pools):
            answers, seen = [], set()
            for score, a, b in sorted(pool, key=lambda x: -x[0]):
                key = bodies[doc][a:b].casefold()
                if key not in seen:
                    answers.append(_cited_span(bodies[doc], doc, ids[doc], a, b, score))
                    seen.add(key)
                if len(answers) == limit:
                    break
            if not answers:
                raise ValueError("No genuine proposal for a supplied passage")
            result.append(answers)
        return result
