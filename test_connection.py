"""
Kiểm thử end-to-end Navisworks MCP
===================================
Chạy trực tiếp mọi thao tác của NavisworksClient trên một mô hình thật và in
PASS/FAIL cho từng cái. Không mock, không giả lập: mục đích là chứng minh đường
COM còn sống trên máy này, chứ không phải chứng minh code gọi đúng tên hàm.

    python test_connection.py                       # tự tìm file .nwc/.nwd để thử
    python test_connection.py "D:\\mo_hinh.nwd"      # chỉ định file
"""

from __future__ import annotations

import glob
import os
import sys
import tempfile
import time

from navisworks_client import NavisworksClient, NwError

# Console Windows mặc định là cp1252: mọi dòng tiếng Việt sẽ ném UnicodeEncodeError
# và giết script trước cả khi chạm tới Navisworks. Ép UTF-8 ngay từ đầu.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = 0, 0
FAILURES = []


def check(label, fn, show=True):
    """Chạy một thao tác, in kết quả rút gọn, đếm PASS/FAIL."""
    global PASS, FAIL
    start = time.time()
    try:
        result = fn()
    except Exception as exc:
        FAIL += 1
        FAILURES.append(f"{label}: {type(exc).__name__}: {exc}")
        print(f"  FAIL  {label}\n          {type(exc).__name__}: {exc}")
        return None
    PASS += 1
    elapsed = time.time() - start
    summary = ""
    if show and isinstance(result, dict):
        summary = ", ".join(
            f"{k}={v}" for k, v in list(result.items())[:4]
            if not isinstance(v, (list, dict))
        )
    print(f"  PASS  {label:<38} {elapsed:5.2f}s  {summary}")
    return result


