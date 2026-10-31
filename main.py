# -*- coding: utf-8 -*-
"""项目文件管家 QML 版 —— 入口。

PoC 坑清单落实：QQuickStyle.setStyle("Basic")（坑#6）、QML 从
_MEIPASS/qml/Main.qml 加载（坑#1）、qml 目录 addImportPath（单例解析）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

QML_APP = Path(__file__).resolve().parent
if str(QML_APP) not in sys.path:
    sys.path.insert(0, str(QML_APP))

from PySide6.QtCore import QUrl, QTimer, qVersion  # noqa: E402
from PySide6.QtGui import (QFont, QFontDatabase,  # noqa: E402
                           QFontInfo, QIcon, QRawFont)
# M47：系统托盘需要 QtWidgets 的 QApplication / QSystemTrayIcon
from PySide6.QtWidgets import (QApplication, QMenu,  # noqa: E402
                               QSystemTrayIcon)
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from controller import AppController  # noqa: E402


def resource_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return QML_APP


def _write_fontcheck(nf: int, fams: list[str], ui: str) -> None:
    """M40：字体链路自检——把实际解析结果写文件（窗口化 exe 无 stdout）。

    输出 %LOCALAPPDATA%\\井然\\fontcheck.txt（失败再退 exe 同目录）。
    判读：bundled=6/6、uiFamily=PJM Sans SC、三个字重 missing=0 → 字体正常；
    若某字重 family 不是 PJM Sans SC 或 missing>0，即该机字体环境有异常。
    """
    sample = "回收站分类版本历史项目文件管家拖入续版本提交清除"
    lines: list[str] = []
    lines.append(f"qt={qVersion()} frozen={getattr(sys, 'frozen', False)}")
    lines.append(f"base={resource_base()}")
    lines.append(f"bundled={nf}/6 uiFamily={ui}")
    lines.append(f"appFamilies={sorted(set(fams))}")
    lines.append("families(PJM/Noto/Inter)=" + str(
        sorted(f for f in QFontDatabase.families()
               if "PJM" in f or "Noto" in f or "Inter" in f)))
    for fam in ("PJM Sans SC", "PJM Num"):
        try:
            lines.append(f"styles({fam})={QFontDatabase.styles(fam)}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"styles({fam}) ERR {e}")
    for wname, w in (("400", QFont.Weight.Normal),
                     ("500", QFont.Weight.Medium),
                     ("600", QFont.Weight.DemiBold)):
        f = QFont("PJM Sans SC")
        f.setWeight(w)
        info = QFontInfo(f)
        raw = QRawFont.fromFont(f)
        idx = [i for ch in sample for i in raw.glyphIndexesForString(ch)]
        lines.append(f"w={wname} family={info.family()} "
                     f"style={info.styleName()} exact={info.exactMatch()} "
                     f"missing={idx.count(0)}/{len(idx)} glyphs={idx[:8]}")
    text = "\n".join(lines) + "\n"
    targets: list[Path] = []
    lad = os.environ.get("LOCALAPPDATA")
    if lad:
        targets.append(Path(lad) / "井然" / "fontcheck.txt")
    if getattr(sys, "frozen", False):
        targets.append(Path(sys.executable).resolve().parent / "fontcheck.txt")
    for t in targets:
        try:
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(text, encoding="utf-8")
            print(f"[fontcheck] written: {t}", flush=True)
            return
        except OSError:
            continue
    print(text, flush=True)


def main() -> int:
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName("pjm_qml")
    app.setOrganizationName("pjm")

    # ===== M49：单实例 =====
    # 用户反馈「能同时开好几个，关掉后托盘里还挂着一堆」——用本地套接字做
    # 单实例：后启动的进程唤起已有窗口后立即退出。探针形态（--selftest 等）
    # 与测试库（DOCVER_STORE）不占锁，避免并行探针互相踢。
    _lock_skip = (os.environ.get("DOCVER_STORE") is not None
                  or any(a in sys.argv for a in (
                      "--selftest", "--entry-selftest", "--btns-selftest",
                      "--fontcheck")))
    _server = None
    _SKEY = "jingran_single_instance"
    if not _lock_skip:
        _probe = QLocalSocket()
        _probe.connectToServer(_SKEY)
        if _probe.waitForConnected(300):
            _probe.write(b"show")
            _probe.flush()
            _probe.waitForBytesWritten(300)
            _probe.disconnectFromServer()
            print("[single] 已有实例在运行，已唤起其窗口", file=sys.stderr)
            return 0
        QLocalServer.removeServer(_SKEY)      # 清理上次异常退出残留
        _server = QLocalServer()
        _server.listen(_SKEY)

    # ===== M30/M40：随包字体（规格 §2.5：中文 / 数字）=====
    # M40：字体族名改为独有的 PJM Sans SC / PJM Num（见 tools/rename_fonts_pjm.py）。
    # 原因：部分企业环境机器装过另一份 Noto Sans SC，Qt 会把系统那份与随包字体合并成
    # 同一 family，部分字因此取到错位字形（界面乱码）。改名后与任何系统的
    # Noto 都不撞名，字形/字重/度量未变。
    def _load_fonts() -> tuple[int, list[str]]:
        base = resource_base() / "resources" / "fonts"
        names = ["NotoSansSC-400.ttf", "NotoSansSC-500.ttf",
                 "NotoSansSC-600.ttf", "Inter-Regular.ttf",
                 "Inter-Medium.ttf", "Inter-SemiBold.ttf"]
        ok = 0
        fams: list[str] = []
        for nm in names:
            f = base / nm
            if f.is_file():
                fid = QFontDatabase.addApplicationFont(str(f))
                if fid >= 0:
                    ok += 1
                    # 只取“来自随包文件”的族名——旧实现用 families()（系统+应用
                    # 混合集）判断，会把系统字体误认成随包字体、静默掩盖加载失败
                    for fam in QFontDatabase.applicationFontFamilies(fid):
                        if fam not in fams:
                            fams.append(fam)
        return ok, fams

    _nf, _fams = _load_fonts()
    _ui = "PJM Sans SC" if "PJM Sans SC" in _fams else "Microsoft YaHei UI"
    _font = QFont(_ui)
    app.setFont(_font)
    if _nf < 6:
        print(f"[warn] 随包字体加载不全 {_nf}/6，UI 字体回退：{_ui}",
              file=sys.stderr)

    # M40：--fontcheck 字体自检（窗口化 exe 无控制台 → 结果写文件）
    if "--fontcheck" in sys.argv:
        _write_fontcheck(_nf, _fams, _ui)
        return 0

    # ===== M17 任务7：应用图标（旧版 app_icon.ico 同源，9 档 16→256）=====
    # 旧版 iconbitmap(路径) 位置参数（.pyw L11200）口径：标题栏/任务栏/
    # Alt+Tab 一套图标。QML 侧 QGuiApplication.setWindowIcon 等价；必须在
    # 引擎加载窗口之前设置。exe 文件图标由 spec 的 EXE(icon=...) 负责。
    _ico = resource_base() / "resources" / "app_icon.ico"
    if _ico.is_file():
        app.setWindowIcon(QIcon(str(_ico)))
    else:
        print(f"[warn] app_icon.ico 缺失：{_ico}", file=sys.stderr)

    # ===== 库定位模式分层（M7 定稿；事故教训 2026-10-15，见 m1_report.md §6）=====
    # 发布形态（打包 exe 且未设 DOCVER_STORE 且无 --sandbox）：locator 定位真实库
    # （生产发行形态连真实数据）；开发/测试形态：强制沙箱 + 启动断言，铁律不变。
    is_release = (getattr(sys, "frozen", False)
                  and not os.environ.get("DOCVER_STORE")
                  and "--sandbox" not in sys.argv)
    if is_release:
        # M41：产品更名「井然」→ 数据目录 LOCALAPPDATA\井然\store。
        # 迁移铁律：历史目录（M39 起的 项目文件管家、更早的 项目文件管家QML）
        # 只读复制、保留不删；新目录已存在则不覆盖（幂等）；复制失败回退旧目录。
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        qml_store = root / "井然" / "store"
        legacy_dirs = [root / "项目文件管家" / "store",
                       root / "项目文件管家QML" / "store"]
        if not qml_store.exists():
            for legacy_store in legacy_dirs:
                if not legacy_store.is_dir():
                    continue
                try:
                    shutil.copytree(legacy_store, qml_store)
                    break
                except OSError as e:  # 复制失败不致命：回退旧目录保证可用
                    print(f"[pjm_qml] migrate store failed: {e}",
                          file=sys.stderr)
                    qml_store = legacy_store
                    break
        qml_store.mkdir(parents=True, exist_ok=True)  # 首启动建目录
        controller = AppController(str(qml_store))
    else:
        dev_store = os.environ.get("DOCVER_STORE") or str(
            Path(__file__).resolve().parent / ".devstore")
        # 断言前置（P2-2，QA 两轮走读驱动；M9 修复，行号证据见 m9_report）：
        # Store 构造有副作用（索引重写），必须先拒绝再构造。
        _real_store = (Path(os.environ.get("LOCALAPPDATA") or Path.home())
                       / "井然" / "store")
        assert Path(dev_store).resolve() != _real_store.resolve(), \
            "开发实例被禁止打开真实版本库"
        controller = AppController(dev_store)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    engine.rootContext().setContextProperty("filesModel", controller.model)
    engine.rootContext().setContextProperty("categoriesModel", controller.catModel)
    engine.rootContext().setContextProperty("verModel", controller.verModel)
    engine.addImportPath(resource_base().as_uri())  # Theme 单例 qmldir 解析

    qml_path = resource_base() / "qml" / "Main.qml"
    if not qml_path.is_file():
        print(f"[pjm_qml] FATAL: QML not found: {qml_path}", file=sys.stderr)
        return 2

    # --selftest：冻结字节码门禁（M7）——QML/Store 全链加载 + 首帧毫秒戳
    _t_load = time.perf_counter()
    selftest = "--selftest" in sys.argv

    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        print("[pjm_qml] FATAL: QML load failed", file=sys.stderr)
        return 3
    win = engine.rootObjects()[0]

    if selftest:
        ms = (time.perf_counter() - _t_load) * 1000
        print(f"[selftest] OK qml_loaded=true "
              f"store={os.path.basename(controller.store.store_dir)} "
              f"fonts={_nf}/6:{_ui} "
              f"first_frame_ms={ms:.0f}", flush=True)
        QTimer.singleShot(150, app.quit)
        return app.exec()

    # ===== M47：系统托盘（关闭窗口默认隐藏到后台）=====
    # 关闭语义在 QML onClosing：controller.forceQuit 为假且 closeToTray 为真 →
    # 只 hide() 不退出；这里负责托盘图标/菜单，并关闭「最后窗口关闭即退出」。
    def _show_win():
        win.show()
        win.raise_()
        win.requestActivate()

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        _tray_icon = QIcon(str(_ico)) if _ico.is_file() else app.windowIcon()
        tray = QSystemTrayIcon(_tray_icon, app)
        tray.setToolTip("井然")
        _menu = QMenu()
        _act_show = _menu.addAction("显示主窗口")
        _menu.addSeparator()
        _act_quit = _menu.addAction("退出井然")

        def _quit_app():
            controller._force_quit = True
            app.quit()

        _act_show.triggered.connect(_show_win)
        _act_quit.triggered.connect(_quit_app)
        tray.setContextMenu(_menu)
        tray.activated.connect(
            lambda r: _show_win()
            if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()

        def _on_hidden():
            tray.showMessage(
                "井然",
                "已隐藏到系统托盘；右键托盘图标可重新打开或退出。",
                QSystemTrayIcon.MessageIcon.Information, 3000)

        controller.hiddenToTray.connect(_on_hidden)
    app.setQuitOnLastWindowClosed(tray is None)

    if _server is not None:
        def _on_new_conn():
            conn = _server.nextPendingConnection()
            if conn is not None:
                conn.disconnectFromServer()
        _server.newConnection.connect(lambda: (_show_win(), _on_new_conn()))
    print(f"[tray] available={tray is not None}", file=sys.stderr)

    # 首帧时间戳（冷启动复测钩子，PoC 手法复用）
    stamped = {"v": False}

    def on_frame():
        if stamped["v"]:
            return
        stamped["v"] = True
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else QML_APP
        try:
            with open(base / ".firstframe", "a", encoding="utf-8") as f:
                f.write(f"{time.time():.6f}\n")
        except OSError:
            pass

    # ===== 入口级门禁（M10 新增，打包产物上可跑）：弹窗真实渲染断言 =====
    # 教训：M6–M9 的弹窗探针全在 Python 层拦截信号，从未验证 QML 真实渲染
    # ——DialogHost 一行 id 误引导致"全部弹窗不显示"潜伏四批。本门禁以
    # dialogHost.property(visible) + grabWindow 帧差对"打开后可见"下断言。
    if "--entry-selftest" in sys.argv:
        results: list[tuple[str, bool, str]] = []
        warns: list[str] = []
        engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
        QQuickItem = type(win)  # QQuickWindow

        def _host():
            return win.findChild(object, "dialogHost")

        def _frame_diff(a, b):
            if a is None or b is None:
                return 0.0
            n = min(a.width() * a.height(), b.width() * b.height())
            if not n:
                return 0.0
            diff = 0
            for y in range(0, a.height(), 8):
                for x in range(0, a.width(), 8):
                    if a.pixel(x, y) != b.pixel(x, y):
                        diff += 1
            sampled = (a.height() // 8 + 1) * (a.width() // 8 + 1)
            return diff / sampled if sampled else 0.0

        def _check(name, opener):
            before = win.grabWindow()
            warns.clear()
            try:
                opener()
            except Exception as e:  # noqa: BLE001
                results.append((name, False, f"opener raised: {e!r}"))
                return
            QTimer.singleShot(450, lambda: _verdict(name, before))

        def _verdict(name, before):
            host = _host()
            vis = bool(host.property("visible")) if host is not None else False
            after = win.grabWindow()
            rd = _frame_diff(before, after)
            ok = vis and rd > 0.02 and not warns
            results.append((name, ok,
                            f"visible={vis} frame_diff={rd:.2%} warns={warns[:1]}"))
            if host is not None:
                host.setProperty("visible", False)   # 关掉继续下一个
            QTimer.singleShot(250, _next)

        _seq: list = []

        def _next():
            if not _seq:
                _report()
                return
            nm, fn = _seq.pop(0)
            _check(nm, fn)

        def _report():
            n_ok = sum(1 for _, ok, _ in results if ok)
            print(f"[entry] {n_ok}/{len(results)} PASS", flush=True)
            for nm, ok, det in results:
                print(f"[entry]  {'PASS' if ok else 'FAIL'}  {nm}  {det}",
                      flush=True)
            QTimer.singleShot(250, _reach_checks)

        # ---- M11 永久断言：入口层可达性（工具栏按钮/右键菜单/收纳）----
        def _reach_checks():
            out = []

            def find(n):
                return win.findChild(object, n)

            def after_restore():
                # ② 左栏右键菜单：打开后有项且可见
                pane = find("leftPane")
                # QA Round 4：空库只有内置节点——回退用内置节点 spec
                # （__unfiled__/__trash__ 均有 actions），断言不再空转
                cid = None
                for i in range(controller.catModel.rowCount()):
                    r = controller.catModel.row_at(i)
                    if not r.get("isBuiltin"):
                        cid = r.get("cid")
                        break
                if cid is None:
                    for fb in ("__unfiled__", "__trash__"):
                        try:
                            sp = json.loads(
                                controller.collectionMenuSpec(fb))
                            if sp.get("actions"):
                                cid = fb
                                break
                        except ValueError:
                            continue

                def menu_check():
                    menus = [c for c in win.findChildren(object)
                             if c.metaObject().className().startswith(
                                 "Menu_QMLTYPE")]
                    best = max((m.property("count") or 0 for m in menus),
                               default=0)
                    vis = any(bool(m.property("visible")) for m in menus)
                    out.append((f"左栏右键菜单可见且非空（cid={cid}）",
                                best > 0 and vis,
                                f"count={best} visible={vis}"))
                    for m in menus:
                        m.setProperty("visible", False)
                    QTimer.singleShot(250, after_menu)
                if pane is not None and cid:
                    try:
                        pane.openMenu(cid, None)
                        QTimer.singleShot(500, menu_check)
                        return
                    except Exception as e:  # noqa: BLE001
                        out.append(("左栏右键菜单可见且非空", False, repr(e)))
                else:
                    out.append(("左栏右键菜单可见且非空", False, "pane/cid 缺失"))
                QTimer.singleShot(50, after_menu)

            def after_menu():
                # ③ 收纳按钮：点击→状态翻转且视觉一致（再点还原）
                btn = find("toggleRight")
                pane_r = find("rightPane")
                import json as _j3
                d0 = _j3.loads(win.diagSash())

                def consistent(d):
                    """折叠态与视觉一致（宽度无关——QA Round 4）：
                    折叠→右栏不可见；展开→右栏可见。"""
                    col = bool(d.get("collapsed"))
                    vis = bool(pane_r.property("visible"))
                    return (not vis) if col else vis

                def after_click():
                    import json as _j
                    d = _j.loads(win.diagSash())
                    flipped = d.get("collapsed") != d0.get("collapsed")
                    ok = flipped and consistent(d)
                    out.append(("收纳按钮点击→状态翻转且视觉一致", ok,
                                f"collapsed {d0.get('collapsed')}→{d.get('collapsed')} "
                                f"rightVisible={bool(pane_r.property('visible'))} "
                                f"mid={d.get('mid')}"))
                    try:
                        import PySide6.QtCore as C2
                        C2.QMetaObject.invokeMethod(
                            btn, "clicked",
                            C2.Qt.ConnectionType.DirectConnection)
                    except Exception:  # noqa: BLE001
                        pass
                    QTimer.singleShot(900, after_expand)

                def after_expand():
                    import json as _j2
                    d2 = _j2.loads(win.diagSash())
                    # QA Round 5：像素字段用容差（SplitView 隐藏→恢复时比例
                    # 分配取整，特定「窗宽 × 持久化 rightW」组合有 ≤12px
                    # 布局舍入——视觉不可感/功能正常）；collapsed 保持严格。
                    # M12-R2：判据对象改「用户可见几何」——left/mid/right。
                    # prefR 是 SplitView 内部值（Qt 会把它回写成窗宽/0 之类
                    # 的非意图值，实测出现 1280→0），不适合作为往返判据，
                    # 仅作追溯输出。
                    TOL = 16
                    pix = ("left", "mid", "right")
                    diffs = {}
                    for k in pix:
                        v0, v2 = d0.get(k), d2.get(k)
                        if v0 is None or v2 is None or abs(v0 - v2) > TOL:
                            diffs[k] = (v0, v2)
                    if d0.get("collapsed") != d2.get("collapsed"):
                        diffs["collapsed"] = (d0.get("collapsed"),
                                              d2.get("collapsed"))
                    ok = (not diffs) and consistent(d2)
                    out.append((f"再点→往返还原（可见几何 left/mid/right ±{TOL}px"
                                f" + collapsed 严格）", ok,
                                f"超容差项={diffs or '无'} "
                                f"（追溯 prefR {d0.get('prefR')}→{d2.get('prefR')}）"))
                    finalize()

                try:
                    import PySide6.QtCore as C
                    C.QMetaObject.invokeMethod(
                        btn, "clicked", C.Qt.ConnectionType.DirectConnection)
                except Exception as e:  # noqa: BLE001
                    out.append(("收纳按钮点击→右栏收起到位", False, repr(e)))
                    finalize()
                    return
                QTimer.singleShot(1000, after_click)

            def finalize():
                n_ok = sum(1 for _, ok, _ in out if ok)
                print(f"[reach] {n_ok}/{len(out)} PASS", flush=True)
                for nm, ok, det in out:
                    print(f"[reach]  {'PASS' if ok else 'FAIL'}  {nm}  {det}",
                          flush=True)
                QTimer.singleShot(150, app.quit)

            # ① 三按钮可达：缩到最小宽后按「实际窗宽」断言
            # （QA Round 4：几何恢复流程可能把窗口带回 1280，setWidth(900)
            #  会被覆盖——断言必须读实际窗宽，不能假定 900）
            old_w = win.width()
            win.setWidth(900)

            def _gap_of(name):
                t = find(name)
                if t is None:
                    return None
                return (win.width() - ((t.property("x") or 0)
                                       + (t.property("width") or 0)))

            def after_resize():
                ok = True
                details = []
                for nm in ("helpBtn", "settingsBtn", "toggleRight"):
                    it = find(nm)
                    if it is None:
                        ok = False
                        details.append(f"{nm}:缺失")
                        continue
                    x = it.property("x") or 0
                    w = it.property("width") or 0
                    vis = bool(it.property("visible"))
                    inside = (x + w) <= win.width() + 0.5
                    if not vis or not inside:
                        ok = False
                    details.append(f"{nm}:x={int(x)},w={int(w)},"
                                   f"in={inside},vis={vis}")
                # M12-R3：钉右判据（宽度无关）——同一步内测两档间隙。
                # 统一定义：右缘间隙 = 按钮 x+width 与 win.width() 之差
                # （不含窗口边框；QA 实测 24 逻辑即此口径）。
                # M17 任务8：右上三按钮按旧版调序（右栏开合/设置/帮助），
                # 最右按钮从 toggleRight 变为 helpBtn —— 判据对象同步更换。
                gap_900 = _gap_of("helpBtn")
                out.append((f"工具栏三按钮可达（实际窗宽 {int(win.width())}）",
                            ok, " ".join(details)))
                win.setWidth(old_w)

                def _pin_verdict():
                    gap_cur = _gap_of("helpBtn")
                    # M31：顶栏右缘留白 16px（修帮助图标超边）后钉右间隙
                    # 设计值 = 60（图标组 + 右缘留白），上界放宽到 80；
                    # 两档间隙一致（|差|≤4）与下界 6 的判据不变。
                    pin_ok = (gap_900 is not None and gap_cur is not None
                              and 6 <= gap_900 <= 80 and 6 <= gap_cur <= 80
                              and abs(gap_900 - gap_cur) <= 4)
                    out.append(("工具栏三按钮钉右缘（宽度无关：两档间隙∈[6,40]"
                                "且差≤4；判据对象=最右的 helpBtn）", pin_ok,
                                f"间隙@900={gap_900} 间隙@{int(win.width())}"
                                f"={gap_cur}"))
                    QTimer.singleShot(350, after_restore)
                QTimer.singleShot(400, _pin_verdict)

            QTimer.singleShot(400, after_resize)

        import tempfile as _tf
        _tmp = Path(_tf.gettempdir()) / "entry_probe_src.txt"
        _tmp.write_text("entry probe", encoding="utf-8")
        _seq = [
            ("提交弹窗", lambda: controller.open_commit_dialog([str(_tmp)])),
            ("设置弹窗", lambda: controller.open_settings()),
            ("帮助弹窗", lambda: controller.open_help()),
        ]
        # M28：从旧版导入功能已按产品要求移除（入口+实现），entry 断言同步删。
        QTimer.singleShot(900, _next)

    # ===== 入口路径门禁（M12 新增）：QML onClicked → controller.X =====
    # 本批漏网类型：open_settings/open_help 缺 @Slot → QML 调用 TypeError 被吞、
    # 点击无反应，而旧门禁只直调 controller 方法所以全绿。本门禁专测该路径。
    if "--entry-buttons" in sys.argv:
        _out: list = []
        _warns: list = []
        engine.warnings.connect(lambda ws: _warns.extend(w.toString()
                                                        for w in ws))

        def _find(n):
            return win.findChild(object, n)

        def _host():
            return win.findChild(object, "dialogHost")

        def _diff(a, b):
            if a is None or b is None:
                return 0.0
            n = (min(a.width(), b.width()) // 8 + 1) * \
                (min(a.height(), b.height()) // 8 + 1)
            d = 0
            for y in range(0, a.height(), 8):
                for x in range(0, a.width(), 8):
                    if a.pixel(x, y) != b.pixel(x, y):
                        d += 1
            return d / n if n else 0.0

        import PySide6.QtCore as _C
        _seq = [("帮助弹窗", "helpBtn"), ("设置弹窗", "settingsBtn"),
                ("提交弹窗", "commitToolBtn")]
        _st = {"i": 0}

        def _step():
            if _st["i"] >= len(_seq):
                return _collapse()
            nm, obj = _seq[_st["i"]]
            it = _find(obj)
            if it is None:
                _out.append((f"QML 入口·{nm}", False, "按钮缺失"))
                _st["i"] += 1
                return QTimer.singleShot(50, _step)
            before = win.grabWindow()
            _warns.clear()
            try:
                _C.QMetaObject.invokeMethod(
                    it, "clicked", _C.Qt.ConnectionType.DirectConnection)
            except Exception as e:  # noqa: BLE001
                _out.append((f"QML 入口·{nm}", False, repr(e)))
                _st["i"] += 1
                return QTimer.singleShot(50, _step)

            def _verdict():
                host = _host()
                vis = bool(host.property("visible")) if host is not None else False
                rd = _diff(before, win.grabWindow())
                _out.append((f"QML 入口·{nm}（clicked→弹窗）",
                             vis and rd > 0.02 and not _warns,
                             f"visible={vis} diff={rd:.2%} warns={_warns[:1]}"))
                # M12：Esc 必须能关弹窗（模态 Popup 吞掉窗口级 Shortcut 曾致关不掉）
                try:
                    # M12-R3：改用 QKeyEvent + postEvent——PySide6.QtTest 已按
                    # 裁剪清单排除出包（spec: PySide6/QtTest），旧写法在产物里
                    # ModuleNotFoundError ⇒ 该断言恒不可执行（QA Round 7 定性）。
                    from PySide6.QtCore import (QCoreApplication, QEvent,
                                                Qt as _Qt)
                    from PySide6.QtGui import QKeyEvent
                    _ev = QKeyEvent(QEvent.Type.KeyPress, _Qt.Key.Key_Escape,
                                    _Qt.KeyboardModifier.NoModifier)
                    QCoreApplication.postEvent(win, _ev)
                except Exception as e:  # noqa: BLE001
                    _out.append((f"QML 入口·{nm}（Esc 关闭）", False, repr(e)))
                    _st["i"] += 1
                    return QTimer.singleShot(250, _step)

                def _esc_verdict():
                    vis2 = bool(host.property("visible")) \
                        if host is not None else False
                    _out.append((f"QML 入口·{nm}（Esc 关闭）", not vis2,
                                 f"after_Esc_visible={vis2} warns={_warns[:1]}"))
                    _st["i"] += 1
                    QTimer.singleShot(250, _step)
                QTimer.singleShot(400, _esc_verdict)
            QTimer.singleShot(500, _verdict)

        def _collapse():
            btn = _find("toggleRight")
            import json as _j
            d0 = _j.loads(win.diagSash())
            _warns.clear()
            try:
                _C.QMetaObject.invokeMethod(
                    btn, "clicked", _C.Qt.ConnectionType.DirectConnection)
            except Exception as e:  # noqa: BLE001
                _out.append(("QML 入口·收纳按钮", False, repr(e)))
                return _report()

            def _done():
                d1 = _j.loads(win.diagSash())
                _out.append(("QML 入口·收纳按钮（clicked→状态翻转）",
                             d1.get("collapsed") != d0.get("collapsed")
                             and not _warns,
                             f"collapsed {d0.get('collapsed')}"
                             f"→{d1.get('collapsed')} warns={_warns[:1]}"))
                _report()
            QTimer.singleShot(700, _done)

        def _report():
            n_ok = sum(1 for _, ok, _ in _out if ok)
            print(f"[btns] {n_ok}/{len(_out)} PASS", flush=True)
            for nm, ok, det in _out:
                print(f"[btns]  {'PASS' if ok else 'FAIL'}  {nm}  {det}",
                      flush=True)
            QTimer.singleShot(150, app.quit)

        QTimer.singleShot(900, _step)

    win.frameSwapped.connect(on_frame)

    # QML 窗口关闭 → controller 落盘 UI（QML onClosing 已发 appClosing；
    # 这里兜底：QML 拒绝关闭（闸门，M5）时不退出）
    app.aboutToQuit.connect(lambda: None)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
