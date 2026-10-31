# -*- coding: utf-8 -*-
"""B1 事件合成状态机（设计 §3.2）—— 纯 Python，可单测。

QML 单 MouseArea 把原始事件（press/move/release/doubleClick）喂给
FileEventSM，状态机返回意图（intents）：
  {"op": "select",     fids:[...]}        应用选择
  {"op": "click",      fid}               单击结算（含点已选集保留的收敛）
  {"op": "external_drag", fids}           → controller.startDragOut
  {"op": "internal_drag", fids}           内部转移（M5 接树）
  {"op": "none"}
语义基准（生产逐条平移，禁止凭直觉重写）：
  · press：未选中行立即选中；点已选集内的行**保留整片选中**（等 release 结算）
  · 位移 < 阈值（PJM_DRAG_PX=4 设计px）→ release 结算单击；
    点已选集保留且无修饰键时 release 收敛为该行（资源管理器习惯，生产
    `_on_file_drag_press` 注释口径）
  · ≥ 阈值 → DRAG_CANDIDATE；拖整片选中（行在选中集内）否则单行
  · 越界判定 `_pointer_outside_root`：客户区外，上边界放宽 34 设计px（陷阱 d）
  · 越界 → external_drag 一次性触发；之后 move 不重复（陷阱 a：QDrag.exec
    模态期间收不到 release，由 dragOutFinished 复位）
  · 双击 = 独立链（第二次 press 重置位移基点，陷阱 e）
  · 回收站行：可选中（红字显示），但不参与拖出（生产 `_on_file_drag_press`
    的 `_trash_row(row)` 排除口径）
"""

from __future__ import annotations

DRAG_THRESHOLD = 4      # PJM_DRAG_PX=4 设计 px（生产 L407；=5 物理 px）
TOP_OVERSHOOT = 34      # 越界判定上放宽（生产 px(34)，L7191 口径）


class FileEventSM:
    """中栏整行事件状态机：IDLE → PRESSED → (CLICK | CANDIDATE)。"""

    IDLE = "IDLE"
    PRESSED = "PRESSED"
    CANDIDATE = "CANDIDATE"
    EXTERNAL = "EXTERNAL"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """回到 IDLE（dragOutFinished / 切换视图时调用——陷阱 a 的复位口）。"""
        self.state = self.IDLE
        self.press_row: str | None = None
        self.press_in_sel: bool = False
        self.press_sel: list[str] = []
        self.x0 = self.y0 = 0
        self.fids_drag: list[str] = []
        self.external_fired = False

    # ---------- 事件入口 ----------
    def press(self, row: str, x: int, y: int, *, ctrl: bool, shift: bool,
              selection: list[str], is_trash: bool,
              select_range,   # fn(anchor_idx, row_idx) -> [fid...]
              row_index: int) -> list[dict]:
        """返回需要立即应用的选择意图。"""
        self.reset()
        self.state = self.PRESSED
        self.press_row = row
        self.press_sel = list(selection)
        self.press_in_sel = row in selection
        # M49：Ctrl 点击要独立结算（取消该行），不能被 release 的「收敛为单行」覆盖
        self.press_ctrl = bool(ctrl)
        self.press_is_trash = is_trash
        self.x0, self.y0 = x, y
        if is_trash:
            # 回收站行：可选中显示，但不参与拖出（生产口径）
            if not ctrl and not shift:
                return [{"op": "select", "fids": [row]}]
            return [{"op": "none"}]
        if ctrl:
            toggled = list(selection)
            if row in toggled:
                toggled.remove(row)
            else:
                toggled.append(row)
            return [{"op": "select", "fids": toggled}]
        if shift:
            return [{"op": "select",
                     "fids": select_range(row_index)}]
        if row in selection:
            # 点已选集保留：不改选择（release 结算收敛——陷阱 b）
            return [{"op": "none"}]
        return [{"op": "select", "fids": [row]}]

    def move(self, x: int, y: int, *, gx: int, gy: int,
             win_x: int, win_y: int, win_w: int, win_h: int) -> list[dict]:
        """move 事件（gx/gy 屏幕坐标，win_* 主窗口客户区屏幕几何）。"""
        if self.state in (self.IDLE, self.EXTERNAL):
            return [{"op": "none"}]
        if self.state == self.PRESSED:
            if self.press_is_trash:
                return [{"op": "none"}]      # 回收站行不参与拖出（生产口径）
            if abs(x - self.x0) < DRAG_THRESHOLD and abs(y - self.y0) < DRAG_THRESHOLD:
                return [{"op": "none"}]
            self.state = self.CANDIDATE
            # 拖整片选中（行在选中集内）否则单行（生产 `_on_file_drag_press`）
            if self.press_in_sel:
                self.fids_drag = [f for f in self.press_sel]
            else:
                self.fids_drag = [self.press_row]
        if self.state == self.CANDIDATE:
            if not self.fids_drag:
                return [{"op": "none"}]
            if self._outside_root(gx, gy, win_x, win_y, win_w, win_h):
                self.state = self.EXTERNAL
                self.external_fired = True
                return [{"op": "external_drag", "fids": list(self.fids_drag)}]
            return [{"op": "internal_drag", "fids": list(self.fids_drag)}]
        return [{"op": "none"}]          # EXTERNAL：已交给 OLE，不再发意图

    def release(self) -> list[dict]:
        """release 结算。候选/外部态不触发单击（陷阱 e 的"当帧 release 不单击"）。"""
        if self.state == self.PRESSED and self.press_row is not None:
            row = self.press_row
            # 点已选集保留：多选 + 无修饰键 + 松手 → 收敛为该行
            if (self.press_in_sel and len(self.press_sel) > 1
                    and not getattr(self, "press_ctrl", False)):
                return [{"op": "select", "fids": [row]},
                        {"op": "click", "fid": row}]
            return [{"op": "click", "fid": row}]
        self.reset()
        return [{"op": "none"}]

    def double_click(self) -> list[dict]:
        """双击：独立于状态机；第二次 press 重置位移基点（陷阱 e）。"""
        self.reset()                     # 重置基点
        if self.press_row is None:
            return [{"op": "none"}]
        return [{"op": "none"}]

    def drag_out_finished(self) -> None:
        """QDrag.exec 返回后由 controller 必发（陷阱 a：模态期收不到 release）。"""
        self.reset()

    @staticmethod
    def _outside_root(gx: int, gy: int, wx: int, wy: int, ww: int, wh: int) -> bool:
        """`_pointer_outside_root` 平移：客户区外，上边界放宽 34 设计 px。"""
        return not (wx <= gx < wx + ww and gy >= wy - TOP_OVERSHOOT and gy < wy + wh)