def find_sample_model() -> str:
    """Tìm một mô hình bất kỳ trên máy để chạy thử."""
    roots = [
        os.path.expanduser(r"~\Desktop"),
        os.path.expanduser(r"~\Documents"),
        os.path.expanduser(r"~\Downloads"),
    ]
    for root in roots:
        for suffix in ("nwd", "nwf", "nwc"):
            hits = glob.glob(os.path.join(root, "**", f"*.{suffix}"), recursive=True)
            if hits:
                return hits[0]
    raise SystemExit(
        "Không tìm thấy file .nwd/.nwf/.nwc nào trên Desktop/Documents/Downloads.\n"
        "Chạy lại kèm đường dẫn: python test_connection.py \"D:\\mo_hinh.nwd\""
    )


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else find_sample_model()
    print(f"Mô hình dùng để kiểm thử: {model}\n")
    nw = NavisworksClient()

    print("[1] Kết nối và tài liệu")
    status = check("get_status", nw.get_status)
    if not status:
        print("\nKhông kết nối được Navisworks, dừng tại đây.")
        return 1
    check("open_model", lambda: nw.open_model(model))
    check("get_model_info", nw.get_model_info)

    print("\n[2] Duyệt cây")
    tree = check("get_model_tree (depth=3)", lambda: nw.get_model_tree("", 3, 200))
    leaf_id = None
    group_id = None
    if tree:
        for node in tree["nodes"]:
            if node["id"] and node["is_geometry"] and leaf_id is None:
                leaf_id = node["id"]
            if node["id"] and node["is_group"] and node["name"] and group_id is None:
                group_id = node["id"]
        print(f"        node hình học mẫu: {leaf_id} | node nhóm mẫu: {group_id}")
    target = leaf_id or group_id
    if target:
        check("get_node_info", lambda: nw.get_node_info(target))
        props = check("get_node_properties", lambda: nw.get_node_properties(target))
        if props:
            print(f"        {props['category_count']} nhóm thuộc tính: "
                  f"{[c['category'] for c in props['categories']][:6]}")
        check("get_node_properties (lọc)",
              lambda: nw.get_node_properties(target, "Item"))
    check("get_model_tree id sai -> phải lỗi",
          lambda: _expect_error(lambda: nw.get_model_tree("9/9/9/9", 1)))

    print("\n[3] Tìm kiếm")
    # Tìm theo một chữ cái để chắc chắn có kết quả trên bất kỳ mô hình nào.
    found = check("find_objects contains 'a'",
                  lambda: nw.find_objects("a", "name", "contains", max_results=5))
    if found:
        print(f"        {found['total_matches']} kết quả, "
              f"mẫu: {[o['name'] for o in found['objects'][:3]]}")
    lower = check("find_objects không phân biệt hoa thường",
                  lambda: nw.find_objects("a", "name", "contains",
                                          case_sensitive=True, max_results=5))
    if found and lower:
        print(f"        không phân biệt hoa thường: {found['total_matches']} kết quả | "
              f"phân biệt: {lower['total_matches']} kết quả")
        if found["total_matches"] < lower["total_matches"]:
            print("  FAIL  tìm không phân biệt hoa thường lại ra ÍT hơn có phân biệt")
    typed = check("find_objects theo type",
                  lambda: nw.find_objects("Ifc", "type", "contains", max_results=5))
    topmost = check("find_objects only_topmost_match",
                    lambda: nw.find_objects("Ifc", "type", "contains",
                                            only_topmost_match=True, max_results=5))
    if typed and topmost:
        print(f"        mọi node khớp: {typed['total_matches']} | "
              f"chỉ node cao nhất: {topmost['total_matches']}")
    check("find_objects detail='full'",
          lambda: nw.find_objects("a", "name", "contains", detail="full", max_results=5))
    check("find_objects detail sai -> phải lỗi",
          lambda: _expect_error(lambda: nw.find_objects("a", detail="chi_tiet")))
    check("find_objects condition sai -> phải lỗi",
          lambda: _expect_error(lambda: nw.find_objects("x", condition="khong_co")))

    # Lấy các node SÂU nhất làm đối tượng thử. Kết quả tìm kiếm trả về theo thứ tự
    # cây nên vài dòng đầu luôn là gốc/tầng trên - thử cô lập trên chúng thì phần
    # bù rỗng một cách hợp lệ, che mất lỗi thật.
    deep = check("find_objects (lấy node sâu để thử)",
                 lambda: nw.find_objects("a", "name", "contains", max_results=300),
                 show=False)
    candidates = sorted((o["id"] for o in (deep or {}).get("objects", []) if o["id"]),
                        key=lambda s: s.count("/"), reverse=True)
    ids = candidates[:3]
    if not ids and target:
        ids = [target]
    print(f"        đối tượng dùng để thử: {ids}")

    print("\n[4] Vùng chọn")
    if ids:
        check("select_objects", lambda: nw.select_objects(ids))
        sel = check("get_selection", nw.get_selection)
        if sel:
            print(f"        đang chọn {sel['count']} đối tượng")
        check("clear_selection", nw.clear_selection)
    else:
        print("  SKIP  không có id nào để thử vùng chọn")

    print("\n[5] Hiển thị")
    if ids:
        check("set_color (đỏ)", lambda: nw.set_color(ids, 1.0, 0.0, 0.0))
        check("set_color giá trị sai -> phải lỗi",
              lambda: _expect_error(lambda: nw.set_color(ids, 5.0, 0.0, 0.0)))
        check("set_transparency", lambda: nw.set_transparency(ids, 0.5))
        check("reset_appearance", nw.reset_appearance)
        check("hide_objects", lambda: nw.hide_objects(ids, True))
        check("hide_objects (hiện lại)", lambda: nw.hide_objects(ids, False))
        iso = check("isolate_objects", lambda: nw.isolate_objects(ids))
        # Cô lập mà ẩn 0 nhánh là cô lập giả: báo ok nhưng màn hình không đổi.
        if iso is not None and iso.get("hidden_branches", 0) == 0:
            FAILURES.append("isolate_objects ẩn 0 nhánh -> cô lập không có tác dụng")
            print("  FAIL  isolate_objects ẩn 0 nhánh (cô lập không có tác dụng)")
        check("show_all_objects", nw.show_all_objects)
        check("isolate_objects id rỗng -> phải lỗi",
              lambda: _expect_error(lambda: nw.isolate_objects([""])))

    print("\n[6] Góc nhìn")
    if ids:
        check("zoom_to_objects", lambda: nw.zoom_to_objects(ids))
    check("zoom_to_objects (toàn mô hình)", lambda: nw.zoom_to_objects())
    check("list_saved_views", nw.list_saved_views)
    check("list_selection_sets", nw.list_selection_sets)

    print("\n[7] Lưu file")
    out_nwd = os.path.join(tempfile.gettempdir(), "navisworks_mcp_test.nwd")
    check("save_model_as (.nwd)", lambda: nw.save_as(out_nwd))
    check("save_model_as đuôi sai -> phải lỗi",
          lambda: _expect_error(lambda: nw.save_as(out_nwd.replace(".nwd", ".txt"))))
    # Navisworks giữ file .nwd vừa lưu đang mở, xoá ngay sẽ dính WinError 32.
    # File tạm không đáng để làm hỏng kết quả kiểm thử.
    try:
        os.remove(out_nwd)
    except OSError as exc:
        print(f"        (không xoá được file tạm, Navisworks đang giữ: {exc.strerror})")

    print("\n[8] Cửa sổ và ảnh chụp")
    check("show_navisworks_window(True)", lambda: nw.set_window_visible(True))
    time.sleep(3)                                  # chờ Navisworks dựng xong khung nhìn
    shot = os.path.join(tempfile.gettempdir(), "navisworks_mcp_test.png")
    try:
        from screenshot import capture
        result = check("capture_screenshot", lambda: capture(shot))
        if result and result.get("blank_warning"):
            print("        CẢNH BÁO: ảnh gần như một màu, vùng 3D có thể chưa dựng xong")
        try:
            os.remove(shot)
        except OSError:
            pass
    except ImportError as exc:
        print(f"  SKIP  capture_screenshot (thiếu thư viện: {exc})")

    print(f"\n{'='*62}\nTổng kết: {PASS} PASS, {len(FAILURES)} FAIL")
    for line in FAILURES:
        print(f"  - {line}")
    return 0 if not FAILURES else 1


def _expect_error(fn):
    """Xác nhận một lời gọi sai PHẢI báo lỗi - nếu nó im lặng thành công thì đó là bug."""
    try:
        fn()
    except NwError as exc:
        return {"đã báo lỗi đúng như mong đợi": str(exc)[:60]}
    raise AssertionError("Lời gọi sai lẽ ra phải báo lỗi nhưng lại thành công.")


if __name__ == "__main__":
    sys.exit(main())
