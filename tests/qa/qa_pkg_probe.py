# -*- coding: utf-8 -*-
"""QA 终验探针 · 打包成品独立重测（不复用产品自带探针）。

只做：锁屏判定 / 哈希 / selftest ×3 / 冷启动 ×3（spawn→窗口可见，中位）。
铁律：所有运行均注入 DOCVER_STORE 沙箱，绝不打开真实版本库。
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
import tempfile

# 按脚本位置推导仓库根，再取编号最大的构建产物（不写死版本号）
_QA = Path(__file__).resolve().parent.parent.parent
_DISTS = sorted((_QA / "build_qml").glob("dist_m*"),
                key=lambda p: int(p.name.split("m")[-1])) if (_QA / "build_qml").is_dir() else []
EXE = (_DISTS[-1] / "井然" / "井然.exe") if _DISTS else (_QA / "build_qml" / "dist" / "井然" / "井然.exe")
SANDBOX = str(Path(tempfile.gettempdir()) / "jingran-sandbox")
REAL_STORE = Path(tempfile.gettempdir()) / "jingran-real-store-do-not-touch"

out_lines = []


def log(s=""):
    print(s, flush=True)
    out_lines.append(str(s))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ---- 0) 锁屏协议判定（GetSystemMetrics(0)==1920 才允许实机输入实验）----
user32 = ctypes.windll.user32
w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
log(f"[screen] {w}x{h} -> {'UNLOCKED (实机输入实验可做)' if w == 1920 else 'LOCKED/非基线 (锁屏协议：一律记账不硬试)'}")

# ---- 1) 哈希（前后一致性 = Defender 未隔离篡改）----
hash_before = sha256_file(EXE)
log(f"[hash] exe sha256 = {hash_before}")
log(f"[size] exe = {EXE.stat().st_size} B; zip = {(EXE.parents[2] / '项目文件管家QML_安装包.zip').stat().st_size} B; dir = {sum(f.stat().st_size for f in EXE.parent.rglob('*') if f.is_file())} B")

env = dict(os.environ)
env["DOCVER_STORE"] = SANDBOX
assert not env.get("DOCVER_STORE", "") .startswith(str(REAL_STORE)), "safety"


user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = wt.BOOL
user32.PostMessageW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL


def enum_pids_windows(pid: int):
    hwnds = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, wt.LPARAM)
    def cb(hwnd, lparam):
        if hwnd is None:
            return True
        cp = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(cp))
        if cp.value == pid and user32.IsWindowVisible(hwnd):
            hwnds.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return hwnds


def run_cold_start(tag: str) -> float:
    """spawn -> 首个可见窗口，毫秒。之后 WM_CLOSE 优雅关闭，超时强杀。"""
    t0 = time.perf_counter()
    proc = subprocess.Popen([str(EXE)], env=env, cwd=str(EXE.parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t_spawn = time.perf_counter() - t0
    visible_ms = None
    deadline = time.perf_counter() + 30
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            log(f"[{tag}] FAIL 进程提前退出 rc={proc.returncode}")
            return -1.0
        if enum_pids_windows(proc.pid):
            visible_ms = (time.perf_counter() - t0) * 1000
            break
        time.sleep(0.01)
    if visible_ms is None:
        log(f"[{tag}] FAIL 30s 内未见可见窗口")
        proc.kill()
        return -1.0
    # 优雅关闭
    for hwnd in enum_pids_windows(proc.pid):
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        log(f"[{tag}] WARN 10s 未退出已强杀")
    log(f"[{tag}] spawn={t_spawn*1000:.0f}ms spawn->visible={visible_ms:.0f}ms rc={proc.returncode}")
    return visible_ms


def run_selftest(i: int) -> float:
    t0 = time.perf_counter()
    r = subprocess.run([str(EXE), "--selftest"], env=env, cwd=str(EXE.parent),
                       capture_output=True, text=True, timeout=60)
    ms = (time.perf_counter() - t0) * 1000
    so = (r.stdout or "").strip()
    se = (r.stderr or "").strip()
    log(f"[selftest#{i}] rc={r.returncode} wall={ms:.0f}ms stdout={so!r} stderr={se!r}")
    return ms


# ---- 2) selftest ×3（打包产物上的冻结字节码门禁，独立复跑）----
log("")
for i in range(1, 4):
    run_selftest(i)

# ---- 3) 冷启动 ×3（spawn→窗口可见）----
log("")
cold = []
for i in range(1, 4):
    ms = run_cold_start(f"cold#{i}")
    if ms > 0:
        cold.append(ms)
    time.sleep(1.0)
if cold:
    cold_sorted = sorted(cold)
    median = cold_sorted[len(cold_sorted) // 2] if len(cold_sorted) % 2 else (cold_sorted[len(cold_sorted)//2 - 1] + cold_sorted[len(cold_sorted)//2]) / 2
    log(f"[cold] median = {median:.0f}ms  (n={len(cold)}, gate ≤1500ms -> {'PASS' if median <= 1500 else 'FAIL'})")

# ---- 4) 哈希复检（Defender 存活性）----
hash_after = sha256_file(EXE)
log(f"[hash-after] {'UNCHANGED (存活，未被隔离/篡改)' if hash_after == hash_before else 'CHANGED!! ' + hash_after}")

Path(__file__).with_name("qa_pkg_probe_out.txt").write_text("\n".join(out_lines), encoding="utf-8")
log("[done] 原始输出已存 tests/qa/qa_pkg_probe_out.txt")
