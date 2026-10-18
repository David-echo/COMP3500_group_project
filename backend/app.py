"""
选举管理与投票系统 — Web 应用层
COMP 3500SEF / 8500SEF 小组项目

启动:
    python3 backend/app.py
访问:
    http://localhost:8767

架构分层（报告中的 ADR-002）:
    app.py      仅做 HTTP 编排、鉴权、错误翻译
    service.py  业务流程（投票/计票/核验），不依赖 Flask
    db.py       持久化与约束
    domain/     纯逻辑（状态机 / 哈希链 / 计票策略），可完整单测
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, g, request, send_from_directory, session
from werkzeug.security import check_password_hash

from domain import lifecycle
import crypto
import db
import seed as seed_module
import service

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "election.db")
SECRET_PATH = os.path.join(DATA_DIR, "secret.key")

# ⚠️ 以下两个默认值**仅供课程演示**，任何真实部署都必须用环境变量覆盖。
#    - TAMPER_TOKEN：仅用于「篡改演练」DEMO 端点，且该端点本身只改审计日志、可还原
#    - SECRET_KEY  ：Flask 会话签名密钥；默认为演示值，生产环境务必设置强随机值
TAMPER_TOKEN = os.environ.get("TAMPER_TOKEN", "TAMPER-DEMO-2026")


def create_app(**config: Any) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "comp3500-demo-secret-change-me"),
        DB_PATH=os.environ.get("ELECTION_DB", DB_PATH),
        SECRET_PATH=os.environ.get("ELECTION_SECRET", SECRET_PATH),
        JSON_AS_ASCII=False,
    )
    app.config.update(config)

    # ---------------- 连接管理 ----------------
    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = db.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    # ---------------- 初始化 ----------------
    with app.app_context():
        conn = db.connect(app.config["DB_PATH"])
        db.migrate(conn)
        conn.close()

    @app.before_request
    def _tick():
        """每次请求前按时间自动推进选举状态（到点开票/截止）。"""
        if request.path.startswith("/api/"):
            db.tick_elections(get_db())

    # ---------------- 鉴权 ----------------
    def current_user() -> dict | None:
        return session.get("user")

    def require_voter(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u or u.get("role") != "voter":
                return jsonify({"error": "请先以选民身份登录"}), 401
            return fn(*a, **kw)

        return wrapper

    def require_admin(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u or u.get("role") != "admin":
                return jsonify({"error": "需要管理员权限"}), 403
            return fn(*a, **kw)

        return wrapper

    def ballot_key() -> bytes:
        master = crypto.load_or_create_secret(app.config["SECRET_PATH"])
        return crypto.derive_key(master, "ballot-master")

    # ---------------- 静态页 ----------------
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    # ---------------- 健康检查 ----------------
    @app.route("/api/health")
    def health():
        conn = get_db()
        ok, bad, msg = db.verify_audit(conn)
        return jsonify(
            {
                "status": "ok",
                "db": os.path.basename(app.config["DB_PATH"]),
                "schema_version": db.SCHEMA_VERSION,
                "audit_chain_ok": ok,
                "audit_chain_message": msg,
                "counts": {
                    "elections": conn.execute("SELECT COUNT(*) c FROM elections").fetchone()["c"],
                    "voters": conn.execute("SELECT COUNT(*) c FROM voter_roll").fetchone()["c"],
                    "ballots": conn.execute("SELECT COUNT(*) c FROM ballots").fetchone()["c"],
                    "audit_entries": conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
                },
            }
        )

    # ---------------- 选举 ----------------
    def _election_detail(conn, row) -> dict:
        positions = []
        for p in conn.execute(
            "SELECT id, title, seats FROM positions WHERE election_id=? ORDER BY id", (row["id"],)
        ).fetchall():
            cands = [
                {"idx": c["idx"], "name": c["name"], "party": c["party"]}
                for c in conn.execute(
                    "SELECT idx, name, party FROM candidates WHERE position_id=? ORDER BY idx",
                    (p["id"],),
                ).fetchall()
            ]
            positions.append(
                {
                    "position_id": p["id"],
                    "title": p["title"],
                    "seats": p["seats"],
                    "candidates": cands,
                    "ballot_count": conn.execute(
                        "SELECT COUNT(*) c FROM ballots WHERE position_id=?", (p["id"],)
                    ).fetchone()["c"],
                }
            )
        total_voters = conn.execute(
            "SELECT COUNT(*) c FROM voter_roll WHERE election_id=?", (row["id"],)
        ).fetchone()["c"]
        voted = conn.execute(
            "SELECT COUNT(*) c FROM voter_roll WHERE election_id=? AND has_voted=1", (row["id"],)
        ).fetchone()["c"]
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "status_label": {
                "scheduled": "未开始",
                "open": "投票进行中",
                "closed": "已截止",
                "published": "结果已公布",
            }[row["status"]],
            "opens_at": row["opens_at"],
            "closes_at": row["closes_at"],
            "strategy": row["strategy"],
            "positions": positions,
            "turnout": {
                "voted": voted,
                "total": total_voters,
                "percent": round(voted * 100.0 / total_voters, 1) if total_voters else 0.0,
            },
        }

    @app.route("/api/elections")
    def list_elections():
        conn = get_db()
        rows = conn.execute("SELECT * FROM elections ORDER BY id").fetchall()
        return jsonify({"elections": [_election_detail(conn, r) for r in rows]})

    @app.route("/api/elections/<int:eid>")
    def get_election(eid: int):
        conn = get_db()
        row = conn.execute("SELECT * FROM elections WHERE id=?", (eid,)).fetchone()
        if row is None:
            return jsonify({"error": "选举不存在"}), 404
        return jsonify(_election_detail(conn, row))

    # ---------------- 演示辅助 ----------------
    @app.route("/api/demo/voters")
    def demo_voters():
        """
        返回方便现场测试的选民编号及其可参与的选举，便于评审老师直接登录投票。

        策略：优先挑选**在尽量多的选举中尚未投票**的选民 ——
        这样同一个人可以连续测试多场选举，不必反复换号。
        """
        conn = get_db()
        rows = conn.execute(
            """SELECT vr.voter_id, vr.name, vr.election_id, vr.has_voted, e.status
                 FROM voter_roll vr
                 JOIN elections e ON e.id = vr.election_id
                WHERE vr.eligible = 1
                ORDER BY vr.voter_id, vr.election_id""",
        ).fetchall()

        per_voter: dict[str, dict] = {}
        for r in rows:
            v = per_voter.setdefault(
                r["voter_id"], {"voter_id": r["voter_id"], "name": r["name"], "available": []}
            )
            if r["has_voted"] == 0:
                v["available"].append({"election_id": r["election_id"], "status": r["status"]})

        # 可投选举数多的排前面，其次编号小的排前面（保证结果稳定）
        ranked = sorted(
            (v for v in per_voter.values() if v["available"]),
            key=lambda v: (-len(v["available"]), v["voter_id"]),
        )
        # 若某个"未投票"的选民所属选举已截止，仍可能拿到，过滤掉非 open 的
        for v in ranked:
            v["available"] = [a for a in v["available"] if a["status"] == "open"]
        ranked = [v for v in ranked if v["available"]]

        return jsonify(
            {
                "voter_pin": seed_module.VOTER_PIN,
                "voter_count": len(ranked),
                "voters": ranked[:12],
                "admin": {"username": seed_module.ADMIN_USER, "pin": seed_module.ADMIN_PIN},
            }
        )

    # ---------------- 认证 ----------------
    @app.route("/api/login", methods=["POST"])
    def login():
        data = request.get_json(silent=True) or {}
        role = (data.get("role") or "voter").strip()
        username = (data.get("username") or "").strip()
        pin = data.get("pin") or ""

        if role == "admin":
            if username == seed_module.ADMIN_USER and pin == seed_module.ADMIN_PIN:
                session["user"] = {"role": "admin", "name": seed_module.ADMIN_USER}
                return jsonify({"ok": True, "user": session["user"]})
            return jsonify({"error": "管理员账号或密码错误"}), 401

        # ---- 选民登录：先登录，再选选举（不在此处绑定选举）----
        if not username or not pin:
            return jsonify({"error": "请输入选民编号与 PIN"}), 400

        conn = get_db()
        rows = conn.execute(
            """SELECT vr.election_id, vr.voter_id, vr.name, vr.pin_hash, vr.eligible,
                      e.title, e.status
                 FROM voter_roll vr
                 JOIN elections e ON e.id = vr.election_id
                WHERE vr.voter_id = ?
                ORDER BY vr.election_id""",
            (username,),
        ).fetchall()

        # 认证：只要在任意一场选举中登记的 PIN 匹配即可（同一 PIN 用于所有选举）
        if not rows or not any(check_password_hash(r["pin_hash"], pin) for r in rows):
            return jsonify({"error": "选民编号或 PIN 错误"}), 401

        elections = [
            {
                "election_id": r["election_id"],
                "title": r["title"],
                "status": r["status"],
                "eligible": bool(r["eligible"]),
                "has_voted": False,
            }
            for r in rows
        ]
        session["user"] = {
            "role": "voter",
            "voter_id": rows[0]["voter_id"],
            "name": rows[0]["name"],
            "elections": elections,
        }
        return jsonify({"ok": True, "user": session["user"]})

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session.pop("user", None)
        return jsonify({"ok": True})

    @app.route("/api/me")
    def me():
        u = current_user()
        if not u:
            return jsonify({"user": None})
        if u.get("role") == "voter":
            # 动态补上每场选举的"是否已投票"，供选民选择要参与哪一场
            conn = get_db()
            elections = []
            for e in u.get("elections", []):
                row = conn.execute(
                    "SELECT has_voted, eligible FROM voter_roll WHERE election_id=? AND voter_id=?",
                    (e["election_id"], u["voter_id"]),
                ).fetchone()
                elections.append(
                    {
                        **e,
                        "has_voted": bool(row["has_voted"]) if row else False,
                        "eligible": bool(row["eligible"]) if row else False,
                    }
                )
            u = {**u, "elections": elections}
        return jsonify({"user": u})

    # ---------------- 投票 ----------------
    @app.route("/api/vote", methods=["POST"])
    @require_voter
    def vote():
        u = current_user()
        data = request.get_json(silent=True) or {}
        choice = data.get("choice") or []
        if not isinstance(choice, list):
            return jsonify({"error": "选择格式错误"}), 400
        try:
            choice = [int(c) for c in choice]
        except (TypeError, ValueError):
            return jsonify({"error": "选择必须是候选序号"}), 400

        conn = get_db()
        try:
            election_id = int(data.get("election_id"))
            position_id = int(data.get("position_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "缺少选举或职位参数"}), 400

        # 安全校验：登录选民只能投自己名册内的选举
        allowed = {e["election_id"] for e in u.get("elections", [])}
        if election_id not in allowed:
            return jsonify({"error": "您不在该选举的选民名册内"}), 403

        try:
            outcome = service.cast_ballot(
                conn,
                ballot_key=ballot_key(),
                election_id=election_id,
                position_id=position_id,
                voter_id=u["voter_id"],
                choice=choice,
                actor=u["voter_id"],
            )
        except service.VoteError as e:
            return jsonify({"error": str(e)}), 400
        except lifecycle.ElectionClosed as e:
            return jsonify({"error": str(e)}), 409
        return jsonify(
            {
                "ok": True,
                "receipt_code": outcome.receipt_code,
                "audit_seq": outcome.audit_seq,
                "message": "投票成功。请保存凭证码，可用于确认您的选票已计入。",
            }
        )

    @app.route("/api/receipt/<code>")
    def receipt(code: str):
        return jsonify(service.verify_receipt(get_db(), code))

    # ---------------- 结果 ----------------
    @app.route("/api/results/<int:eid>")
    def results(eid: int):
        conn = get_db()
        row = conn.execute("SELECT status FROM elections WHERE id=?", (eid,)).fetchone()
        if row is None:
            return jsonify({"error": "选举不存在"}), 404
        # 未截止的选举不公开计票结果，避免影响投票
        if row["status"] in ("scheduled", "open"):
            return jsonify(
                {
                    "published": False,
                    "message": "选举尚未截止，计票结果不予公开（防止影响投票行为）",
                    "status": row["status"],
                }
            )
        try:
            data = service.publish_results(conn, ballot_key(), eid, actor="admin")
        except service.VoteError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"published": True, "results": data["results"]})

    # ---------------- 完整性校验 ----------------
    @app.route("/api/integrity/<int:eid>")
    def integrity(eid: int):
        return jsonify(service.check_invariants(get_db(), eid))

    @app.route("/api/audit/verify")
    def audit_verify():
        conn = get_db()
        ok, bad, msg = db.verify_audit(conn)
        chain = db.read_audit_chain(conn)
        return jsonify(
            {
                "ok": ok,
                "first_bad_seq": bad,
                "message": msg,
                "length": len(chain),
                "chain_tip": chain[-1].entry_hash if chain else "",
            }
        )

    @app.route("/api/audit/entries")
    def audit_entries():
        conn = get_db()
        limit = min(request.args.get("limit", 40, type=int) or 40, 500)
        rows = conn.execute(
            "SELECT seq, op, actor, payload, ts, entry_hash FROM audit_log ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return jsonify(
            {
                "entries": [
                    {
                        "seq": r["seq"],
                        "op": r["op"],
                        "actor": r["actor"],
                        "payload": json.loads(r["payload"]),
                        "ts": r["ts"],
                        "entry_hash": r["entry_hash"][:20] + "…",
                    }
                    for r in rows
                ]
            }
        )

    # ---------------- 管理操作 ----------------
    @app.route("/api/admin/status", methods=["POST"])
    @require_admin
    def admin_status():
        data = request.get_json(silent=True) or {}
        eid, new = int(data.get("election_id")), (data.get("status") or "").strip()
        conn = get_db()
        try:
            db.set_status(conn, eid, new, actor="admin")
        except KeyError:
            return jsonify({"error": "选举不存在"}), 404
        except lifecycle.InvalidTransition as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "status": new})

    # ---------------- 篡改演练（仅用于现场演示） ----------------
    @app.route("/api/demo/tamper", methods=["POST"])
    def tamper():
        """
        故意篡改一条审计记录的内容，用于演示哈希链的检测能力。

        用一个临时表保存原值即可干净还原（避免 UPDATE 主键带来的 rowid 变化）。
        必须带 token 才可调用，防止被误用。
        """
        data = request.get_json(silent=True) or {}
        if data.get("token") != TAMPER_TOKEN:
            return jsonify({"error": "缺少有效的演示 token"}), 403
        conn = get_db()
        if data.get("restore"):
            row = conn.execute("SELECT * FROM tamper_backup LIMIT 1").fetchone()
            if row is None:
                return jsonify({"ok": False, "message": "没有可还原的篡改记录"})
            conn.execute(
                "UPDATE audit_log SET op=?, payload=? WHERE seq=?",
                (row["op"], row["payload"], row["seq"]),
            )
            conn.execute("DELETE FROM tamper_backup")
            conn.commit()
            ok, bad, msg = db.verify_audit(conn)
            return jsonify({"ok": True, "restored_seq": row["seq"], "chain_ok": ok, "message": msg})

        target = conn.execute(
            "SELECT * FROM audit_log WHERE op='ballot.cast' ORDER BY seq LIMIT 1"
        ).fetchone()
        if target is None:
            return jsonify({"ok": False, "message": "没有可篡改的投票记录"})

        conn.execute("DROP TABLE IF EXISTS tamper_backup")
        conn.execute("CREATE TABLE tamper_backup AS SELECT * FROM audit_log WHERE seq=?", (target["seq"],))
        payload = json.loads(target["payload"])
        payload["tampered_by"] = "演示：攻击者修改了这条记录"
        conn.execute(
            "UPDATE audit_log SET op=?, payload=? WHERE seq=?",
            ("ballot.cast.TAMPERED", json.dumps(payload, ensure_ascii=False, sort_keys=True), target["seq"]),
        )
        conn.commit()
        ok, bad, msg = db.verify_audit(conn)
        return jsonify(
            {
                "ok": True,
                "tampered_seq": target["seq"],
                "chain_ok": ok,
                "first_bad_seq": bad,
                "message": msg,
            }
        )

    # ---------------- 错误处理 ----------------
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "接口不存在"}), 404
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "服务器内部错误"}), 500

    return app


def bootstrap(app: Flask) -> dict:
    """确保数据库存在并有演示数据，且每个进行中的选举都留有可投票的选民。"""
    with app.app_context():
        conn = db.connect(app.config["DB_PATH"])
        db.migrate(conn)
        master = crypto.load_or_create_secret(app.config["SECRET_PATH"])
        key = crypto.derive_key(master, "ballot-master")
        created = False
        if not seed_module.is_seeded(conn):
            info = seed_module.seed(conn, key)
            created = True
        else:
            info = {}
        # 幂等补齐：保证至少有 MIN_AVAILABLE_VOTERS 名未投票选民可用于现场测试
        topped = seed_module.top_up_voters(conn)
        conn.close()
    return {"seeded": created, "topped_up": topped, **info}


app = create_app()

if __name__ == "__main__":
    result = bootstrap(app)
    port = int(os.environ.get("PORT", "8767"))
    print("=" * 64)
    print(" 选举管理与投票系统 — COMP 3500SEF / 8500SEF")
    print("=" * 64)
    if result.get("seeded"):
        print(" ✔ 已生成演示数据集（4 场选举 / 190 名选民 / 预投选票）")
    else:
        print(" ✔ 使用已有数据库")
    print(f" 访问地址: http://localhost:{port}")
    print(" 管理员: admin / admin123    选民 PIN: 1234")
    print("=" * 64)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
