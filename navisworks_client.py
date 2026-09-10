"""
Navisworks COM Automation Client
=================================
Lớp giao tiếp COM tới Autodesk Navisworks. Phát triển và kiểm chứng trên
Navisworks Manage 2026 (ProgID Navisworks.Document.23); bản cũ hơn kết nối
được qua các ProgID trong PROG_IDS nhưng chưa kiểm chứng đầy đủ.

Đường đi kỹ thuật (đo trực tiếp trên máy, không suy đoán từ tài liệu):
    doc   = Dispatch("Navisworks.Document.23")   # LocalServer32 -> Roamer.exe
    state = doc.State                            # InwOpState10, TOÀN BỘ COM API

Nguyên tắc thiết kế:
  * Mọi thao tác COM chạy trên ĐÚNG MỘT luồng chuyên trách (xem _ComThread).
  * Lỗi COM thô được dịch sang NwError kèm thông điệp tiếng Việt nói rõ cách sửa.
  * Đối tượng được định danh bằng "chỉ mục đường dẫn" dạng "1/1/1/2/1" - dãy chỉ số
    1-based từ gốc partition xuống. Đây chính là InwOaPath.ArrayData, chuyển đổi
    hai chiều được và đọc được bằng mắt.

Ba cạm bẫy của pywin32 với API này, đã trả giá để biết:
  1. doc.State là THUỘC TÍNH, không phải hàm - doc.State() báo "Member not found".
  2. Thuộc tính có tham số phải gọi qua tiền tố Set/Get:
     st.SetSelectionHidden(sel, True), không phải st.SelectionHidden[sel] = True.
  3. Tìm kiếm (FindSpec) trả về 0 kết quả một cách IM LẶNG nếu thiếu selection
     làm phạm vi - phải seed bằng SelectAll() rồi mới FindAll() ra kết quả.
"""

from __future__ import annotations

import functools
import os
import queue
import threading
from typing import Any, Dict, List, Optional, Sequence

import pythoncom
import win32com.client
from win32com.client import VARIANT

# ProgID theo phiên bản: 23 = 2026, 22 = 2025, 21 = 2024, 20 = 2023, 19 = 2022.
PROG_IDS = (
    "Navisworks.Document.23",
    "Navisworks.Document.22",
    "Navisworks.Document.21",
    "Navisworks.Document.20",
    "Navisworks.Document.19",
    "Navisworks.Document",
)

# nwEFindCondition - lấy từ metadata của Autodesk.Navisworks.Interop.ComApi.dll
FIND_CONDITIONS = {
    "has_attribute": 1,
    "has_no_attribute": 2,
    "has_property": 3,
    "has_no_property": 4,
    "same_type": 5,
    "equal": 6,
    "not_equal": 7,
    "less_than": 8,
    "less_or_equal": 9,
    "greater_or_equal": 10,
    "greater_than": 11,
    "contains": 12,
    "wildcard": 13,
}

# nwESearchMode
SEARCH_MODE_ALL_PATHS = 3

# Cặp (category, property) nội bộ cho các kiểu tìm kiếm thông dụng.
SEARCH_FIELDS = {
    "name": ("LcOaNode", "LcOaSceneBaseUserName"),
    "type": ("LcOaNode", "LcOaSceneBaseClassUserName"),
    "internal_type": ("LcOaNode", "LcOaSceneBaseClassName"),
}

OPENABLE_SUFFIXES = (
    ".nwd", ".nwf", ".nwc", ".dwg", ".dxf", ".ifc", ".rvt", ".dgn",
    ".3ds", ".fbx", ".skp", ".stp", ".step", ".igs", ".iges", ".sat", ".obj",
)


class NwError(Exception):
    """Lỗi đã được diễn giải sang thông điệp thân thiện cho người dùng."""


