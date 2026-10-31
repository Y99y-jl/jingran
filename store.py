# -*- coding: utf-8 -*-
"""项目文件管家 · 存储层（store.py）

由 tools/extract_store.py 从生产 项目文件管家.pyw 做 AST 依赖闭包机械切片生成。
除本文件头外，全部内容为生产源码逐字节切片（等价三证之②可审计）。
本模块零 tkinter / 零 PySide6 依赖（等价三证之①静态断言）。
"""
from datetime import datetime

from pathlib import Path

import hashlib

import json

import os

import re

import shutil

import stat

import tempfile

import time

import zipfile


DEFAULT_STORE_DIR = Path.home() / "Documents" / "项目文件库"
OLD_STORE_DIR = Path.home() / "Documents" / "文档版本库"
LOCATOR_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "项目文件管家"
LOCATOR_FILE = LOCATOR_DIR / "location.json"
INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
def _is_relative(path, root):
    """安全判断 path 是否位于 root 之下（兼容无 is_relative_to 的场景）。"""
    if root is None:
        return False
    try:
        return Path(path).is_relative_to(root)
    except AttributeError:
        try:
            Path(path).relative_to(root)
            return True
        except ValueError:
            return False
    except ValueError:
        return False
def _safe_sha256(path):
    """只读取原始字节计算 sha256（不解析文件内容，只读取原始字节）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()
def _copy2_writable(src, dest):
    """字节级 copy2 复制，并确保目标文件可写。

    背景：copy2 会连元数据一起保真复制（不解析内容），但也连带了"只读"
    属性——微信等来源的只读文件入库/导出后依然只读，无法直接编辑。
    故在落盘后清除只读位。若目标已存在且只读（旧库遗留数据），
    先解除其只读再覆盖，避免 copy2 打开目标时报 PermissionError。
    清除失败不致命（如目标在只读介质上），静默跳过保持原有健壮性。
    """
    dest = Path(dest)
    if dest.exists():
        try:
            os.chmod(dest, 0o666)
        except OSError:
            pass
    shutil.copy2(src, dest)
    try:
        st = os.lstat(dest)
        if not (st.st_mode & stat.S_IWRITE):
            os.chmod(dest, st.st_mode | stat.S_IWRITE)
    except OSError:
        pass
def _read_locator():
    """读取位置指针文件里的 store_dir 字段，返回 Path。

    文件不存在 / 解析失败 / 字段缺失 / 类型非法一律静默返回 None，
    绝不抛异常。所有"读取内容"仅限本程序自己写的 json。
    """
    try:
        with open(LOCATOR_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("store_dir")
    if not val or not isinstance(val, str):
        return None
    return Path(val)
def _write_locator(store_dir):
    """把 store_dir 原子写入位置指针文件（先 .tmp 再 os.replace）。

    失败抛 OSError，由调用方捕获；不会留下半截文件。
    """
    LOCATOR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(LOCATOR_FILE) + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"store_dir": str(Path(store_dir))}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, LOCATOR_FILE)
    finally:
        if tmp.exists():
            try:
                os.remove(tmp)
            except OSError:
                pass
def _resolve_store_dir(explicit=None):
    """解析版本库位置，优先级：显式参数 > 环境变量 > 指针文件 > 默认。"""
    if explicit:
        return Path(explicit)
    env = os.environ.get("DOCVER_STORE")
    if env:
        return Path(env)
    loc = _read_locator()
    if loc is not None:
        return loc
    return DEFAULT_STORE_DIR
class Store:
    def __init__(self, store_dir=None):
        self.locator_warning = None
        explicit = store_dir is not None or bool(os.environ.get("DOCVER_STORE"))
        self.store_dir = _resolve_store_dir(store_dir)
        # 健壮性：指针文件存在但目标位置不可用（如已拔掉的 U 盘）→ 回退默认库
        if not explicit:
            loc = _read_locator()
            if loc is not None and self.store_dir == loc:
                try:
                    self.store_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    self.locator_warning = (
                        f"配置的版本库位置当前不可用：{loc}（{e}）；"
                        f"已临时改用默认位置：{DEFAULT_STORE_DIR}")
                    self.store_dir = DEFAULT_STORE_DIR
            elif loc is None and LOCATOR_FILE.exists():
                # 指针文件损坏/字段缺失：静默回退默认库，但提示用户
                self.locator_warning = (
                    f"位置指针文件无法识别（{LOCATOR_FILE}）；"
                    f"已改用默认位置：{DEFAULT_STORE_DIR}")
        # 自动迁移旧「文档版本库」
        if (not explicit and not self.store_dir.exists()
                and OLD_STORE_DIR.exists()
                and (OLD_STORE_DIR / "config.json").exists()):
            try:
                shutil.copytree(OLD_STORE_DIR, self.store_dir)
            except OSError:
                pass
        self.files_dir = self.store_dir / "files"
        self.config_file = self.store_dir / "config.json"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.config = self._load_json(self.config_file, {})
        self.config.setdefault("collections", [])
        self.config.setdefault("files", [])
        self.config.setdefault("ui", {})
        self._col_parent = {}
        self._col_name = {}
        # 分类结构补默认值 / 脏数据兜底（向后兼容旧格式）
        self._ensure_collections()
        # 启动时清理超过 1 小时的临时对比副本
        self._cleanup_temp_copies()
        # R14：清掉上次异常退出/强杀留下的拖出临时文件（正常退出由 on_close 收）
        self._cleanup_share_dir()
        # R6：旧格式（v5：collections 多分类 + 磁盘路径语义）一次性迁移。
        # 只改写 config.json；磁盘 meta 的旧字段由 load_meta 懒清理（见下），
        # 因此回滚 = 用 config_v5_backup.json 还原 config.json 即可。
        self.migrated_v6 = self._migrate_v5_to_v6()
        # 校验索引与磁盘一致性，必要时全量重建
        self._ensure_index()

    # ---------- 基础 ----------
    @staticmethod
    def _load_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
        # A2：主文件损坏/不可读 → 依次尝试同目录 .bak（_save_json 每次覆盖前
        # 都会留一份）。meta.json 没有 .bak：open 抛 OSError → 自然回落 default，
        # 对 meta 调用点（_load_meta / _disk_fids）行为完全兼容。
        try:
            with open(str(path) + ".bak", "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return default
        # 兜底结构校验：本方法的两个调用点（config.json / meta.json）都要求 dict
        return data if isinstance(data, dict) else default

    @staticmethod
    def _save_json(path, data):
        """
        原子写入：先写 .tmp → 备份旧文件为 .bak → os.replace 覆盖。
        任何失败抛出 OSError，由调用方捕获提示；不会留下半截文件。
        """
        path = Path(path)
        tmp = Path(str(path) + ".tmp")
        bak = Path(str(path) + ".bak")
        try:
            if path.exists():
                try:
                    shutil.copy2(path, bak)
                except OSError:
                    pass
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())   # A2：落盘到介质，断电也不留空/半文件
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---------- 文件库迁移 ----------
    def migrate_store_dir(self, new_dir, progress=None):
        """把整个版本库迁移到 new_dir。

        - 前置校验不通过一律抛 ValueError（附中文原因）；
        - 复制为纯字节级（_copy2_writable），绝不解析任何文件；
        - 校验（文件数 / config.json / files 子目录集合）通过后写指针并切换；
        - 失败则清掉半成品目录，旧库与指针保持不动；
        - 绝不删除旧目录，由 UI 提示用户自行确认后清理。

        返回 (new_dir, old_dir)。

        注意：界面上的迁移入口已按用户要求移除，本方法保留为 Store 层
        能力 —— 需要时可写脚本调用，或将来恢复界面入口时直接复用。
        """
        new_dir = Path(new_dir)
        old_dir = self.store_dir

        # ---- 前置校验 ----
        try:
            same = new_dir.resolve() == old_dir.resolve()
        except OSError:
            same = new_dir == old_dir
        if same:
            raise ValueError("目标位置与当前版本库位置相同")
        if _is_relative(old_dir, new_dir) or _is_relative(new_dir, old_dir):
            raise ValueError("目标目录不能是当前版本库的子目录，"
                             "也不能包含当前版本库")
        if new_dir.exists():
            try:
                entries = list(new_dir.iterdir())
            except OSError as e:
                raise ValueError(f"目标目录无法访问：{e}")
            if entries:
                if ((new_dir / "config.json").exists()
                        and (new_dir / "files").exists()
                        and any((new_dir / "files").iterdir())):
                    raise ValueError("目标目录看起来是另一个版本库，请换一个空目录")
                raise ValueError("目标目录不是空目录，请换一个空目录")

        # ---- 收集源库文件清单（跳过 __pycache__ 与 work 编辑工作目录）----
        # R7：work/ 是编辑会话工作目录（含未提交副本），不参与迁移校验；
        # 迁移后旧库 work 里若有未提交修改会留在旧库，属可接受边界。
        src_files = []
        for root, dirs, files in os.walk(old_dir):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "work")]
            for fn in files:
                src_files.append(Path(root) / fn)
        total = len(src_files)

        # ---- 执行复制 + 校验（失败即清理半成品）----
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            done = 0
            for fp in src_files:
                rel = fp.relative_to(old_dir)
                dest = new_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                _copy2_writable(fp, dest)
                done += 1
                # 每 20 个或最后一批回调一次，避免回调过频
                if progress is not None and (done % 20 == 0 or done == total):
                    progress(done, total, str(rel))
            if progress is not None and total == 0:
                progress(0, 0, "")

            # ---- 校验 ----
            new_files = []
            for root, dirs, files in os.walk(new_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "work")]
                new_files.extend(files)
            if len(new_files) != total:
                raise OSError(
                    f"迁移后文件数不一致：源 {total} / 目标 {len(new_files)}")
            cfg = self._load_json(new_dir / "config.json", None)
            if not isinstance(cfg, dict):
                raise OSError("目标目录的 config.json 无法解析")
            src_sub = {p.name for p in (old_dir / "files").iterdir()
                       if p.is_dir()} if (old_dir / "files").exists() else set()
            new_sub = {p.name for p in (new_dir / "files").iterdir()
                       if p.is_dir()} if (new_dir / "files").exists() else set()
            if src_sub != new_sub:
                raise OSError("目标目录 files/ 的子目录与源库不一致")

            # ---- 写位置指针（原子）----
            _write_locator(new_dir)
        except Exception:
            shutil.rmtree(new_dir, ignore_errors=True)
            raise

        # ---- 切换内部路径 ----
        self.store_dir = new_dir
        self.files_dir = new_dir / "files"
        self.config_file = new_dir / "config.json"
        self.config = self._load_json(self.config_file, {})
        self.config.setdefault("collections", [])
        self.config.setdefault("files", [])
        self.config.setdefault("ui", {})
        self._col_parent = {}
        self._col_name = {}
        self._ensure_collections()
        self._ensure_index()
        return new_dir, old_dir

    # ---------- 临时副本清理 ----------
    @staticmethod
    def _cleanup_temp_copies():
        """清理超过 1 小时的临时副本（对比用 pjm_cmp_ / 库中副本用 pjm_lib_）。"""
        try:
            base = Path(tempfile.gettempdir())
            now = time.time()
            for pat in ("pjm_cmp_*", "pjm_lib_*"):
                for d in base.glob(pat):
                    try:
                        if d.is_dir() and now - d.stat().st_mtime > 3600:
                            shutil.rmtree(d, ignore_errors=True)
                    except OSError:
                        pass
        except OSError:
            pass

    # ---------- 分类（支持无限层级） ----------
    def _cleanup_share_dir(self, max_age=0):
        """R14：清掉 <版本库>/work/share 里拖出分享留下的临时文件。

        R15 起 share/ 下**每次拖拽一个会话子目录**（见 App._new_share_dir），
        所以这里按整个会话目录回收，而不是逐个文件删。

        max_age > 0 时只清比它更旧的会话 —— 刚拖出的那一份要留着，目标程序
        （聊天工具/SVN 客户端）常常在 drop 返回之后才真正去拷那个文件。

        只动 share/ 这一个子目录 —— work/ 下正在进行的编辑会话绝不触碰。
        正常退出由 App.on_close 收；异常退出/强杀会留残渣，故启动时兜底一次。
        """
        try:
            d = self.work_dir / "share"
            if not d.is_dir():
                return
            now = time.time()
            for it in list(d.iterdir()):
                try:
                    if max_age and now - it.stat().st_mtime < max_age:
                        continue
                    if it.is_dir():
                        shutil.rmtree(it, ignore_errors=True)
                    else:              # 兼容 R14 遗留在 share/ 根下的散落文件
                        it.unlink()
                except OSError:
                    pass
            try:                       # 空了就顺手收掉 share/，别在 work/ 留空壳
                next(d.iterdir())
            except StopIteration:
                try:
                    d.rmdir()
                except OSError:
                    pass
        except OSError:
            pass
    def collections(self):
        return self.config.get("collections", [])

    def _rebuild_col_cache(self):
        """重建 {cid: parent} 与 {cid: name} 缓存，避免遍历时线性扫描。"""
        self._col_parent = {}
        self._col_name = {}
        for c in self.collections():
            if isinstance(c, dict) and c.get("id"):
                self._col_parent[c["id"]] = c.get("parent")
                self._col_name[c["id"]] = c.get("name", "")

    def _ensure_collections(self):
        """补齐/修正分类结构：缺 parent 补 None，parent 悬空修正为 None。

        兼容旧数据（无 parent 字段）；有修正才落盘。
        """
        colls = self.config.get("collections", [])
        if not isinstance(colls, list):
            colls = []
        ids = {c.get("id") for c in colls
               if isinstance(c, dict) and c.get("id")}
        changed = False
        for c in colls:
            if not isinstance(c, dict):
                continue
            if "parent" not in c:
                c["parent"] = None
                changed = True
            if c.get("parent") is not None and c.get("parent") not in ids:
                c["parent"] = None
                changed = True
        self.config["collections"] = colls
        self._rebuild_col_cache()
        if changed:
            try:
                self._save_json(self.config_file, self.config)
            except OSError:
                pass

    def collection_children(self, cid):
        """直接子分类列表（cid 为 None 时返回全部一级分类）。"""
        return [c for c in self.collections() if c.get("parent") == cid]

    def collection_descendants(self, cid):
        """全部子孙 cid 列表（递归，带循环保护）。"""
        result = []
        seen = set()
        stack = list(self.collection_children(cid))
        while stack:
            c = stack.pop()
            child = c.get("id")
            if not child or child in seen:
                continue
            seen.add(child)
            result.append(child)
            stack.extend(self.collection_children(child))
        return result

    def collection_path(self, cid):
        """返回从一级到该分类的名称列表，如 ["特医注册", "果胶调研"]。"""
        path = []
        seen = set()
        cur = cid
        while cur is not None and cur in self._col_name and cur not in seen:
            seen.add(cur)
            path.append(self._col_name[cur])
            cur = self._col_parent.get(cur)
        return list(reversed(path))

    def collection_depth(self, cid):
        """分类深度：一级为 0。"""
        depth = len(self.collection_path(cid)) - 1
        return depth if depth > 0 else 0

    def collection_labels(self):
        """返回 [(cid, 缩进显示名, depth)]，按树的先序排列，供菜单/下拉使用。

        同名消歧：若出现完全相同的「缩进显示名」（不同父、同深度、同名），
        只对**这些重复项**追加所属父路径后缀，如 "    同名子（A）"；
        父路径用 collection_path 拼接（避免直接父名也重名）。
        未重复的保持原样，界面保持清爽；追加后仍重复再补短 cid 兜底。
        """
        raw = []           # [(cid, name, depth)]
        visited = set()

        def walk(parent):
            for c in self.collection_children(parent):
                cid = c.get("id")
                if not cid or cid in visited:
                    continue
                visited.add(cid)
                raw.append((cid, c.get("name", ""), self.collection_depth(cid)))
                walk(cid)

        walk(None)

        def base_disp(name, depth):
            return "    " * depth + name

        # 统计哪些「缩进显示名」重复（只有重复的才消歧）
        disp_count = {}
        for _cid, name, depth in raw:
            d = base_disp(name, depth)
            disp_count[d] = disp_count.get(d, 0) + 1

        out = []
        used = set()
        for cid, name, depth in raw:
            d = base_disp(name, depth)
            if disp_count[d] > 1:
                parent_cid = self._col_parent.get(cid)
                parent_path = self.collection_path(parent_cid) if parent_cid else []
                if parent_path:
                    d = d + "（" + " / ".join(parent_path) + "）"
            # 兜底：消歧后仍碰撞则补短 cid
            if d in used:
                d = d + "（#" + str(cid)[-4:] + "）"
            used.add(d)
            out.append((cid, d, depth))
        return out

    def collection_scope(self, cid):
        """返回 [cid] + 全部子孙，用于「父分类包含子分类文件」的过滤。"""
        return [cid] + self.collection_descendants(cid)

    def add_collection(self, name, parent=None):
        name = (name or "").strip()
        if not name:
            raise ValueError("分类名不能为空")
        if parent is not None and parent not in self._col_name:
            raise ValueError("父分类不存在")
        if any(c.get("parent") == parent and c.get("name") == name
               for c in self.collections()):
            raise ValueError("同一层级下已存在同名分类")
        cid = "c_" + uuid_hex()
        self.config["collections"].append(
            {"id": cid, "name": name, "parent": parent})
        self._save_json(self.config_file, self.config)
        self._rebuild_col_cache()
        return cid

    def rename_collection(self, cid, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("分类名不能为空")
        if cid not in self._col_name:
            raise ValueError("分类不存在")
        parent = self._col_parent.get(cid)
        for c in self.collections():
            if (c.get("id") != cid and c.get("parent") == parent
                    and c.get("name") == name):
                raise ValueError("同一层级下已存在同名分类")
        for c in self.collections():
            if c.get("id") == cid:
                c["name"] = name
                self._save_json(self.config_file, self.config)
                self._rebuild_col_cache()
                return
        raise ValueError("分类不存在")

    def move_collection(self, cid, new_parent):
        """把分类迁移到 new_parent 下（None 表示移到顶层）。"""
        if cid not in self._col_name:
            raise ValueError("分类不存在")
        if new_parent is not None and new_parent not in self._col_name:
            raise ValueError("目标分类不存在")
        if new_parent == cid or (new_parent is not None
                                 and new_parent in self.collection_descendants(cid)):
            raise ValueError("不能移动到自己的子分类下")
        name = self._col_name.get(cid)
        for c in self.collections():
            if (c.get("id") != cid and c.get("parent") == new_parent
                    and c.get("name") == name):
                raise ValueError("目标层级下已存在同名分类")
        for c in self.collections():
            if c.get("id") == cid:
                c["parent"] = new_parent
                break
        self._save_json(self.config_file, self.config)
        self._rebuild_col_cache()
        return cid

    def collection_parent(self, cid):
        """返回分类的直接父 cid（顶层为 None）。"""
        return self._col_parent.get(cid)

    def reorder_collection(self, cid, new_parent, before_cid=None):
        """把分类 cid 移到 new_parent 层，并插到 before_cid 的前面（None=该层末尾）。

        用于 #4 的同层重排 / 跨层定点插入。因 collection_children 按 collections
        的原始顺序过滤，只须保证「插到 before_cid 条目正前方」即可命中目标位置，
        即使其它父的条目与它交错也不影响相对次序。
        校验与 move_collection 对齐：存在性 / 不能移入自己子孙 / 目标层同名。
        """
        if cid not in self._col_name:
            raise ValueError("分类不存在")
        if new_parent is not None and new_parent not in self._col_name:
            raise ValueError("目标分类不存在")
        if new_parent == cid or (new_parent is not None
                                 and new_parent in self.collection_descendants(cid)):
            raise ValueError("不能移动到自己的子分类下")
        if before_cid is not None:
            if before_cid not in self._col_name:
                raise ValueError("目标分类不存在")
            if before_cid == cid:
                return cid                                 # 落点即自身：无需移动
            if before_cid in self.collection_descendants(cid):
                raise ValueError("不能移动到自己的子分类下")
        name = self._col_name.get(cid)
        for c in self.collections():
            if (c.get("id") != cid and c.get("parent") == new_parent
                    and c.get("name") == name):
                raise ValueError("目标层级下已存在同名分类")
        entry = None
        rest = []
        for c in self.collections():
            if c.get("id") == cid:
                entry = c
            else:
                rest.append(c)
        if entry is None:
            raise ValueError("分类不存在")
        entry["parent"] = new_parent
        if before_cid is None:
            rest.append(entry)
        else:
            idx = next((i for i, c in enumerate(rest)
                        if c.get("id") == before_cid), None)
            if idx is None:
                rest.append(entry)          # 目标不存在 → 退化为末尾
            else:
                rest.insert(idx, entry)
        self.config["collections"] = rest
        self._save_json(self.config_file, self.config)
        self._rebuild_col_cache()
        return cid

    def delete_collection(self, cid):
        """级联删除该分类及其全部子孙，返回被删除的 cid 列表。

        只删分类与归类引用，绝不动文件记录本身（文件变为「未分类」）。
        """
        if cid not in self._col_name:
            return []
        victims = [cid] + self.collection_descendants(cid)
        vset = set(victims)
        self.config["collections"] = [c for c in self.collections()
                                      if c.get("id") not in vset]
        # 索引上的归属批量清理（一次落盘）
        for entry in self.config.get("files", []):
            if entry.get("category") in vset:
                entry["category"] = None
        self._save_json(self.config_file, self.config)
        # 磁盘 meta 同步（索引为权威，保持一致）
        for fid in self._disk_fids():
            meta = self.load_meta(fid)
            if not isinstance(meta, dict):
                continue
            if meta.get("category") in vset:
                meta["category"] = None
                self._save_json(self._meta_path(fid), meta)
        self._rebuild_col_cache()
        return victims

    def collection_name(self, cid):
        return self._col_name.get(cid, "?")

    def collection_names(self, cids):
        """显示用：叶子名以「、」连接（不做全路径，避免列过宽）。"""
        return "、".join(self.collection_name(cid) for cid in cids)

    # ---------- 索引 ----------
    def _disk_fids(self):
        """磁盘上「有效」的 fid：meta.json 可解析且 versions 非空。

        与 rebuild_index 的收录口径保持一致，避免每次启动都误判不一致
        而反复全量重建（解析失败 / 空 versions 的目录一律忽略）。
        """
        fids = set()
        if self.files_dir.exists():
            for d in self.files_dir.iterdir():
                if not d.is_dir():
                    continue
                meta = self._load_json(d / "meta.json", None)
                if isinstance(meta, dict) and meta.get("versions"):
                    fids.add(d.name)
        return fids

    def _free_fid(self, fid):
        """确保 fid 目录未被占用：目录已存在（无论内容是什么）即派生新 fid。
        v6 没有 relpath 可比对，任何已存在目录一律视为占用。"""
        while (self.files_dir / fid).exists():
            fid = f"{fid}_{uuid_hex()[:6]}"
        return fid

    # ---------- v5 → v6 一次性迁移 ----------
    MIGRATION_BACKUP_NAME = "config_v5_backup.json"

    def _migrate_v5_to_v6(self):
        """v5 → v6 一次性迁移。返回 True 表示本次执行了迁移。

        触发条件（内容判定，与备份文件是否存在无关 → 天然幂等）：
        config 顶层含 watch / watch_enabled / managed_folder，
        或任一 files 条目含 collections / relpath / external / status_cache。
        失败路径：备份失败 → 抛 RuntimeError，绝不写盘（config 保持原样）。
        """
        cfg = self.config
        legacy_file_keys = {"collections", "relpath", "external", "status_cache"}

        def _is_legacy():
            if any(k in cfg for k in ("watch", "watch_enabled", "managed_folder")):
                return True
            for e in cfg.get("files") or []:
                if isinstance(e, dict) and legacy_file_keys & set(e):
                    return True
            return False

        if not _is_legacy():
            return False
        backup = self.store_dir / self.MIGRATION_BACKUP_NAME
        if not backup.exists():
            try:
                shutil.copy2(self.config_file, backup)
            except OSError as e:
                raise RuntimeError(
                    f"数据格式升级失败：无法备份 config.json（{e}）。"
                    "已中止，你的数据未做任何修改。")
        new_files = []
        for e in cfg.get("files") or []:
            if not isinstance(e, dict):
                continue
            cols = e.get("collections") or []
            new_files.append({
                "fid": e.get("fid", ""),
                "name": e.get("name", ""),
                "category": (cols[0] if cols else e.get("category")),
                "latest_time": e.get("latest_time", ""),
                "version_count": e.get("version_count", 0),
                "latest_hash": e.get("latest_hash", ""),
                "search_text": e.get("search_text", ""),
            })
        cfg["files"] = new_files
        for k in ("watch", "watch_enabled", "managed_folder"):
            cfg.pop(k, None)
        # _save_json 原子写：先把旧 config 复制为 .bak，再 os.replace
        self._save_json(self.config_file, cfg)
        return True

    def _ensure_index(self):
        """校验索引与磁盘 files\\ 是否一致，不一致则全量重建。"""
        idx = self.config.get("files")
        ok = isinstance(idx, list)
        if ok:
            idx_fids = {e.get("fid") for e in idx if isinstance(e, dict)}
            if idx_fids != self._disk_fids():
                ok = False
        if not ok:
            self.rebuild_index()

    @staticmethod
    def _search_blob(meta):
        parts = [meta.get("name", "")]
        for v in meta.get("versions", []):
            parts.append(v.get("reason", ""))
            parts.append(v.get("source", ""))
        return "\n".join(parts).lower()

    def _index_entry(self, meta):
        versions = meta.get("versions", [])
        latest = None
        for v in versions:
            if latest is None or v.get("time", "") >= latest.get("time", ""):
                latest = v
        return {
            "fid": meta["fid"],
            "name": meta.get("name", ""),
            "category": meta.get("category"),
            "latest_time": latest.get("time", "") if latest else "",
            "version_count": len(versions),
            "latest_hash": (latest.get("sha256", "") if latest else ""),
            "search_text": self._search_blob(meta),
        }

    def rebuild_index(self, save=True):
        """全量扫描 files\\ 重建索引，返回索引列表。"""
        entries = []
        for fid in sorted(self._disk_fids()):
            meta = self.load_meta(fid)
            if not meta or not meta.get("versions"):
                continue
            entries.append(self._index_entry(meta))
        self.config["files"] = entries
        if save:
            self._save_json(self.config_file, self.config)
        return entries

    def _update_index_entry(self, meta):
        """提交/归类/改名后刷新索引项（原地更新，保持引用有效）。"""
        entry = self._index_entry(meta)
        files = self.config.setdefault("files", [])
        for e in files:
            if e.get("fid") == meta["fid"]:
                e.clear()
                e.update(entry)
                self._save_json(self.config_file, self.config)
                return e
        files.append(entry)
        self._save_json(self.config_file, self.config)
        return entry

    def _remove_index_entry(self, fid):
        files = self.config.get("files", [])
        self.config["files"] = [e for e in files if e.get("fid") != fid]
        self._save_json(self.config_file, self.config)

    def find_in_category(self, cid, name):
        """按分类查同名（name 含扩展名；大小写不敏感——✅ lead 拍板，
        对齐 Windows 文件系统习惯，避免「A.docx」与「a.docx」造成视觉重复）。
        cid=None=未分类。返回索引条目 dict 或 None。"""
        key = (name or "").strip().lower()
        if not key:
            return None
        for e in self.config.get("files", []):
            if e.get("category") == cid and \
                    str(e.get("name", "")).strip().lower() == key:
                return e
        return None

    def file_list(self):
        """返回索引中的受管文件条目（按最近版本时间倒序）。"""
        result = [e for e in self.config.get("files", [])
                  if e.get("version_count", 0) > 0]
        result.sort(key=lambda e: e.get("latest_time", ""), reverse=True)
        return result

    # 兼容旧调用名
    def all_files(self):
        return self.file_list()

    # ---------- 文件与版本 ----------
    def _file_id(self, name: str):
        """v6：fid = 净化文件名词干 + 随机后缀（不再有路径可哈希）。
        随机后缀防撞；目录占用由 _free_fid 兜底。"""
        stem = INVALID_CHARS.sub("_", Path(name).stem) or "file"
        return f"{stem}_{uuid_hex()}"

    def _meta_path(self, fid):
        return self.files_dir / fid / "meta.json"

    def _load_meta(self, fid):
        return self._load_json(self._meta_path(fid), None)

    def load_meta(self, fid):
        """读取单个文件 meta 并规范化为 v6 schema。

        旧字段（relpath/external/status_cache/collections）在这里被剥掉：
        内存里永远只有新 schema，之后任何一次 save 落盘的都是干净结构
        （= 磁盘 meta 的懒清理）。config.json 未迁移字段不受影响。
        """
        meta = self._load_meta(fid)
        if meta is None:
            return None
        for k in ("relpath", "external", "status_cache"):
            meta.pop(k, None)
        if "collections" in meta:
            cols = meta.pop("collections") or []
            if not meta.get("category"):
                meta["category"] = cols[0] if cols else None
        # 用 `or` 兜底：显式 null 不能留在键里（历史教训见原 R2 注释——
        # time=None 会让版本列表排序抛 TypeError，reason=None 会露出 "None"）
        meta["category"] = meta.get("category") or None
        meta["name"] = meta.get("name") if isinstance(meta.get("name"), str) else ""
        # versions 必须是 dict 列表：外部把 meta.json 改坏（如 `"versions": 5`）
        # 时不能让"读一条记录"抛栈（_disk_fids/rebuild_index 都依赖本方法）
        raw_vs = meta.get("versions")
        meta["versions"] = ([v for v in raw_vs if isinstance(v, dict)]
                            if isinstance(raw_vs, list) else [])
        for v in meta["versions"]:
            v["id"] = v.get("id") or ""
            v["time"] = v.get("time") or ""
            v["reason"] = v.get("reason") or ""
            v["source"] = v.get("source") or ""
            v["size"] = v.get("size") or 0
            v["sha256"] = v.get("sha256") or ""
            v["auto"] = bool(v.get("auto"))
            v["star"] = bool(v.get("star"))
        return meta

    def _append_snapshot(self, meta, src_path, reason, source, auto):
        """把 src_path 复制入库作为 meta 的新版本并落盘（new/next 共用）。"""
        fid = meta["fid"]
        fdir = self.files_dir / fid
        fdir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        seq = 1
        while True:
            vfile = f"{now:%Y%m%d_%H%M%S}_{seq}{src_path.suffix}"
            if not (fdir / vfile).exists():
                break
            seq += 1
        _copy2_writable(src_path, fdir / vfile)
        try:
            digest = _safe_sha256(src_path)     # 只读字节，不解析内容
        except Exception:
            digest = ""
        meta.setdefault("versions", []).append({
            "id": vfile,
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "source": (source or "").strip(),
            "size": src_path.stat().st_size,
            "auto": bool(auto),
            "sha256": digest,
            "star": False,
        })
        self._save_json(self._meta_path(fid), meta)
        self._update_index_entry(meta)

    def commit_new(self, path, reason, source="", category=None):
        """新建一条文件记录：path 当前内容复制入库作为第 1 个版本。
        同分类同名查重由 UI 层负责；此处再兜底校验一次（✅ lead 拍板：
        防御双保险，保留）。"""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("修改原因不能为空")
        name = path.name
        if self.find_in_category(category, name) is not None:
            raise ValueError(f"该分类下已存在同名文件：{name}")
        fid = self._free_fid(self._file_id(name))
        meta = {"fid": fid, "name": name, "category": category, "versions": []}
        self._append_snapshot(meta, path, reason, source, auto=False)
        return meta["versions"][-1]

    def commit_next_version(self, fid, path, reason, source=""):
        """给已有记录续一个版本：快照复制入库；磁盘上的 path 原文件不动。
        path 也可以是库内快照路径（转移合并场景复用本方法）。"""
        meta = self.load_meta(fid)
        if meta is None:
            raise ValueError("文件记录不存在")
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("修改原因不能为空")
        self._append_snapshot(meta, path, reason, source, auto=False)
        return meta["versions"][-1]

    def set_category(self, fid, cid):
        """设置文件归属分类（查重由 UI 层先做）。cid=None 表示未分类。"""
        meta = self.load_meta(fid)
        if meta is None:
            raise ValueError("文件记录不存在")
        if cid is not None and cid not in self._col_name:
            raise ValueError("目标分类不存在")
        meta["category"] = cid
        self._save_json(self._meta_path(fid), meta)
        self._update_index_entry(meta)

    def rename_record(self, fid, new_name):
        """重命名记录（转移冲突「重命名后移动」用）。"""
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("文件名不能为空")
        if INVALID_CHARS.search(new_name):
            raise ValueError('文件名不能包含 \\ / : * ? " < > |')
        meta = self.load_meta(fid)
        if meta is None:
            raise ValueError("文件记录不存在")
        if new_name != meta.get("name") and \
                self.find_in_category(meta.get("category"), new_name) is not None:
            raise ValueError(f"该分类下已存在同名文件：{new_name}")
        meta["name"] = new_name
        self._save_json(self._meta_path(fid), meta)
        self._update_index_entry(meta)

    def set_version_star(self, meta, ver_id, star):
        for v in meta.get("versions", []):
            if v.get("id") == ver_id:
                v["star"] = bool(star)
                break
        self._save_json(self._meta_path(meta["fid"]), meta)
        self._update_index_entry(meta)

    def update_version_info(self, fid, ver_id, reason, source):
        """R14：就地更新某版本的「修改原因 / 意见来源」（只改元数据，
        绝不动版本快照文件，也不产生新版本）。

        修改原因必填 —— 与提交弹窗口径一致。改完必须刷新索引项：搜索
        blob（search_text）里含这两个字段，不刷新会出现"搜得到旧词、
        搜不到新词"的鬼影。返回更新后的版本 dict。
        """
        meta = self.load_meta(fid)
        if meta is None:
            raise ValueError("文件记录不存在")
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == ver_id), None)
        if ver is None:
            raise ValueError("该版本不存在")
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("修改原因不能为空")
        ver["reason"] = reason
        ver["source"] = (source or "").strip()
        self._save_json(self._meta_path(fid), meta)
        self._update_index_entry(meta)
        return ver

    def version_file(self, meta, ver):
        f = self.files_dir / meta["fid"] / ver["id"]
        if not f.is_file():
            raise FileNotFoundError("版本文件丢失，请检查版本库目录")
        return f

    # ---------- 回收站 ----------
    def _trash_dir(self):
        d = self.store_dir / "_trash"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _move_to_trash(self, src, tag, extra=None, register=True):
        """把 src（文件或目录）移动进 _trash，加时间戳前缀避免重名。

        register=True 时同步在回收站清单（_trash/trash.json）里登记一条，
        供左栏「回收站」分类列出/还原；register=False 用于「残壳」目录
        （版本删光后只剩 meta.json 的记录目录，由 _trash_attach_extra
        挂在原条目上）。

        返回值：登记成功 → 该条目 dict；register=False → 落点 Path；
        移动失败 → None。
        """
        src = Path(src)
        if not src.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._trash_dir()
        dest = base / f"{stamp}_{tag}_{src.name}"
        n = 1
        while dest.exists():
            dest = base / f"{stamp}_{tag}_{n}_{src.name}"
            n += 1
        try:
            shutil.move(str(src), str(dest))
        except (OSError, shutil.Error):
            try:
                if src.is_dir():
                    shutil.copytree(src, dest)
                    shutil.rmtree(src, ignore_errors=True)
                else:
                    _copy2_writable(src, dest)
                    os.remove(src)
            except OSError:
                return None
        if register:
            return self._trash_register(dest, tag, extra=extra)
        return dest

    # ---------- 回收站清单（_trash/trash.json）----------
    # 真身永远是 _trash 下的文件/目录；json 只是索引，丢了也能靠目录扫描
    # 重新合成（见 _trash_scan），所以不存在「清单坏了 = 内容丢了」。
    TRASH_MANIFEST_NAME = "trash.json"

    # 回收站目录里的文件名形如 20260930_101530_rec_报告.docx（撞名会多一段序号）
    _TRASH_NAME_RE = re.compile(
        r"^\d{8}_\d{6}_(?:rec|ver)_(?:(\d+)_)?(.+)$", re.S)

    def _trash_manifest_path(self):
        return self._trash_dir() / self.TRASH_MANIFEST_NAME

    @classmethod
    def _trash_strip_prefix(cls, name):
        """去掉时间戳/类型前缀，还原出原始文件名（认不出就原样返回）。"""
        m = cls._TRASH_NAME_RE.match(name or "")
        return m.group(2) if m else (name or "")

    @staticmethod
    def _trash_item_id(path):
        """条目 id：由真身路径派生 → 同一份内容反复扫描 id 稳定。"""
        return "t" + hashlib.sha1(
            str(path).encode("utf-8", "replace")).hexdigest()[:10]

    @staticmethod
    def _path_size(path):
        """文件/目录占用字节数（读不到的部分按 0 计，仅用于展示）。"""
        p = Path(path)
        try:
            if p.is_file():
                return p.stat().st_size
            total = 0
            for root, _dirs, files in os.walk(p):
                for fn in files:
                    try:
                        total += (Path(root) / fn).stat().st_size
                    except OSError:
                        pass
            return total
        except OSError:
            return 0

    def _load_trash_items(self):
        data = self._load_json(self._trash_manifest_path(), {})
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [it for it in items
                if isinstance(it, dict) and it.get("path")]

    def _save_trash_items(self, items):
        try:
            self._save_json(self._trash_manifest_path(), {"items": items})
        except OSError:
            pass          # 清单写不进最多丢"还原元数据"，真身仍在 _trash

    def _trash_register(self, dest, tag, extra=None):
        """登记一条回收站条目，返回该条目 dict。
        extra_paths 初始化成空表：残壳由 _trash_attach_extra 事后挂上来。"""
        if dest is None:
            return None
        dest = Path(dest)
        extra = dict(extra or {})
        name = extra.get("name") or self._trash_strip_prefix(dest.name)
        item = {
            "id": self._trash_item_id(dest),
            "tag": tag,                       # rec=整条记录 / ver=单个版本
            "path": str(dest),
            "extra_paths": [],
            "name": name,
            "ext": Path(name).suffix.lower().lstrip("."),
            "fid": extra.get("fid") or "",
            "category": extra.get("category"),
            "latest_time": extra.get("latest_time") or "",
            "version_count": int(extra.get("version_count") or 0),
            "version": extra.get("version") or None,
            "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "size": self._path_size(dest),
        }
        items = [it for it in self._load_trash_items()
                 if it.get("id") != item["id"]]
        items.append(item)
        self._save_trash_items(items)
        return item

    def _trash_attach_extra(self, item_id, path):
        """把「残壳」路径挂到已有条目上（删光版本的记录目录）。"""
        if not item_id or path is None:
            return
        items = self._load_trash_items()
        changed = False
        for it in items:
            if it.get("id") == item_id:
                ex = it.setdefault("extra_paths", [])
                if str(path) not in ex:
                    ex.append(str(Path(path)))
                    changed = True
        if changed:
            self._save_trash_items(items)

    def _trash_synth_entry(self, p):
        """给清单外的遗留内容（旧版本删出来的、手工放进 _trash 的）造条目。

        只读 meta.json 里"能信的那部分"：字段类型被外部改坏（如
        `"versions": 5`）也不能让回收站视图抛栈 —— 这里是只读展示路径。
        """
        p = Path(p)
        meta = {}
        if p.is_dir():
            meta = self._load_json(p / "meta.json", {}) or {}
            if not isinstance(meta, dict):
                meta = {}
        name = meta.get("name") or self._trash_strip_prefix(p.name)
        if not isinstance(name, str):
            name = self._trash_strip_prefix(p.name)
        raw_vs = meta.get("versions")
        versions = [v for v in raw_vs if isinstance(v, dict)] \
            if isinstance(raw_vs, list) else []
        times = [str(v.get("time") or "") for v in versions]
        deleted_at = ""
        m = re.match(r"^(\d{8})_(\d{6})", p.name)
        if m:
            try:
                deleted_at = datetime.strptime(
                    m.group(1) + m.group(2),
                    "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                deleted_at = ""
        return {
            "id": self._trash_item_id(p),
            "tag": "rec" if p.is_dir() else "ver",
            "path": str(p),
            "extra_paths": [],
            "name": name,
            "ext": Path(name).suffix.lower().lstrip("."),
            "fid": meta.get("fid") if isinstance(meta.get("fid"), str) else "",
            "category": meta.get("category"),
            "latest_time": (max(times) if times else ""),
            "version_count": len(versions),
            "version": None,          # 遗留条目没有版本元数据，按快照还原
            "deleted_at": deleted_at,
            "legacy": True,
            "size": self._path_size(p),
        }

    def _trash_scan(self):
        """读回收站：以清单为准，剔除真身已丢的、吸收清单外的遗留内容。

        返回按删除时间倒序的条目列表（内部会按需回写清单）。

        两个关键口径：
        · 真身丢了的条目直接摘掉，且**它的 extra_paths 不再算"已引用"** ——
          否则那个残壳会在本轮扫描里被当成"已引用"跳过、下一轮才冒出来，
          中间这一轮用户看到的是"清单里没有、目录里有"的自相矛盾状态；
        · 只有真身还在的条目，其 extra_paths 才算被引用（那是有主的残壳，
          跟活跃条目一起出现在同一条里，不该再单列一条）。
        """
        base = self._trash_dir()
        items = self._load_trash_items()
        live, changed = [], False
        for it in items:
            if Path(it.get("path")).exists():
                live.append(it)
            else:
                changed = True
        items = live
        referenced = set()
        for it in items:
            referenced.add(str(Path(it.get("path"))))
            for p in it.get("extra_paths") or []:
                referenced.add(str(Path(p)))
        try:
            entries = sorted(base.iterdir())
        except OSError:
            entries = []
        for p in entries:
            # 只跳过清单自己的备份/临时文件（不能按后缀一刀切：
            # 用户完全可能提交名为 x.tmp / x.bak 的文件，删掉后被搬进来）
            if p.name in (self.TRASH_MANIFEST_NAME,
                          self.TRASH_MANIFEST_NAME + ".tmp",
                          self.TRASH_MANIFEST_NAME + ".bak"):
                continue
            if str(p) in referenced:
                continue
            items.append(self._trash_synth_entry(p))
            changed = True
        if changed:
            self._save_trash_items(items)
        items.sort(key=lambda it: str(it.get("deleted_at") or ""), reverse=True)
        return items

    def trash_items(self):
        """回收站条目（左栏「回收站」分类的数据源）。"""
        return self._trash_scan()

    def trash_summary(self):
        """返回 (条目数, 占用字节数)。"""
        items = self._trash_scan()
        return len(items), sum(int(it.get("size") or 0) for it in items)

    @staticmethod
    def _remove_path(p):
        """删除一个文件/目录（尽力而为）。返回 True 表示已不存在。"""
        pp = Path(p)
        try:
            if pp.is_dir():
                shutil.rmtree(pp)
            elif pp.exists():
                os.remove(pp)
        except OSError:
            return not pp.exists()
        return True

    def empty_trash(self):
        """清空回收站（物理删除）。返回 (条目数, 字节数, 失败路径列表)。

        被占用的内容删不掉时不算"成功清空"：清单会按**剩下什么**重写，
        保证清单与真身始终一致（下次进来还能看到、还能再删）。
        """
        base = self._trash_dir()
        items = self._trash_scan()
        total = sum(int(it.get("size") or 0) for it in items)
        try:
            entries = sorted(base.iterdir())
        except OSError as e:
            return 0, 0, [str(e)]
        failed = []
        for p in entries:
            if not self._remove_path(p):
                failed.append(str(p))
        # 清单 = 残留下来的真身（不复用旧条目：它们的 path 可能已经失效）
        rest = []
        for p in entries:
            if p.exists():
                rest.append(self._trash_synth_entry(p))
        self._save_trash_items(rest)
        return len(items) - len(rest), total, failed

    def purge_trash_item(self, item_id):
        """彻底删除回收站里的单个条目（不可恢复）。"""
        items = self._trash_scan()
        item = next((it for it in items if it.get("id") == item_id), None)
        if item is None:
            # 真身（含残壳）都已不在 → 用清单原始条目兜底删残壳，再摘掉条目
            raw = self._load_trash_items()
            item = next((it for it in raw if it.get("id") == item_id), None)
            if item is None:
                return False, "回收站条目不存在"
            paths = [item.get("path")] + list(item.get("extra_paths") or [])
            ok = all(self._remove_path(p) for p in paths)
            if ok:
                self._save_trash_items(
                    [it for it in raw if it.get("id") != item_id])
            return ok, ("" if ok else "有文件正被其它程序占用，未能全部删除")
        ok = True
        for p in [item.get("path")] + list(item.get("extra_paths") or []):
            if not self._remove_path(p):
                ok = False
        if ok:
            self._save_trash_items(
                [it for it in items if it.get("id") != item_id])
        return ok, ("" if ok else "有文件正被其它程序占用，未能全部删除")

    def _unique_name_in_category(self, cid, old_name, marker="副本"):
        """在指定分类下派生一个不重名的名字：
        「xxx - 副本.ext」「xxx - 副本(2).ext」…（库内复制 / 回收站还原共用）。"""
        old_name = old_name or "未命名"
        stem, suffix = Path(old_name).stem, Path(old_name).suffix
        base = f"{stem} - {marker}"
        n = 2
        while True:
            cand = f"{base}{suffix}" if n == 2 else f"{base}({n - 1}){suffix}"
            if self.find_in_category(cid, cand) is None:
                return cand
            n += 1

    @staticmethod
    def _undo_move(moved_to, back_to):
        """把已经移出回收站的真身送回 _trash（还原中途失败时回滚用）。

        为什么必须回滚：清单是「真身在哪」的索引，还原失败却把真身留在库内，
        下一次扫描就会按"真身已丢"把条目摘掉 —— 用户看到"还原失败"，
        清单却假装什么都没发生。回滚失败也不致命：真身在库里，
        重启时 _ensure_index 会凭磁盘 meta 把它重新收进索引。
        """
        try:
            if moved_to is None:
                return False
            mp, bp = Path(moved_to), Path(back_to)
            if mp.exists() and not bp.exists():
                shutil.move(str(mp), str(bp))
                return True
        except (OSError, shutil.Error):
            pass
        return False

    def restore_trash_item(self, item_id):
        """把回收站条目还原回版本库。返回 (ok, 结果说明)。"""
        items = self._trash_scan()
        item = next((it for it in items if it.get("id") == item_id), None)
        if item is None:
            return False, "回收站条目不存在"
        src = Path(item.get("path"))
        if not src.exists():
            return False, "回收站内容已丢失"
        moved_to = None
        try:
            if item.get("tag") == "rec" and src.is_dir():
                ok, msg, moved_to = self._restore_record_dir(src, item)
            else:
                ok, msg, moved_to = self._restore_version_file(src, item)
        except Exception as e:                  # 兜底：界面不该被未知异常打断
            self._undo_move(moved_to, src)
            return False, f"还原失败：{e}"
        if not ok:
            self._undo_move(moved_to, src)      # 已移出的真身送回回收站
            return False, msg
        for p in item.get("extra_paths") or []:
            self._remove_path(p)
        self._save_trash_items(
            [it for it in items if it.get("id") != item_id])
        return True, msg

    def _restore_record_dir(self, src, item):
        """还原整条记录目录（fid 被占用 / 目录不是标准记录时另派新 fid）。

        返回 (ok, 说明, 真身落点)；落点用于失败回滚（见 _undo_move）。
        """
        fid = item.get("fid") or ""
        target = self.files_dir / fid if fid else None
        if target is None or target.exists() or not (src / "meta.json").is_file():
            meta = self._load_json(src / "meta.json", None)
            if not isinstance(meta, dict):
                return False, "记录目录里没有可用的 meta.json，无法还原", None
            fid = self._free_fid(self._file_id(
                meta.get("name") or item.get("name") or "还原文件"))
            target = self.files_dir / fid
            try:
                shutil.move(str(src), str(target))
            except (OSError, shutil.Error) as e:
                return False, f"还原失败：{e}", None
            meta["fid"] = fid
            meta["name"] = meta.get("name") or item.get("name") or ""
            try:
                self._save_json(target / "meta.json", meta)
            except OSError as e:
                return False, f"还原失败：{e}", target
        else:
            try:
                shutil.move(str(src), str(target))
            except (OSError, shutil.Error) as e:
                return False, f"还原失败：{e}", None
        meta = self.load_meta(fid)
        if meta is None:
            return False, "还原后的记录读不出来（已回滚，内容仍在回收站）", target
        if not meta.get("versions"):
            # 0 版本的"残壳"还原回库只会留下一条谁都看不见、又占目录的空记录
            return False, ("该内容里已经不剩任何版本，无法还原"
                           "（可用「彻底删除」清理）"), target
        if meta.get("category") is not None and \
                meta["category"] not in self._col_name:
            meta["category"] = None        # 原分类已被删除 → 落回未分类
        name = meta.get("name") or "还原文件"
        hit = self.find_in_category(meta.get("category"), name)
        if hit is not None and hit.get("fid") != fid:
            meta["name"] = self._unique_name_in_category(
                meta.get("category"), name, "还原")
        try:
            self._save_json(self._meta_path(fid), meta)
            self._update_index_entry(meta)
        except OSError as e:
            return False, f"还原失败：{e}", target
        return True, f"已还原「{meta.get('name')}」", target

    def _restore_version_file(self, src, item):
        """还原单个版本快照：原记录还在就补回一条版本，否则新建记录。

        返回 (ok, 说明, 真身落点)；落点用于失败回滚（见 _undo_move）。
        """
        ver = dict(item.get("version") or {})
        fid = item.get("fid") or ""
        name = item.get("name") or self._trash_strip_prefix(src.name)
        meta = self.load_meta(fid) if fid else None
        prev_meta = None
        if meta is not None:
            try:
                prev_meta = json.loads(json.dumps(meta))   # 回滚用的还原前快照
            except (TypeError, ValueError):
                prev_meta = None
        d = self.files_dir / fid if meta is not None else None
        if d is None:                       # 原记录已不在 → 用快照新建记录
            fid = self._free_fid(self._file_id(name))
            d = self.files_dir / fid
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"还原失败：{e}", None
        ver_id = ver.get("id") or src.name
        dest = d / ver_id
        n = 1
        while dest.exists():
            ver_id = f"{n}_{ver_id}"
            dest = d / ver_id
            n += 1
        try:
            shutil.move(str(src), str(dest))
        except (OSError, shutil.Error) as e:
            return False, f"还原失败：{e}", None
        try:
            st = dest.stat()
        except OSError:
            st = None
        ver = {
            "id": ver_id,
            "time": (ver.get("time") or item.get("latest_time")
                     or (datetime.fromtimestamp(st.st_mtime).strftime(
                         "%Y-%m-%d %H:%M:%S") if st else
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))),
            "reason": ver.get("reason") or "自回收站还原",
            "source": ver.get("source") or "",
            "size": (st.st_size if st else 0),
            "auto": bool(ver.get("auto")),
            "sha256": ver.get("sha256") or "",
            "star": bool(ver.get("star")),
        }
        if meta is None:
            cat = item.get("category")
            if cat is not None and cat not in self._col_name:
                cat = None
            new_name = name
            if self.find_in_category(cat, new_name) is not None:
                new_name = self._unique_name_in_category(cat, new_name, "还原")
            try:
                self._save_json(self._meta_path(fid),
                                {"fid": fid, "name": new_name, "category": cat,
                                 "versions": [ver]})
                fresh = self.load_meta(fid)
                if fresh is None:
                    self._drop_half_restored(fid, None)
                    return False, "还原后的记录读不出来", dest
                self._update_index_entry(fresh)
            except OSError as e:
                # 写盘/写索引失败：连刚建出来的记录目录一起撤掉，
                # 否则重启时 _ensure_index 会按磁盘 meta 重建出"有版本行、快照缺失"的记录
                self._drop_half_restored(fid, prev_meta)
                return False, f"还原失败：{e}", dest
            return True, f"已把「{name}」还原为新文件「{new_name}」", dest
        # 按 time 插到有序位置（还原的是"旧版本"时不能无脑 append：
        # 保持 versions 时间正序，latest_version/版本号编号的口径才稳定）
        versions = meta.setdefault("versions", [])
        pos = len(versions)
        for i, v in enumerate(versions):
            if str(ver.get("time") or "") < str((v or {}).get("time") or ""):
                pos = i
                break
        versions.insert(pos, ver)
        try:
            self._save_json(self._meta_path(fid), meta)
            self._update_index_entry(meta)
        except OSError as e:
            # 回滚要把"还原前的 meta"写回去（否则库里留下一条指向空快照的版本）
            self._drop_half_restored(fid, prev_meta)
            return False, f"还原失败：{e}", dest
        return True, f"已把「{ver_id}」还原回「{meta.get('name', '')}」", dest

    def _drop_half_restored(self, fid, prev_meta):
        """撤销一次半途失败的还原：meta 回退（prev_meta=None 则删掉新记录）。"""
        try:
            if prev_meta is None:
                try:
                    os.remove(self._meta_path(fid))
                except OSError:
                    pass
                self._remove_index_entry(fid)
            else:
                self._save_json(self._meta_path(fid), prev_meta)
                now = self.load_meta(fid)
                if now is not None:
                    self._update_index_entry(now)
        except OSError:
            pass          # 尽力而为：真身已回滚，重启时 _ensure_index 会再对账

    def delete_version(self, fid, ver_id):
        """删除单个历史版本（移入 _trash）；若无版本残留则同时移除整条记录。"""
        meta = self._load_meta(fid)
        if meta is None:
            return False, "记录不存在"
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == ver_id), None)
        if ver is None:
            return False, "版本不存在"
        entry = self._move_to_trash(
            self.files_dir / fid / ver_id, "ver",
            extra={"fid": fid, "name": meta.get("name", ""),
                   "category": meta.get("category"),
                   "latest_time": ver.get("time", ""),
                   "version_count": 1,
                   "version": dict(ver)})
        if entry is None and (self.files_dir / fid / ver_id).exists():
            # 移入回收站失败（占用/权限/磁盘满）→ 绝不先把版本从 meta 里抹掉，
            # 否则快照变成谁都指不到的孤儿（原实现会静默丢版本）
            return False, "移入回收站失败（文件被占用或权限不足），已保留该版本"
        meta["versions"] = [v for v in meta["versions"]
                            if v.get("id") != ver_id]
        if meta["versions"]:
            self._save_json(self._meta_path(fid), meta)
            self._update_index_entry(meta)
        else:
            # 版本删光 → 记录目录只剩 meta.json，作为"残壳"挂到上面的条目上，
            # 不再单列一条（否则回收站里会出现一条 0 版本的记录）。
            # 落盘空 versions 再搬：否则残壳里还留着"已经不在目录里的版本项"，
            # 它一旦被重新识别成条目/被还原，就会指向幽灵版本（打开即报错）。
            meta["versions"] = []
            try:
                self._save_json(self._meta_path(fid), meta)
            except OSError:
                pass
            shell = self._move_to_trash(self.files_dir / fid, "rec",
                                        register=False)
            if shell is not None and entry is not None:
                self._trash_attach_extra(entry.get("id"), shell)
            self._remove_index_entry(fid)
        return True, ""

    def delete_file_record(self, fid):
        """删除整个文件记录（含全部快照），移入 _trash。"""
        fdir = self.files_dir / fid
        if fdir.exists():
            meta = self._load_meta(fid) or {}
            versions = [v for v in (meta.get("versions") or [])
                        if isinstance(v, dict)]
            latest = max((str(v.get("time") or "") for v in versions),
                         default="")
            moved = self._move_to_trash(fdir, "rec",
                                        extra={"fid": fid,
                                               "name": meta.get("name",
                                                                fdir.name),
                                               "category": meta.get("category"),
                                               "latest_time": latest,
                                               "version_count": len(versions)})
            if moved is None and fdir.exists():
                # 记录目录还在 → 移入回收站失败：保留索引，绝不"假装删掉了"
                raise OSError("移入回收站失败（文件被占用或权限不足）")
        self._remove_index_entry(fid)
        return True

    def copy_file(self, fid):
        """库内复制（R6）：以最新版快照为唯一版本新建记录，继承分类。
        同分类重名自动顺延「xxx - 副本.ext」「xxx - 副本(2).ext」…——
        复制是显式操作，无需弹窗。不产生任何库外磁盘文件。"""
        meta = self.load_meta(fid)
        if meta is None:
            raise ValueError("文件记录不存在")
        latest = self.latest_version(meta)
        if latest is None:
            raise ValueError("该文件没有任何版本，无法复制")
        src_snapshot = self.files_dir / fid / latest["id"]
        if not src_snapshot.is_file():
            raise FileNotFoundError("最新版本的快照文件丢失，请检查版本库目录")
        cat = meta.get("category")
        old_name = meta.get("name") or "未命名"
        suffix = Path(old_name).suffix
        # 命名规则与「回收站还原」共用（_unique_name_in_category）
        cand = self._unique_name_in_category(cat, old_name, "副本")
        new_fid = self._free_fid(self._file_id(cand))
        fdir = self.files_dir / new_fid
        fdir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        seq = 1
        while True:
            vfile = f"{now:%Y%m%d_%H%M%S}_{seq}{suffix}"
            if not (fdir / vfile).exists():
                break
            seq += 1
        _copy2_writable(src_snapshot, fdir / vfile)
        try:
            digest = _safe_sha256(src_snapshot)     # 与快照字节相同
        except Exception:
            digest = ""
        new_meta = {
            "fid": new_fid, "name": cand, "category": cat,
            "versions": [{
                "id": vfile,
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "reason": f"复制自「{old_name}」的最新版本",
                "source": "", "size": src_snapshot.stat().st_size,
                "auto": False, "sha256": digest, "star": False,
            }],
        }
        self._save_json(self._meta_path(new_fid), new_meta)
        self._update_index_entry(new_meta)
        return new_meta

    # ---------- 导出 ----------
    def save_version_as(self, meta, ver, dest):
        _copy2_writable(self.version_file(meta, ver), dest)

    def latest_version(self, meta):
        """返回"最新"的一条版本（按 time 取最大；无版本返回 None）。

        为什么不能直接 `versions[-1]`：回收站还原会把**旧版本**补回 versions
        （见 _restore_version_file），"追加顺序 == 时间顺序"这条不变量不再成立。
        而列表/详情显示的时间走的是 max(time)（_index_entry）——两边必须同口径，
        否则"打开（编辑最新版本）/创建副本/并入"会静默用旧版本的内容。
        同一秒内多条时取**后追加**的那条（与原实现口径一致）。
        """
        versions = meta.get("versions", []) or []
        if not versions:
            return None
        best = 0
        for i, v in enumerate(versions):
            if str(v.get("time") or "") >= str(versions[best].get("time") or ""):
                best = i
        return versions[best]

    # ---------- R7：编辑会话工作目录 ----------
    @property
    def work_dir(self):
        """编辑会话工作目录 <版本库>/work（不进备份、不参与迁移、不受 C12 清理）。"""
        return self.store_dir / "work"

    def sessions_file(self):
        """编辑会话持久化文件 <版本库>/work/sessions.json。"""
        return self.work_dir / "sessions.json"

    def work_copy_path(self, fid, ver_id, name):
        """work/<fid>/<ver_id>/<原名> 结构化目录：重启可按结构精确反查会话。"""
        d = self.work_dir / fid / ver_id
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def export_edit_copy(self, meta, ver=None):
        """R7：把该版本快照复制到库下 work/ 编辑工作目录并返回路径。
        不再写 %TEMP%（pjm_lib_* 仅剩对比链路兼容用途，见 _cleanup_temp_copies）。
        复制是字节级 copy2（字节级复制，落盘后清除只读位，见 _copy2_writable）；
        不 startfile —— 打开动作由 App 层做，
        便于失败处理与会话登记先后可控。ver 为 None 时取最新版本。"""
        if ver is None:
            ver = self.latest_version(meta)
        if ver is None:
            raise ValueError("该文件没有任何版本")
        dest = self.work_copy_path(meta["fid"], ver["id"], meta.get("name", ""))
        _copy2_writable(self.version_file(meta, ver), dest)
        return dest

    def load_edit_sessions(self):
        """读取编辑会话表；损坏/缺失一律返回空 dict。"""
        data = self._load_json(self.sessions_file(), {})
        return data if isinstance(data, dict) else {}

    def save_edit_sessions(self, sessions):
        """sessions: {key: {...}}；key = f"{fid}|{ver_id}"。原子写。
        持久化失败不致命：重启兜底还能按 work 目录结构反查。"""
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            self._save_json(self.sessions_file(), sessions)
        except OSError:
            pass

    def delete_work_dir(self, fid, ver_id=None):
        """删除编辑工作副本目录 work/<fid>/[<ver_id>/]（尽力而为，不抛错）。
        ver_id 为 None 时删除该 fid 的整个 work 子目录（删除记录时用）；
        ver 级删除后若 fid 目录已空，一并移除（保持 work 干净）。"""
        target = (self.work_dir / fid if ver_id is None
                  else self.work_dir / fid / ver_id)
        try:
            shutil.rmtree(target, ignore_errors=True)
        except OSError:
            pass
        if ver_id is not None:
            try:
                (self.work_dir / fid).rmdir()      # 仅空目录会成功
            except OSError:
                pass

    def export_backup(self, dest_zip):
        """把整个版本库（跳过 _trash 与 work 编辑工作目录）打包成 zip。"""
        dest_zip = Path(dest_zip)
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(self.store_dir):
                rp = Path(root)
                if "_trash" in rp.parts or "work" in rp.parts:
                    continue
                dirs[:] = [d for d in dirs if d not in ("_trash", "work")]
                for fn in files:
                    fp = rp / fn
                    try:
                        z.write(fp, str(fp.relative_to(self.store_dir)
                                        ).replace("\\", "/"))
                    except OSError:
                        continue
        return dest_zip
def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:10]
