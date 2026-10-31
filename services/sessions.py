# -*- coding: utf-8 -*-
"""编辑会话状态机（G1–G8——设计 §1.3；生产 L9493–10000 平移）。

纯逻辑 + 注入式定时器/时钟（可单测）；Qt 零依赖。
生产对拍锚点：on_open_edit_session L9493 / _sig_for L9548 / _session_sig
L9556 / _ensure_edit_poll L9565 / _poll_edit_sessions L9574 /
_exit_edit_sessions_gate L9864 / _restore_edit_sessions L9885 /
_drop_edit_session L9970 / _drop_edit_sessions_for_fid L9977。

口径要点（禁止"顺手优化"）：
  · 副本路径 <库>/work/<fid>/<ver_id>/<原名>（Store.export_edit_copy 承担）
  · 同一 (fid, ver) 会话且副本在 → 复用（不重复导出、不重置基线/skip）
  · 签名：≤300MB sha256；>300MB mtime+size 伪签名（"big:" 前缀）
  · 轮询 2s：mtime+size 快筛 → 变了才算哈希 → skip_sha 跳过已取消版
  · 一次只处理一个 ask（_edit_prompt_busy 口径）
  · 关窗闸门：无变化会话直接删（保持 work/ 干净）；有变化 → pending
"""

from __future__ import annotations

import time
from datetime import datetime as _dt
from pathlib import Path

from store import _safe_sha256

EDIT_POLL_MS = 2000           # 生产 L9490
EDIT_HASH_MAX = 300 * 1024 * 1024   # 生产 L9491