class _ComThread:
    """Thực thi mọi thao tác COM trên ĐÚNG MỘT luồng chuyên trách.

    Máy chủ MCP chạy tool đồng bộ trong thread pool nên mỗi lần gọi có thể rơi vào
    một luồng khác nhau. COM lại đòi CoInitialize riêng cho từng luồng và cấm dùng
    con trỏ giao diện chéo luồng - hệ quả là lỗi "CoInitialize has not been called".
    Dồn hết về một luồng vừa khử triệt để lỗi đó, vừa tuần tự hóa các lời gọi tới
    Navisworks (bản thân Navisworks cũng chỉ xử lý một yêu cầu tại một thời điểm).
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="navisworks-com",
                                                daemon=True)
                self._thread.start()

    def _run(self) -> None:
        pythoncom.CoInitialize()
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                fn, args, kwargs, box, done = item
                try:
                    box.append((True, fn(*args, **kwargs)))
                except BaseException as exc:          # chuyển nguyên vẹn về luồng gọi
                    box.append((False, exc))
                finally:
                    done.set()
        finally:
            pythoncom.CoUninitialize()

    def call(self, fn, *args, **kwargs):
        self._ensure_started()
        box: List[tuple] = []
        done = threading.Event()
        self._queue.put((fn, args, kwargs, box, done))
        # Mở NWD lớn có thể mất nhiều phút; không đặt hạn chót ngắn ở đây.
        done.wait()
        ok, payload = box[0]
        if ok:
            return payload
        raise payload


def _on_com_thread(method):
    """Đẩy một phương thức của client sang luồng COM chuyên trách."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return self._thread.call(method, self, *args, **kwargs)
    return wrapper


def _translate(exc: BaseException) -> NwError:
    """Dịch lỗi COM thô sang thông điệp nói rõ người dùng phải làm gì."""
    text = str(exc)
    if "Not implemented" in text:
        return NwError("Navisworks không hỗ trợ thao tác này qua COM API.")
    if "Invalid argument" in text:
        return NwError("Navisworks từ chối tham số: kiểm tra lại id đối tượng hoặc "
                       "tên category/property.")
    if "Catastrophic failure" in text:
        return NwError("Navisworks gặp lỗi nội bộ khi thực hiện thao tác này "
                       "(thường do gọi tính năng cần giao diện đồ họa trong lúc "
                       "cửa sổ đang ẩn).")
    if "Type mismatch" in text:
        return NwError(f"Kiểu tham số không khớp với API Navisworks: {exc}")
    if "Unknown name" in text:
        return NwError(f"Phiên bản Navisworks này không có thành viên API đó: {exc}")
    return NwError(f"{type(exc).__name__}: {exc}")


