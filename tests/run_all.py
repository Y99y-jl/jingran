"""一条命令跑完全部测试：既有专项探针 + 新的 UI 冒烟。

    QT_QPA_PLATFORM=offscreen <venv>/python.exe tests/run_all.py

每个用例独立进程、独立沙箱库，互不污染。汇总失败时退出码 1，
可直接挂在发版脚本或 CI 上。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

# 顺序：先专项（快），再 UI 冒烟（慢、覆盖面最广）
CASES = [
    ("m35 集成", "m35_integ_probe.py"),
    ("m36 交互", "m36_probe.py"),
    ("m39 回收站", "m39_probe.py"),
    ("m40 行内操作", "m40_probe.py"),
    ("m47 设置/托盘", "m47_probe.py"),
    ("m49 拖拽", "m49_probe.py"),
    ("m50 弹窗", "m50_probe.py"),
    ("m91 暗色", "m91_dark_probe.py"),
    ("m92 页脚", "m92_footer_probe.py"),
    ("m94 对齐", "m94_probe.py"),
    ("m97 分栏拖拽", "m97_sash_probe.py"),
    ("m99 弹窗尺寸", "m99_dialog_probe.py"),
    ("UI 冒烟", "ui_smoke.py"),
]


def summary_line(out: str) -> str:
    """从输出里挑出「N PASS / M FAIL」那一行，作为摘要。"""
    hits = [ln.strip().strip("= ").strip()
            for ln in out.splitlines()
            if "PASS" in ln and "FAIL" in ln and "=" not in ln.strip()[:1]]
    if hits:
        return hits[-1]
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "(无输出)"


def main() -> int:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    rows, failed = [], 0
    t_all = time.time()
    for name, fname in CASES:
        path = HERE / fname
        if not path.is_file():
            rows.append((name, "SKIP", "文件不存在", 0.0))
            continue
        t0 = time.time()
        proc = subprocess.run([PY, str(path)], capture_output=True, text=True,
                              env=env, cwd=str(HERE.parent))
        dt = time.time() - t0
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        if not ok:
            failed += 1
        rows.append((name, "PASS" if ok else "FAIL", summary_line(out), dt))

    print("\n" + "=" * 70)
    print(f"{'用例':<14}{'结果':<6}{'耗时':<8}摘要")
    print("-" * 70)
    for name, state, msg, dt in rows:
        print(f"{name:<14}{state:<6}{dt:>6.1f}s  {msg[:42]}")
    total = time.time() - t_all
    print("-" * 70)
    print(f"合计 {len(rows)} 个用例，失败 {failed} 个，用时 {total:.1f}s")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
