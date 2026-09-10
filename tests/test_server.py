"""
Test chạy được mà KHÔNG cần Navisworks cài trên máy.

Client kết nối lazy: khởi tạo NavisworksClient và đăng ký tool không chạm vào COM,
chỉ khi gọi một thao tác thật mới mở kết nối. Nhờ vậy CI kiểm được phần đông code -
định danh đối tượng, kiểm tra tham số, hợp đồng trả về - trên máy không có Navisworks.

Phần phải có Navisworks thật nằm ở test_connection.py, chạy thủ công.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from navisworks_client import FIND_CONDITIONS, NavisworksClient, NwError  # noqa: E402


class TestObjectId:
    """Chuỗi chỉ mục '1/1/2' là định danh đối tượng, phải chuyển hai chiều chính xác."""

    @pytest.mark.parametrize("text,expected", [
        ("", []),
        ("1", [1]),
        ("1/1/1/2/1", [1, 1, 1, 2, 1]),
        ("  1/2  ", [1, 2]),
        ("/1/2/", [1, 2]),
    ])
    def test_parse(self, text, expected):
        assert NavisworksClient._parse_id(text) == expected

    @pytest.mark.parametrize("array,expected", [
        ([], ""),
        ([1], "1"),
        ([1, 1, 2], "1/1/2"),
    ])
    def test_format(self, array, expected):
        assert NavisworksClient._format_id(array) == expected

    def test_round_trip(self):
        for text in ("", "1", "1/1/1/2/1/1/1"):
            indices = NavisworksClient._parse_id(text)
            assert NavisworksClient._format_id(indices) == text

    @pytest.mark.parametrize("bad", ["a", "1/x", "1//2", "-1", "0/1", "1.5"])
    def test_reject_invalid(self, bad):
        # Chỉ mục là 1-based: 0 và số âm là id sai, không phải id hợp lệ khác gốc.
        with pytest.raises(NwError):
            NavisworksClient._parse_id(bad)


class TestValueConversion:
    """Giá trị đọc từ COM phải JSON hóa được, nếu không tool sẽ vỡ lúc trả về."""

    def test_passes_primitives_through(self):
        for value in (None, "chuỗi", 1, 1.5, True):
            assert NavisworksClient._py_value(value) == value

    def test_recurses_into_sequences(self):
        assert NavisworksClient._py_value([1, "a", (2, 3)]) == [1, "a", [2, 3]]

    def test_stringifies_unknown_objects(self):
        class Ngay:
            def __str__(self):
                return "2026-09-10"

        assert NavisworksClient._py_value(Ngay()) == "2026-09-10"


class TestMemberAccessor:
    """Con trỏ COM lấy qua GetActiveObject và qua Dispatch không bind giống nhau."""

    def test_reads_plain_value(self):
        class Doc:
            IsModified = False

        assert NavisworksClient._member(Doc(), "IsModified", None) is False

    def test_calls_method_form(self):
        class Doc:
            def IsModified(self):
                return True

        assert NavisworksClient._member(Doc(), "IsModified", None) is True

    def test_falls_back_when_member_missing(self):
        assert NavisworksClient._member(object(), "KhongCo", "mac_dinh") == "mac_dinh"


class TestFileValidation:
    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(NwError, match="Không tìm thấy file"):
            NavisworksClient._check_readable(str(tmp_path / "khong_ton_tai.nwd"))

    def test_rejects_unsupported_suffix(self, tmp_path):
        path = tmp_path / "tai_lieu.docx"
        path.write_text("x", encoding="utf-8")
        with pytest.raises(NwError, match="không nằm trong danh sách"):
            NavisworksClient._check_readable(str(path))

    def test_accepts_supported_suffix(self, tmp_path):
        path = tmp_path / "mo_hinh.nwd"
        path.write_text("x", encoding="utf-8")
        assert NavisworksClient._check_readable(str(path)) == os.path.abspath(str(path))


class TestFindConditions:
    def test_covers_navisworks_enum_range(self):
        # Giá trị lấy từ metadata nwEFindCondition của Navisworks; lệch một con số
        # là tìm sai loại điều kiện mà không có lỗi nào báo ra.
        assert FIND_CONDITIONS["equal"] == 6
        assert FIND_CONDITIONS["contains"] == 12
        assert FIND_CONDITIONS["wildcard"] == 13
        assert set(FIND_CONDITIONS.values()) == set(range(1, 14))


@pytest.mark.skipif(sys.platform != "win32", reason="server.py cần pywin32, chỉ có trên Windows")
class TestServerContract:
    """Mọi tool phải trả về dict có khóa 'ok', kể cả khi bên trong ném lỗi."""

    def test_imports_without_navisworks_installed(self):
        import server

        assert server.mcp is not None

    def test_registers_expected_tools(self):
        import server

        expected = {
            "check_navisworks_connection", "show_navisworks_window",
            "open_model", "append_model", "save_model_as", "get_model_info",
            "get_model_tree", "get_node_info", "get_node_properties", "find_objects",
            "get_selection", "select_objects", "clear_selection",
            "set_color", "set_transparency", "reset_appearance",
            "hide_objects", "isolate_objects", "show_all_objects",
            "zoom_to_objects", "list_saved_views", "apply_saved_view",
            "list_selection_sets", "capture_screenshot",
        }
        missing = {name for name in expected if not callable(getattr(server, name, None))}
        assert not missing, f"thiếu tool: {sorted(missing)}"

    def test_safe_wrapper_converts_error_to_contract(self):
        import server

        @server.safe
        def no_ra_loi():
            raise NwError("hỏng có chủ đích")

        result = no_ra_loi()
        assert result["ok"] is False
        assert "hỏng có chủ đích" in result["error"]

    def test_safe_wrapper_never_leaks_exception(self):
        import server

        @server.safe
        def no_ra_loi_la():
            raise RuntimeError("lỗi không lường trước")

        assert no_ra_loi_la()["ok"] is False

    def test_safe_wrapper_wraps_success(self):
        import server

        @server.safe
        def tra_ve_dict():
            return {"gia_tri": 1}

        assert tra_ve_dict() == {"ok": True, "gia_tri": 1}