class EditSessions:
    """编辑会话注册表 + 轮询/闸门决策。定时器经 after 注入（QTimer/虚拟）。"""

    def __init__(self, store, after=None, now=None, on_ask=None) -> None:
        """store: Store；after: fn(delay_ms, fn)（轮询链）；now: 时钟（测试）；
        on_ask: fn(ask)——G3 询问产生即回调（controller → QML 信号）。"""
        self._store = store
        self._after = after
        self._now = now or (lambda: time.monotonic())
        self._on_ask = on_ask
        self.sessions: dict[str, dict] = {}
        self._poll_id = None
        self._prompt_busy = False
        self.asks: list[dict] = []       # 待处理的保存询问（M6 渲染成三选弹窗）
        self.orphans: list[dict] = []    # G4：孤儿会话（P1，M6 弹窗）
        self._poll_seq = 0               # 代次（重启/清空后旧轮询回调作废）

    # ---------------- G1：打开/复用 ----------------
    def open(self, meta: dict, ver: dict | None = None) -> dict:
        """on_open_edit_session 平移（除 os.startfile/弹窗——controller 承担）。

        返回 {ok, key, path, reused}；失败 {ok: False, reason}。
        """
        if ver is None:
            ver = self._store.latest_version(meta)
        if ver is None:
            return {"ok": False, "reason": "该文件没有任何版本"}
        key = f"{meta['fid']}|{ver['id']}"
        sess = self.sessions.get(key)
        reuse = bool(sess) and Path(sess.get("path", "")).is_file()
        if reuse:
            path = Path(sess["path"])
            self.sessions[key] = sess          # 保留基线与 skip（生产口径）
        else:
            try:
                path = self._store.export_edit_copy(meta, ver)
                st_ = path.stat()
                base_sig = self.sig_for(path, st_)
            except (OSError, Exception) as e:   # noqa: BLE001（生产同口径捕获）
                return {"ok": False, "reason": str(e)}
            self.sessions[key] = {
                "fid": meta["fid"], "ver_id": ver["id"],
                "name": meta.get("name", ""), "path": str(path),
                "base_mtime": st_.st_mtime, "base_size": st_.st_size,
                "base_sha256": base_sig, "skip_sha": None,
                "opened_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        self._store.save_edit_sessions(self.sessions)
        self.ensure_poll()
        return {"ok": True, "key": key, "path": str(path), "reused": reuse}

    # ---------------- G2：签名 ----------------
    def sig_for(self, path: Path, st_) -> str:
        """_sig_for 平移：≤300MB sha256；>300MB mtime+size 伪签名（'big:' 前缀）。"""
        if st_.st_size <= EDIT_HASH_MAX:
            return _safe_sha256(path)
        return "big:%d:%d" % (st_.st_mtime_ns, st_.st_size)

    def session_sig(self, s: dict) -> str:
        """_session_sig 平移：快筛未变复用基线；变化才算哈希；OSError 上抛。"""
        st_ = Path(s["path"]).stat()
        if st_.st_mtime == s["base_mtime"] and st_.st_size == s["base_size"]:
            return s["base_sha256"]
        return self.sig_for(s["path"], st_)

    # ---------------- G2 轮询 ----------------
    def ensure_poll(self) -> None:
        if self._poll_id is not None or self._after is None:
            return
        self._poll_seq += 1
        seq = self._poll_seq
        _t = self._after(EDIT_POLL_MS, lambda: self._poll_tick(seq))
        # P2：必须记住这条链（after 可能返回 None，用 True 当哨兵），
        # 否则每次开会话都新起一条 2s 轮询链，越开越多。
        self._poll_id = _t if _t is not None else True

    def _poll_tick(self, seq: int) -> None:
        if seq != self._poll_seq:
            return                      # 代次过期（重启/清空后旧回调作废）
        self._poll_id = None            # 本链已到期，下一次 ensure_poll 才续
        self.poll()
        self.ensure_poll()

    def poll(self) -> list[tuple[str, dict, str]]:
        """_poll_edit_sessions 平移：返回本轮变化 (key, s, sig) 列表，
        并把首个 ask 记入 self.asks（busy 口径：一次只弹一个）。"""
        changed = []
        for key, s in list(self.sessions.items()):
            if s.get("orphan"):
                continue
            try:
                sig = self.session_sig(s)
            except OSError:
                continue                # 副本暂被占用：下轮再看
            if sig == s["base_sha256"]:
                continue
            if s.get("skip_sha") is not None and sig == s["skip_sha"]:
                continue
            s["skip_sha"] = None        # 内容又变了 → 重新可弹
            changed.append((key, s, sig))
        if changed and not self._prompt_busy:
            self._prompt_busy = True
            key, s, sig = changed[0]
            ask = {"key": key, "fid": s.get("fid"), "verId": s.get("ver_id"),
                   "name": s.get("name", ""), "sig": sig,
                   "choices": ["commit", "discard", "cancel"]}
            self.asks.append(ask)
            self._store.save_edit_sessions(self.sessions)
            if self._on_ask is not None:
                self._on_ask(ask)
            # busy 复位由消费方调用 resolve_ask 时进行（生产在弹窗关闭后）
        return changed

    @property
    def prompt_busy(self) -> bool:
        return self._prompt_busy

    # ---------------- G3：三选结算 ----------------
    def resolve_ask(self, key: str, choice: str, new_name: str | None = None) -> dict:
        """保存询问三选（M6 弹窗的消费端；决策逻辑本类承担）。

        commit → commit_next_version（reason 固定口径）+ 基线重置；
        discard → drop（删副本+记录，skip 语义不做——直接丢）；
        cancel → skip_sha 记当前 sig（不再弹，内容再变才重新弹）。
        """
        s = self.sessions.get(key)
        self._prompt_busy = False
        if ask_in_asks(self.asks, key):
            drop_ask(self.asks, key)
        if s is None:
            return {"ok": False, "reason": "会话不存在"}
        if choice == "commit":
            meta = self._store.load_meta(s["fid"])
            ver = next((v for v in (meta.get("versions", []) if meta else [])
                        if v.get("id") == s.get("ver_id")), None)
            if meta is None or ver is None:
                return {"ok": False, "reason": "记录或版本不存在"}
            try:
                self._store.commit_next_version(
                    s["fid"], Path(s["path"]), f"编辑副本提交（{s.get('name', '')}）")
            except (ValueError, OSError) as e:
                return {"ok": False, "reason": str(e)}
            # 基线重置（生产：commit 后基线=新内容）
            try:
                st_ = Path(s["path"]).stat()
                s["base_mtime"], s["base_size"] = st_.st_mtime, st_.st_size
                s["base_sha256"] = self.sig_for(Path(s["path"]), st_)
                s["skip_sha"] = None
            except OSError:
                pass
            self._store.save_edit_sessions(self.sessions)
            return {"ok": True, "action": "committed", "fid": s["fid"]}
        if choice == "discard":
            self.drop(key)
            return {"ok": True, "action": "discarded"}
        # cancel：记 skip（G3 取消语义——同内容不再弹）
        try:
            s["skip_sha"] = self.session_sig(s)
        except OSError:
            s["skip_sha"] = None
        self._store.save_edit_sessions(self.sessions)
        return {"ok": True, "action": "cancelled"}

    # ---------------- G6：关窗闸门 ----------------
    def exit_gate(self) -> tuple[bool, list[dict]]:
        """_exit_edit_sessions_gate 平移。

        返回 (True, []) = 可以关；(False, pending) = 有未提交修改
        （pending 结构同 asks——M6 渲染三选/批处理弹窗；无弹窗时调用方
        拒绝关闭）。无变化会话直接删（保持 work/ 干净）。
        """
        pending = []
        for key, s in list(self.sessions.items()):
            try:
                sig = self.session_sig(s)
            except OSError:
                pending.append({"key": key, "fid": s.get("fid"),
                                "verId": s.get("ver_id"), "name": s.get("name", ""),
                                "sig": None})   # 占用中：保留，重启兜底再问
                continue
            if sig == s["base_sha256"] or s.get("orphan"):
                self.drop(key)
            else:
                pending.append({"key": key, "fid": s.get("fid"),
                                "verId": s.get("ver_id"), "name": s.get("name", ""),
                                "sig": sig})
        if pending:
            self._store.save_edit_sessions(self.sessions)
            return (False, pending)
        self._store.save_edit_sessions(self.sessions)
        return (True, [])

    # ---------------- G7：重启兜底 ----------------
    def restore(self) -> dict:
        """_restore_edit_sessions 平移：sessions.json + work/ 结构反查 +
        逐条校验（副本没了→丢；反查不到→孤儿；未变→静默盯；变了→ask）。"""
        store = self._store
        loaded = store.load_edit_sessions()
        self.sessions = dict(loaded) if isinstance(loaded, dict) else {}
        for s in self.sessions.values():
            s.pop("skip_sha", None)          # 重启即重新问
        known = {f"{s.get('fid')}|{s.get('ver_id')}" for s in self.sessions.values()}
        try:
            wd = store.work_dir
            if wd.is_dir():
                for fid_dir in sorted(wd.iterdir()):
                    if not fid_dir.is_dir():
                        continue
                    for ver_dir in sorted(fid_dir.iterdir()):
                        if not ver_dir.is_dir():
                            continue
                        key = f"{fid_dir.name}|{ver_dir.name}"
                        if key in known:
                            continue
                        files = [p for p in sorted(ver_dir.iterdir())
                                 if p.is_file()]
                        if not files:
                            continue
                        self.sessions[key] = {
                            "fid": fid_dir.name, "ver_id": ver_dir.name,
                            "name": files[0].name, "path": str(files[0]),
                        }
        except OSError:
            pass
        pending, orphans = [], []
        for key in list(self.sessions.keys()):
            s = self.sessions[key]
            fid, ver_id = s.get("fid"), s.get("ver_id")
            if not fid or not ver_id:
                fid, _, ver_id = key.partition("|")
                s["fid"], s["ver_id"] = fid, ver_id
            path = Path(s.get("path") or "")
            meta = store.load_meta(fid)
            has_ver = bool(meta) and any(
                v.get("id") == ver_id for v in (meta.get("versions", []) or []))
            if not path.is_file():
                self.sessions.pop(key, None)
                continue
            if not has_ver:
                orphans.append(key)
                continue
            try:
                st_ = path.stat()
            except OSError:
                self.sessions.pop(key, None)
                continue
            s.setdefault("name", (meta or {}).get("name", ""))
            s.setdefault("base_mtime", st_.st_mtime)
            s.setdefault("base_size", st_.st_size)
            s.setdefault("base_sha256", self.sig_for(path, st_))
            s.setdefault("opened_at", "")
            try:
                sig = self.session_sig(s)
            except OSError:
                self.sessions.pop(key, None)
                continue
            if sig == s["base_sha256"]:
                continue
            pending.append({"key": key, "fid": fid, "verId": ver_id,
                            "name": s.get("name", ""), "sig": sig})
        self.orphans = [{"key": k, **self.sessions[k]} for k in orphans
                        if k in self.sessions]   # G4：孤儿（P1，M6 弹窗）
        self.asks = list(pending)                # 变了 → 逐个再问
        if self.sessions:
            store.save_edit_sessions(self.sessions)
            self.ensure_poll()
        return {"pending": pending, "orphans": self.orphans,
                "kept": len(self.sessions)}

    # ---------------- G8：会话删除联动 ----------------
    def drop(self, key: str) -> None:
        s = self.sessions.pop(key, None)
        if s is None:
            return
        self._store.delete_work_dir(s.get("fid", ""), s.get("ver_id", ""))

    def drop_for_fid(self, fid: str) -> None:
        for key in [k for k in self.sessions if k.split("|", 1)[0] == fid]:
            self.drop(key)

    def stop_polling(self) -> None:
        self._poll_seq += 1       # 代次作废（关窗兜底路径不再续轮询）
        _t, self._poll_id = self._poll_id, None
        _stop = getattr(_t, "stop", None)
        if callable(_stop):
            _stop()               # 生产 QTimer：顺手停掉，别留一条空转链


def ask_in_asks(asks: list[dict], key: str) -> bool:
    return any(a.get("key") == key for a in asks)


def drop_ask(asks: list[dict], key: str) -> None:
    asks[:] = [a for a in asks if a.get("key") != key]
