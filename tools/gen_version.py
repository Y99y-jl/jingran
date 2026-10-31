"""版本号单一真源同步器（发版前跑一次）。

真源：仓库根的 `VERSION`（一行，如 1.1.10）。本脚本把它同步到四处：
  1. `installer/version_info.txt`  —— PyInstaller 的 Windows VERSIONINFO
     （exe 右键属性 → 详细信息 里显示的版本，此前完全没有）
  2. `app_version.py`              —— 运行期读的版本号（设置 → 关于）
  3. `installer/jingran.iss`       —— Inno Setup 的 #define AppVersion
  4. `installer/jingran.iss` 的 [Files] Source 行 —— 指向本次产物目录

第 4 条是为堵一个真实事故：Source 行原来手工改，漏改就会把上一版
产物原样打进安装包（字节数完全相同、只有文件名变了），装完看着是
新版、实际跑的是旧代码。现在由脚本推导，且**幂等**——产物目录尚未
构建时重复运行不会继续递增。

用法：
    python tools/gen_version.py            # 同步（自动推导产物目录）
    python tools/gen_version.py 1.2.0      # 顺手改真源再同步
    python tools/gen_version.py --dist dist_m80   # 显式指定产物目录

推导规则：取 iss 里当前的 dist_mN；若 build_qml/dist_mN 已存在（说明
上一轮已构建过），递增到第一个不存在的编号，避免覆盖历史产物。
"""
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
ISS = ROOT / "installer" / "jingran.iss"
VINFO = ROOT / "installer" / "version_info.txt"
APPVER = ROOT / "app_version.py"
BUILD_ROOT = ROOT / "build_qml"

COMPANY = "井然"
PRODUCT = "井然"
DESC = "井然 · 项目文件管家"
INTERNAL = "jingran"


def next_dist_dir(explicit: str | None = None) -> str:
    """推导本次产物目录名（dist_mNN 形式）。

    幂等：目录已存在才递增；不存在说明还没构建，保持原值。
    """
    if explicit:
        return explicit
    if not ISS.is_file():
        return "dist_m1"
    m = re.search(r"dist_m(\d+)", ISS.read_text(encoding="utf-8"))
    n = int(m.group(1)) if m else 0
    while (BUILD_ROOT / f"dist_m{n}").exists():
        n += 1
    return f"dist_m{n}" if n else "dist_m1"


def sync_iss_dist(dist: str) -> tuple[str, str] | None:
    """把 iss 的 [Files] Source 行改指向 dist 目录。返回 (旧, 新)。"""
    if not ISS.is_file():
        return None
    s = ISS.read_text(encoding="utf-8")
    m = re.search(r'(Source:\s*"\.\.\\build_qml\\)(dist_m\d+)(\\井然\\\*)', s)
    if not m:
        return None
    old = m.group(2)
    if old == dist:
        return (old, dist)
    s2 = s[:m.start(2)] + dist + s[m.end(2):]
    ISS.write_text(s2, encoding="utf-8")
    return (old, dist)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    explicit = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--dist" and i + 2 <= len(sys.argv[1:]):
            explicit = sys.argv[i + 2]
            break

    if args:
        VERSION_FILE.write_text(args[0].strip() + "\n", encoding="utf-8")
    ver = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        print(f"版本号格式不对：{ver!r}（应为 x.y.z）")
        return 2
    major, minor, patch = (int(x) for x in ver.split("."))
    quad = f"{major}.{minor}.{patch}.0"
    build = datetime.date.today().isoformat()

    # 1) PyInstaller VERSIONINFO
    VINFO.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', '{COMPANY}'),
        StringStruct('FileDescription', '{DESC}'),
        StringStruct('FileVersion', '{quad}'),
        StringStruct('InternalName', '{INTERNAL}'),
        StringStruct('LegalCopyright', ''),
        StringStruct('OriginalFilename', '井然.exe'),
        StringStruct('ProductName', '{PRODUCT}'),
        StringStruct('ProductVersion', '{ver}'),
        StringStruct('Comments', 'built {build}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""", encoding="utf-8")

    # 2) 运行期版本模块
    APPVER.write_text(
        f'"""构建期自动生成，勿手改（真源是仓库根 VERSION）。"""\n'
        f'VERSION = "{ver}"\nBUILD_DATE = "{build}"\n',
        encoding="utf-8")

    # 3) Inno Setup 版本
    if ISS.is_file():
        s = ISS.read_text(encoding="utf-8")
        s2 = re.sub(r'#define AppVersion "[^"]*"',
                    f'#define AppVersion "{ver}"', s, count=1)
        if s2 != s:
            ISS.write_text(s2, encoding="utf-8")

    # 4) Inno Setup [Files] Source 指向本次产物目录
    dist = next_dist_dir(explicit)
    changed = sync_iss_dist(dist)

    print(f"已同步版本 {ver} → version_info.txt / app_version.py / jingran.iss")
    if changed:
        old, new = changed
        if old == new:
            print(f"产物目录未变：build_qml/{new}（尚未构建，重复运行不会递增）")
        else:
            print(f"产物目录：build_qml/{old} → build_qml/{new}")
    print()
    print("下一步构建命令（路径已与 iss 对齐）：")
    print(f"  pyinstaller build_pjm_qml.spec --distpath build_qml/{dist} "
          f"--workpath build_qml_work_{dist.replace('dist_', '')} --noconfirm")
    return 0


if __name__ == "__main__":
    sys.exit(main())