class NavisworksClient:
    """Bọc COM API của Navisworks thành các thao tác trả về dữ liệu Python thuần."""

    def __init__(self) -> None:
        self._thread = _ComThread()
        self._doc = None
        self._launched_by_us = False

    # ------------------------------------------------------------------ kết nối

    def _connect(self):
        """Bám vào Navisworks đang chạy; nếu chưa có thì tự khởi động một bản mới."""
        last: Optional[BaseException] = None
        for prog_id in PROG_IDS:                       # ưu tiên bản đang mở sẵn
            try:
                doc = win32com.client.GetActiveObject(prog_id)
                self._launched_by_us = False
                return doc
            except Exception as exc:
                last = exc
        for prog_id in PROG_IDS:                       # không có thì khởi động
            try:
                doc = win32com.client.Dispatch(prog_id)
                self._launched_by_us = True
                return doc
            except Exception as exc:
                last = exc
        raise NwError(
            "Không kết nối được tới Navisworks. Kiểm tra: (1) Navisworks đã cài trên "
            "máy chưa, (2) Python đang chạy có cùng bitness (64-bit) với Navisworks, "
            f"(3) lỗi COM cuối cùng: {last}"
        )

    @staticmethod
    def _member(obj, name, default=None):
        """Đọc một thành viên COM không cần biết nó là thuộc tính hay phương thức.

        Con trỏ lấy qua GetActiveObject và qua Dispatch không bind giống nhau:
        cùng một IsModified, một bên là hàm, bên kia là bool sẵn. Gọi cứng một kiểu
        thì đường còn lại chết với 'bool' object is not callable.
        """
        try:
            value = getattr(obj, name)
        except Exception:
            return default
        if isinstance(value, (bool, int, float, str)) or value is None:
            return value
        try:
            return value()
        except Exception:
            return default

    def _doc_state(self):
        """Trả về (document, state), tự kết nối lại nếu con trỏ COM đã chết."""
        if self._doc is not None:
            try:
                _ = self._doc.State                    # phép thử rẻ nhất còn sống
            except Exception:
                self._doc = None
        if self._doc is None:
            self._doc = self._connect()
        return self._doc, self._doc.State

    # -------------------------------------------------------- tiện ích đường dẫn

    @staticmethod
    def _parse_id(object_id: str) -> List[int]:
        """'1/1/1/2' -> [1, 1, 1, 2]. Chuỗi rỗng = gốc mô hình."""
        text = str(object_id).strip().strip("/")
        if not text:
            return []
        try:
            parts = [int(p) for p in text.split("/")]
        except ValueError:
            raise NwError(f"id đối tượng không hợp lệ: {object_id!r}. "
                          "Định dạng đúng là dãy chỉ số 1-based ngăn bởi '/', ví dụ "
                          "'1/1/1/2/1'. Lấy id từ get_model_tree hoặc find_objects.")
        if any(p < 1 for p in parts):
            raise NwError(f"id đối tượng chứa chỉ số < 1: {object_id!r} (chỉ mục là 1-based).")
        return parts

    @staticmethod
    def _format_id(array_data) -> str:
        if not array_data:
            return ""
        return "/".join(str(int(i)) for i in array_data)

    def _make_path(self, state, object_id: str):
        path = state.ObjectFactory(state.GetEnum("eObjectType_nwOaPath"))
        indices = self._parse_id(object_id)
        if indices:
            path.ArrayData = indices
        return path

    def _selection_from_ids(self, state, object_ids: Sequence[str]):
        sel = state.ObjectFactory(state.GetEnum("eObjectType_nwOpSelection"))
        sel.SelectNone()
        paths = sel.Paths()
        for oid in object_ids:
            paths.Add(self._make_path(state, oid))
        return sel

    @staticmethod
    def _node_summary(node, object_id: str, full: bool = True) -> Dict[str, Any]:
        """Mô tả một node. Mỗi khóa thêm vào đây là một chuyến COM liên tiến trình.

        Đo trên máy: khoảng 4 ms/lời gọi khi cửa sổ Navisworks đang ẩn và ~20 ms khi
        cửa sổ đang hiện (mỗi lời gọi kéo theo một nhịp vẽ lại giao diện). Bảy thuộc
        tính của bản 'full' vì thế thành 40-200 ms mỗi đối tượng - đủ để một truy vấn
        200 kết quả mất từ 8 tới 40 giây. Bản rút gọn giữ đúng ba thứ cần để quyết
        định xem có cần đọc kỹ đối tượng đó không.
        """
        summary = {
            "id": object_id,
            "name": node.UserName,
            "type": node.ClassUserName,
        }
        if not full:
            return summary
        summary.update({
            "internal_type": node.ClassName,
            "is_group": bool(node.IsGroup),
            "is_geometry": bool(node.IsGeometry),
            "is_layer": bool(node.IsLayer),
            "is_instance": bool(node.IsInsert),
        })
        return summary

    @staticmethod
    def _bbox_dict(box) -> Optional[Dict[str, Any]]:
        try:
            if box.IsEmpty:
                return None
        except Exception:
            pass
        lo, hi = box.min_pos, box.max_pos
        mn = [lo.data1, lo.data2, lo.data3]
        mx = [hi.data1, hi.data2, hi.data3]
        return {
            "min": mn,
            "max": mx,
            "size": [mx[i] - mn[i] for i in range(3)],
            "center": [(mx[i] + mn[i]) / 2.0 for i in range(3)],
            "note": "Đơn vị theo mô hình gốc (mô hình xuất từ Revit thường là mm).",
        }

    @staticmethod
    def _py_value(value) -> Any:
        """Đổi giá trị COM sang kiểu JSON hóa được."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (tuple, list)):
            return [NavisworksClient._py_value(v) for v in value]
        return str(value)

    # ------------------------------------------------------------ trạng thái app

    @_on_com_thread
    def get_status(self) -> Dict[str, Any]:
        try:
            doc, state = self._doc_state()
            current = state.GetCurrentFilename()
            return {
                "ok": True,
                "connected": True,
                "product": state.GetProductInfo(),
                "window_visible": bool(self._member(doc, "Visible", False)),
                "launched_by_mcp": self._launched_by_us,
                "loaded_file_count": int(state.LoadedFileCount),
                "current_file": current or None,
                "has_model": bool(current),
                "modified": bool(self._member(doc, "IsModified", False)),
            }
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def set_window_visible(self, visible: bool) -> Dict[str, Any]:
        try:
            doc, _ = self._doc_state()
            doc.Visible = bool(visible)
            if visible:
                doc.StayOpen()          # giữ cửa sổ sống sau khi MCP nhả con trỏ COM
            return {"window_visible": bool(self._member(doc, "Visible", False))}
        except Exception as exc:
            raise _translate(exc)

    # ------------------------------------------------------------------ tài liệu

    @staticmethod
    def _check_readable(file_path: str) -> str:
        resolved = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.isfile(resolved):
            raise NwError(f"Không tìm thấy file: {resolved}")
        suffix = os.path.splitext(resolved)[1].lower()
        if suffix not in OPENABLE_SUFFIXES:
            raise NwError(
                f"Đuôi file {suffix or '(không có)'} không nằm trong danh sách Navisworks "
                f"mở được: {', '.join(OPENABLE_SUFFIXES)}"
            )
        return resolved

    @_on_com_thread
    def open_model(self, file_path: str) -> Dict[str, Any]:
        resolved = self._check_readable(file_path)
        try:
            doc, state = self._doc_state()
            doc.OpenFile(resolved)
        except Exception as exc:
            raise _translate(exc)
        # Gọi thành công KHÔNG chứng minh mô hình đã nạp - phải kiểm chứng độc lập.
        loaded = state.GetCurrentFilename() or ""
        if os.path.normcase(loaded) != os.path.normcase(resolved):
            raise NwError(
                f"Navisworks nhận lệnh mở nhưng file hiện hành vẫn là {loaded or '(trống)'}. "
                "Thường do file hỏng hoặc thiếu bộ đọc định dạng đó."
            )
        return {
            "file": resolved,
            "loaded_file_count": int(state.LoadedFileCount),
            "triangles": int(state.NumTriangles),
        }

    @_on_com_thread
    def append_model(self, file_path: str) -> Dict[str, Any]:
        resolved = self._check_readable(file_path)
        try:
            doc, state = self._doc_state()
            before = int(state.LoadedFileCount)
            doc.AppendFile(resolved)
            after = int(state.LoadedFileCount)
        except Exception as exc:
            raise _translate(exc)
        if after <= before:
            raise NwError(f"Navisworks không nạp thêm được {resolved} "
                          f"(số file đang mở vẫn là {after}).")
        return {"file": resolved, "loaded_file_count": after,
                "triangles": int(state.NumTriangles)}

    @_on_com_thread
    def save_as(self, file_path: str) -> Dict[str, Any]:
        resolved = os.path.abspath(os.path.expanduser(file_path))
        suffix = os.path.splitext(resolved)[1].lower()
        if suffix not in (".nwd", ".nwf"):
            raise NwError("Chỉ lưu được sang .nwd (đóng gói cả hình học) hoặc "
                          ".nwf (chỉ tham chiếu tới file gốc).")
        folder = os.path.dirname(resolved)
        if folder and not os.path.isdir(folder):
            raise NwError(f"Thư mục đích không tồn tại: {folder}")
        try:
            doc, _ = self._doc_state()
            doc.SaveAs(resolved)
        except Exception as exc:
            raise _translate(exc)
        if not os.path.isfile(resolved):
            raise NwError(f"Navisworks báo lưu xong nhưng không thấy file {resolved}.")
        return {"file": resolved, "size_bytes": os.path.getsize(resolved)}

    @_on_com_thread
    def get_model_info(self) -> Dict[str, Any]:
        try:
            doc, state = self._doc_state()
            count = int(state.LoadedFileCount)
            files = []
            for i in range(1, count + 1):
                part = state.LoadedFileFromNdx(i)
                files.append({"index": i, "name": part.UserName, "path": part.filename})
            return {
                "current_file": state.GetCurrentFilename() or None,
                "loaded_files": files,
                "triangles": int(state.NumTriangles),
                "bounding_box": self._bbox_dict(state.GetBoundingBox()),
                "saved_view_count": int(state.SavedViews().Count),
                "selection_set_count": int(state.SelectionSetsEx().Count),
                "modified": bool(self._member(doc, "IsModified", False)),
            }
        except Exception as exc:
            raise _translate(exc)

    # ------------------------------------------------------------- cây mô hình

    def _resolve_node(self, state, object_id: str):
        """Đi từ gốc partition xuống theo dãy chỉ số, trả về node COM."""
        indices = self._parse_id(object_id)
        node = state.CurrentPartition
        if node is None:
            raise NwError("Chưa có mô hình nào được mở trong Navisworks. "
                          "Gọi open_model trước.")
        for depth, i in enumerate(indices):
            if not node.IsGroup:
                raise NwError(f"id {object_id!r} không hợp lệ: nhánh tại mức {depth} "
                              "không có con.")
            children = node.Children()
            if i > int(children.Count):
                raise NwError(f"id {object_id!r} không hợp lệ: mức {depth} chỉ có "
                              f"{int(children.Count)} con, không có con thứ {i}.")
            node = children.Item(i)
        return node

    @_on_com_thread
    def get_model_tree(self, object_id: str = "", depth: int = 2,
                       max_nodes: int = 300) -> Dict[str, Any]:
        if depth < 0:
            raise NwError("depth phải >= 0.")
        if max_nodes < 1 or max_nodes > 5000:
            raise NwError("max_nodes phải nằm trong khoảng 1..5000.")
        try:
            _, state = self._doc_state()
            root = self._resolve_node(state, object_id)
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

        nodes: List[Dict[str, Any]] = []
        truncated = [False]
        base = self._parse_id(object_id)

        def walk(node, indices: List[int], level: int) -> None:
            if len(nodes) >= max_nodes:
                truncated[0] = True
                return
            entry = self._node_summary(node, self._format_id(indices))
            entry["depth"] = level
            if node.IsGroup:
                try:
                    entry["child_count"] = int(node.Children().Count)
                except Exception:
                    entry["child_count"] = None
            nodes.append(entry)
            if not node.IsGroup or level >= depth:
                return
            children = node.Children()
            for i in range(1, int(children.Count) + 1):
                if len(nodes) >= max_nodes:
                    truncated[0] = True
                    return
                walk(children.Item(i), indices + [i], level + 1)

        try:
            walk(root, base, 0)
        except Exception as exc:
            raise _translate(exc)
        return {"root_id": self._format_id(base), "depth": depth,
                "count": len(nodes), "truncated": truncated[0], "nodes": nodes}

    @_on_com_thread
    def get_node_info(self, object_id: str) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            node = self._resolve_node(state, object_id)
            info = self._node_summary(node, self._format_id(self._parse_id(object_id)))
            if node.IsGroup:
                info["child_count"] = int(node.Children().Count)
            try:
                info["bounding_box"] = self._bbox_dict(node.GetBoundingBox(True, True))
            except Exception:
                info["bounding_box"] = None
            return info
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def get_node_properties(self, object_id: str,
                            category: Optional[str] = None) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            if state.CurrentPartition is None:
                raise NwError("Chưa có mô hình nào được mở. Gọi open_model trước.")
            path = self._make_path(state, object_id)
            gui_node = state.GetGUIPropertyNode(path, True)
            groups = gui_node.GUIAttributes()
            wanted = category.strip().lower() if category else None
            out: List[Dict[str, Any]] = []
            for i in range(1, int(groups.Count) + 1):
                attr = groups.Item(i)
                display = attr.ClassUserName
                internal = attr.ClassName
                if wanted and wanted not in (display or "").lower() \
                        and wanted not in (internal or "").lower():
                    continue
                props = attr.Properties()
                items = []
                for j in range(1, int(props.Count) + 1):
                    p = props.Item(j)
                    items.append({"name": p.UserName, "internal_name": p.name,
                                  "value": self._py_value(p.value)})
                out.append({"category": display, "internal_category": internal,
                            "properties": items})
            return {"id": self._format_id(self._parse_id(object_id)),
                    "category_count": len(out), "categories": out}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    # -------------------------------------------------------------- tìm kiếm

    @_on_com_thread
    def find_objects(self, value: str, search_in: str = "name",
                     condition: str = "contains",
                     property_category: Optional[str] = None,
                     property_name: Optional[str] = None,
                     case_sensitive: bool = False,
                     only_topmost_match: bool = False,
                     detail: str = "basic",
                     max_results: int = 200) -> Dict[str, Any]:
        if condition not in FIND_CONDITIONS:
            raise NwError(f"condition không hợp lệ: {condition!r}. Chọn một trong: "
                          f"{', '.join(sorted(FIND_CONDITIONS))}")
        if max_results < 1 or max_results > 5000:
            raise NwError("max_results phải nằm trong khoảng 1..5000.")
        if detail not in ("basic", "full"):
            raise NwError("detail chỉ nhận 'basic' (id + tên + kiểu) hoặc 'full'.")
        if property_category and property_name:
            cat, prop = property_category, property_name
        else:
            if search_in not in SEARCH_FIELDS:
                raise NwError(f"search_in không hợp lệ: {search_in!r}. Chọn "
                              f"{', '.join(SEARCH_FIELDS)}, hoặc truyền cặp "
                              "property_category + property_name.")
            cat, prop = SEARCH_FIELDS[search_in]
        try:
            _, state = self._doc_state()
            if state.CurrentPartition is None:
                raise NwError("Chưa có mô hình nào được mở. Gọi open_model trước.")
            spec = state.ObjectFactory(state.GetEnum("eObjectType_nwOpFindSpec"))
            cond = state.ObjectFactory(state.GetEnum("eObjectType_nwOpFindCondition"))
            cond.SetAttributeNames(cat)
            cond.SetPropertyNames(prop)
            cond.Condition = FIND_CONDITIONS[condition]
            cond.ValueCaseSensitive = bool(case_sensitive)
            cond.value = VARIANT(pythoncom.VT_BSTR, str(value))
            spec.Conditions().Add(cond)
            spec.SearchMode = SEARCH_MODE_ALL_PATHS
            # Mặc định Navisworks gộp kết quả: khớp được node cha thì con cháu không
            # được liệt kê riêng. Tìm "Ifc" vì thế chỉ ra đúng 1 dòng (IfcSite) dù cả
            # cây đều khớp. Tắt gộp để trả về từng đối tượng một.
            spec.ResultDisjoint = bool(only_topmost_match)
            # Bắt buộc: không seed phạm vi thì FindAll trả về 0 mà không báo lỗi.
            scope = state.ObjectFactory(state.GetEnum("eObjectType_nwOpSelection"))
            scope.SelectAll()
            spec.selection = scope
            finder = state.ObjectFactory(state.GetEnum("eObjectType_nwOpFind"))
            finder.FindSpec = spec
            result = finder.FindAll()
            paths = result.Paths()
            total = int(paths.Count)
            items = []
            for i in range(1, min(total, max_results) + 1):
                path = paths.Item(i)
                nodes = path.Nodes()
                leaf = nodes.Item(int(nodes.Count))
                items.append(self._node_summary(leaf, self._format_id(path.ArrayData),
                                                full=(detail == "full")))
            return {"query": {"value": value, "condition": condition,
                              "category": cat, "property": prop,
                              "case_sensitive": bool(case_sensitive),
                              "only_topmost_match": bool(only_topmost_match)},
                    "total_matches": total, "returned": len(items),
                    "truncated": total > len(items), "objects": items}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    # ----------------------------------------------------------- vùng chọn

    @_on_com_thread
    def get_selection(self, max_results: int = 200,
                      detail: str = "basic") -> Dict[str, Any]:
        if detail not in ("basic", "full"):
            raise NwError("detail chỉ nhận 'basic' (id + tên + kiểu) hoặc 'full'.")
        try:
            _, state = self._doc_state()
            sel = state.CurrentSelection
            paths = sel.Paths()
            total = int(paths.Count)
            items = []
            for i in range(1, min(total, max_results) + 1):
                path = paths.Item(i)
                nodes = path.Nodes()
                leaf = nodes.Item(int(nodes.Count))
                items.append(self._node_summary(leaf, self._format_id(path.ArrayData),
                                                full=(detail == "full")))
            return {"count": total, "returned": len(items),
                    "truncated": total > len(items), "objects": items}
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def select_objects(self, object_ids: Sequence[str]) -> Dict[str, Any]:
        if not object_ids:
            raise NwError("Danh sách object_ids rỗng.")
        try:
            _, state = self._doc_state()
            sel = self._selection_from_ids(state, object_ids)
            state.CurrentSelection = sel
            return {"selected": int(state.CurrentSelection.Paths().Count)}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def clear_selection(self) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            sel = state.ObjectFactory(state.GetEnum("eObjectType_nwOpSelection"))
            sel.SelectNone()
            state.CurrentSelection = sel
            return {"selected": int(state.CurrentSelection.Paths().Count)}
        except Exception as exc:
            raise _translate(exc)

    # ------------------------------------------------------------- hiển thị

    @_on_com_thread
    def set_color(self, object_ids: Sequence[str],
                  red: float, green: float, blue: float) -> Dict[str, Any]:
        for name, v in (("red", red), ("green", green), ("blue", blue)):
            if not 0.0 <= float(v) <= 1.0:
                raise NwError(f"{name} phải nằm trong khoảng 0.0..1.0 (nhận {v}).")
        try:
            _, state = self._doc_state()
            sel = self._selection_from_ids(state, object_ids)
            vec = state.ObjectFactory(state.GetEnum("eObjectType_nwLVec3f"))
            vec.SetValue(float(red), float(green), float(blue))
            state.OverrideColor(sel, vec)
            return {"colored": len(list(object_ids)), "rgb": [red, green, blue]}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def set_transparency(self, object_ids: Sequence[str],
                         transparency: float) -> Dict[str, Any]:
        if not 0.0 <= float(transparency) <= 1.0:
            raise NwError("transparency phải nằm trong khoảng 0.0 (đặc) .. 1.0 (trong suốt).")
        try:
            _, state = self._doc_state()
            sel = self._selection_from_ids(state, object_ids)
            state.OverrideTransparency(sel, float(transparency))
            return {"objects": len(list(object_ids)), "transparency": float(transparency)}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def reset_appearance(self) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            state.OverrideResetAll()
            return {"message": "Đã bỏ mọi ghi đè màu và độ trong suốt."}
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def hide_objects(self, object_ids: Sequence[str], hidden: bool = True) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            sel = self._selection_from_ids(state, object_ids)
            state.SetSelectionHidden(sel, bool(hidden))
            return {"objects": len(list(object_ids)), "hidden": bool(hidden)}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    def _complement_ids(self, state, targets: Sequence[Sequence[int]]) -> List[str]:
        """Tập nhánh nhỏ nhất phủ kín mọi thứ KHÔNG nằm trên đường tới targets.

        InwOpSelection.Invert() không cho phần bù theo cây - gọi nó trên một vùng
        chọn 1 node trả về rỗng, tức "ẩn hết phần còn lại" sẽ ẩn đúng 0 đối tượng
        mà vẫn báo thành công. Vì vậy phần bù được tính tường minh ở đây: đi từ gốc,
        node nào không phải tổ tiên cũng không phải con cháu của target thì ẩn cả
        nhánh và không đi sâu thêm.
        """
        goals = [tuple(t) for t in targets]
        to_hide: List[str] = []

        def walk(node, idx: List[int]) -> None:
            here = tuple(idx)
            if here in goals:                                   # chính nó -> giữ nguyên
                return
            if any(g[:len(here)] == here for g in goals):        # tổ tiên -> đi tiếp
                if not node.IsGroup:
                    return
                children = node.Children()
                for i in range(1, int(children.Count) + 1):
                    walk(children.Item(i), idx + [i])
                return
            if any(here[:len(g)] == g for g in goals):            # con cháu -> giữ
                return
            to_hide.append(self._format_id(idx))                  # ngoài phạm vi -> ẩn

        walk(state.CurrentPartition, [])
        return to_hide

    @_on_com_thread
    def isolate_objects(self, object_ids: Sequence[str]) -> Dict[str, Any]:
        """Chỉ hiện các đối tượng chỉ định, ẩn toàn bộ phần còn lại."""
        ids = list(object_ids)
        if not ids:
            raise NwError("Danh sách object_ids rỗng.")
        targets = [self._parse_id(oid) for oid in ids]
        if any(not t for t in targets):
            raise NwError("Không cô lập được gốc mô hình (id rỗng): "
                          "gốc đã bao trùm mọi thứ nên không có gì để ẩn.")
        try:
            _, state = self._doc_state()
            if state.CurrentPartition is None:
                raise NwError("Chưa có mô hình nào được mở. Gọi open_model trước.")
            state.HiddenItemsResetAll()
            hide_ids = self._complement_ids(state, targets)
            if hide_ids:
                state.SetSelectionHidden(
                    self._selection_from_ids(state, hide_ids), True)
            sel = self._selection_from_ids(state, ids)
            state.CurrentSelection = sel
            return {"isolated": len(ids), "hidden_branches": len(hide_ids)}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def show_all_objects(self) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            state.HiddenItemsResetAll()
            state.RequiredItemsResetAll()
            return {"message": "Đã hiện lại toàn bộ đối tượng."}
        except Exception as exc:
            raise _translate(exc)

    # --------------------------------------------------------------- góc nhìn

    @_on_com_thread
    def zoom_to_objects(self, object_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            if object_ids:
                sel = self._selection_from_ids(state, object_ids)
                state.CurrentSelection = sel
                state.ZoomInCurViewOnSel(sel)
                return {"message": f"Đã zoom vào {len(list(object_ids))} đối tượng."}
            state.ViewAll()
            return {"message": "Đã zoom về toàn bộ mô hình."}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def list_saved_views(self) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            views = state.SavedViews()
            items = []
            for i in range(1, int(views.Count) + 1):
                v = views.Item(i)
                items.append({"index": i, "name": getattr(v, "name", None)})
            return {"count": len(items), "views": items}
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def apply_saved_view(self, name_or_index: Any) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            views = state.SavedViews()
            total = int(views.Count)
            if total == 0:
                raise NwError("Mô hình không có viewpoint nào đã lưu.")
            target = None
            if isinstance(name_or_index, int) or str(name_or_index).isdigit():
                idx = int(name_or_index)
                if not 1 <= idx <= total:
                    raise NwError(f"Chỉ số viewpoint ngoài phạm vi 1..{total}.")
                target = views.Item(idx)
            else:
                for i in range(1, total + 1):
                    v = views.Item(i)
                    if str(getattr(v, "name", "")).lower() == str(name_or_index).lower():
                        target = v
                        break
            if target is None:
                raise NwError(f"Không tìm thấy viewpoint tên {name_or_index!r}. "
                              "Gọi list_saved_views để xem danh sách.")
            state.ApplyView(target)
            return {"applied": getattr(target, "name", str(name_or_index))}
        except NwError:
            raise
        except Exception as exc:
            raise _translate(exc)

    @_on_com_thread
    def list_selection_sets(self) -> Dict[str, Any]:
        try:
            _, state = self._doc_state()
            sets = state.SelectionSetsEx()
            items = []
            for i in range(1, int(sets.Count) + 1):
                s = sets.Item(i)
                items.append({"index": i, "name": getattr(s, "name", None)})
            return {"count": len(items), "selection_sets": items}
        except Exception as exc:
            raise _translate(exc)
