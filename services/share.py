# -*- coding: utf-8 -*-
"""分享会话生命周期（E2 / PRD 矩阵 S8）—— 从生产 App 类逐字节平移。

来源（生产 .pyw 只读基准）：
  App._new_share_dir          L7290
  App._version_share_name     L7313（内嵌 _ver_seq_no 口径 L9604 平移为纯函数）
  App._materialize_share      L7327
  App._clear_share_dir        L7352（实调 Store._cleanup_share_dir(0)）
  App._sweep_share            L7361（实调 Store._cleanup_share_dir(max_age)）
  App._on_drag_end 的 20s 定时 L7417（after→注入的 after 回调）

关键语义（全部保留，禁止"顺手优化"）：
  · 一次拖拽一个会话子目录 <库>/work/share/<time>_<pid>_<seq> —— 避开
    20s 窗口内同名被改 (2) 的历史 bug（R15）；
  · 同一次多选里真重名才加序号，绝不覆盖已有文件；
  · 拖完 20s 才 sweep(20)，最近的会话目录原样留着（drop 后延迟拷贝竞态）；
  · 连续两轮拖出只保留最后一个定时器（_share_after_id 口径）；
  · 清理真正干活的是 Store._cleanup_share_dir —— 本模块绝不自写删除逻辑。
定时器不内建：controller 注入 after(delay_ms, fn)（QTimer 版）；测试注入
虚拟时钟，保证 20s 竞态可编程验证（矩阵 E2「锁屏敏感=否」）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from store import _copy2_writable


def ver_seq_no(meta: dict, ver_id: str) -> int:
    """按提交时间正序算 vN（口径同生产 _ver_seq_no L9604 / _render_versions）。"""
    versions = meta.get("versions", []) or []
    chrono = sorted(versions, key=lambda v: str(v.get("time") or ""))
    for i, v in enumerate(chrono):
        if v.get("id") == ver_id:
            return i + 1
    return len(chrono) or 1


class ShareSessions:
    """一次拖拽 = 一个临时目录；20s 延迟清理；定时器由调用方注入。"""

    def __init__(self, store, after=None) -> None:
        """store: Store 实例；after: fn(delay_ms, fn)（None 则无定时器）。"""
        self._store = store
        self._after = after
        self._share_seq = 0
        self._share_cur: Path | None = None
        self._share_after_id: int | None = None
        self._after_seq = 0

    # ---------- 目录 ----------
    def new_share_dir(self) -> Path:
        """为**这一次拖拽**开一个新的临时目录 <版本库>/work/share/<会话id>。"""
        self._share_seq += 1
        sid = f"{int(time.time())}_{os.getpid()}_{self._share_seq}"
        d = self._store.work_dir / "share" / sid
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._share_cur = d
        return d

    # ---------- 命名与物化 ----------
    def version_share_name(self, meta: dict, ver: dict) -> str:
        """拖出的文件名：<词干>_v<N><后缀>（N 口径同版本区列表）。"""
        name = meta.get("name") or "未命名"
        suffix = Path(name).suffix
        stem = Path(name).stem or "未命名"
        return f"{stem}_v{ver_seq_no(meta, ver['id'])}{suffix}"

    def materialize_share(self, pairs) -> list[str]:
        """把 [(meta, ver), ...] 落成真实文件，返回绝对路径列表。"""
        out: list[str] = []
        d = self.new_share_dir()
        for meta, ver in pairs:
            try:
                src = self._store.version_file(meta, ver)
            except (OSError, FileNotFoundError):
                continue
            want = self.version_share_name(meta, ver)
            target = d / want
            n = 2
            while target.exists():
                target = d / f"{Path(want).stem}({n}){Path(want).suffix}"
                n += 1
            try:
                _copy2_writable(src, target)
            except OSError:
                continue
            out.append(str(target))
        return out

    # ---------- 清理 ----------
    def clear_share_dir(self) -> None:
        """整片清空拖出临时目录（退出清 / 启动兜底清）。"""
        self._store._cleanup_share_dir(0)

    def sweep_share(self, max_age: float) -> None:
        """只清比 max_age 秒更旧的拖出会话目录，最近这一次原样留着。"""
        self._store._cleanup_share_dir(max_age)

    # ---------- 拖拽结束挂钩（20s 竞态）----------
    def on_drag_end(self) -> None:
        """拖拽结束：上一轮定时器作废，只留最后这一个（生产 _on_drag_end 口径）。"""
        if self._share_after_id is not None:
            # after 注入方负责真正的取消；这里约定 after(delay, fn) 返回句柄、
            # cancel(handle) 取消。为保持纯逻辑可测，采用「代次」判别：
            # 定时器回调带代次，过期代次不执行。
            pass
        self._after_seq += 1
        seq = self._after_seq
        if self._after is not None:
            self._after(20000, lambda: self._clear_share_dir_later(seq))

    def _clear_share_dir_later(self, seq: int) -> None:
        if seq != self._after_seq:
            return  # 已被新一轮拖出取代（代次过期），什么都不做
        self.sweep_share(20)
