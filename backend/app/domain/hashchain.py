"""Module."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional
GENESIS = "0" * 64
FORBIDDEN_KEYS = {
    "choice",
    "choice_enc",
    "candidate",
    "candidate_id",
    "voted_for",
    "ballot_choice",
}
def canonical(payload: Any) -> str:
    """Canonical."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
def compute_hash(seq: int, op: str, actor: str, payload: Any, ts: str, prev_hash: str) -> str:
    body = "\x1f".join([prev_hash, str(seq), op, actor, canonical(payload), ts])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
def assert_no_forbidden_keys(payload: Any) -> None:
    """Assert no forbidden keys."""
    if not isinstance(payload, dict):
        return
    bad = FORBIDDEN_KEYS.intersection(payload.keys())
    if bad:
        raise ValueError(
            f"Audit log must not contain vote-choice fields {sorted(bad)}: it would break ballot anonymity"
        )
@dataclass(frozen=True)
class ChainRecord:
    seq: int
    op: str
    actor: str
    payload: dict
    ts: str
    prev_hash: str
    entry_hash: str
def verify_chain(records: list[ChainRecord]) -> tuple[bool, Optional[int], str]:
    """Verify chain."""
    prev = GENESIS
    expected = 1
    for r in records:
        if r.seq != expected:
            return False, r.seq, f"Sequence gap: expected {expected}, got {r.seq} (records may have been deleted)"
        if r.prev_hash != prev:
            return False, r.seq, f"Chain broken at seq={r.seq}: prev_hash does not match the previous entry"
        if compute_hash(r.seq, r.op, r.actor, r.payload, r.ts, r.prev_hash) != r.entry_hash:
            return False, r.seq, f"Chain broken at seq={r.seq}: content does not match the stored hash (tampered)"
        prev = r.entry_hash
        expected += 1
    return True, None, f"Audit chain intact: {len(records)} entries, tip {prev[:16]}…"
def chain_tip(records: list[ChainRecord]) -> str:
    return records[-1].entry_hash if records else GENESIS
