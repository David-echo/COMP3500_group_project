#!/usr/bin/env python3
"""
独立审计链校验工具 (Standalone audit verifier)
=============================================

用途：**不经过 Web 应用**，直接对数据库文件校验审计链完整性。

这个工具的存在本身就是一条工程论证：
审计能力不应依赖被审计的系统自己"说自己没问题"。
任何第三方（例如选举监察机构）拿到数据库文件即可独立复核。

用法:
    python3 tools/verify_audit.py                       # 默认数据库
    python3 tools/verify_audit.py data/election.db      # 指定数据库
    python3 tools/verify_audit.py --json                # 机器可读输出

退出码:
    0 = 链完整
    1 = 链已断裂（可能被篡改）
    2 = 无法读取数据库
"""

from __future__ import annotations

import argparse
import json
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

import db  # noqa: E402


def verify(db_path: str) -> tuple[int, dict]:
    if not os.path.exists(db_path):
        return 2, {"ok": False, "error": f"数据库不存在：{db_path}"}

    conn = db.connect(db_path)
    try:
        # 表可能不存在（空库）
        has = conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ).fetchone()["c"]
        if not has:
            return 2, {"ok": False, "error": "该数据库没有 audit_log 表"}

        chain = db.read_audit_chain(conn)
        ok, bad, msg = db.verify_audit(conn)

        # 附加统计，便于人工复核
        stats = {}
        for t in ("elections", "positions", "candidates", "voter_roll", "ballots",
                  "receipts", "votes_log", "results"):
            try:
                stats[t] = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            except Exception:
                stats[t] = None

        return (0 if ok else 1), {
            "ok": ok,
            "database": os.path.abspath(db_path),
            "audit_entries": len(chain),
            "first_bad_seq": bad,
            "message": msg,
            "chain_tip": chain[-1].entry_hash if chain else db.hashchain.GENESIS,
            "counts": stats,
        }
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="独立校验选举系统审计链完整性")
    ap.add_argument(
        "db",
        nargs="?",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "election.db"
        ),
        help="数据库文件路径",
    )
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    code, result = verify(args.db)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    print("=" * 62)
    print(" 审计链独立校验 (Audit chain verification)")
    print("=" * 62)
    print(f" 数据库      : {result.get('database', args.db)}")
    if "error" in result:
        print(f" ❌ {result['error']}")
        return code

    print(f" 审计记录数  : {result['audit_entries']}")
    print(f" 链尾哈希    : {result['chain_tip']}")
    print("-" * 62)
    if result["ok"]:
        print(f" ✅ {result['message']}")
    else:
        print(f" ❌ {result['message']}")
        print(f"    第一条断裂记录序号: {result['first_bad_seq']}")
        print("    结论：审计日志已不可信，存在被篡改或删除的记录。")
    print("-" * 62)
    print(" 数据规模:")
    for k, v in (result.get("counts") or {}).items():
        print(f"   {k:<12} {v}")
    print("=" * 62)
    return code


if __name__ == "__main__":
    sys.exit(main())
