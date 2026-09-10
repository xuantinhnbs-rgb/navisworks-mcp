"""
Hợp đồng của bề mặt tool mà AI nhìn thấy.
=========================================
Khác với test_repo_layout.py (đọc source bằng AST), nhóm này NẠP THẬT server và
hỏi MCP danh sách tool - tức là kiểm đúng thứ model nhận được: tên, mô tả, và
JSON schema sinh ra từ annotation. Một tool thiếu mô tả hay có schema sai kiểu
vẫn chạy được bằng tay nhưng model sẽ không biết khi nào nên gọi nó.

Cần Windows vì server.py import pywin32, nhưng KHÔNG cần Navisworks: client kết
nối lười, việc đăng ký tool không chạm vào COM.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Con số này là chốt chặn có chủ đích: thêm/bớt tool phải sửa nó, và khi sửa thì
# nhớ cập nhật bảng tool trong README.md lẫn README.vi.md (xem CONTRIBUTING.md).
EXPECTED_TOOL_COUNT = 24

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="server.py cần pywin32, chỉ có trên Windows"
)


@pytest.fixture(scope="module")
def tools():
    import server

    return asyncio.run(server.mcp.list_tools())


def test_dung_so_tool_nhu_tai_lieu(tools):
    assert len(tools) == EXPECTED_TOOL_COUNT


def test_moi_tool_deu_co_mo_ta(tools):
    """Mô tả chính là docstring - đó là thứ model đọc để quyết định gọi hay không."""
    thieu = [t.name for t in tools if not (t.description or "").strip()]
    assert not thieu, "tool thiếu mô tả: %s" % thieu


def test_moi_tool_co_input_schema_kieu_object(tools):
    for tool in tools:
        schema = tool.input_schema
        assert schema.get("type") == "object", tool.name
        assert isinstance(schema.get("properties", {}), dict), tool.name


def test_moi_tham_so_bat_buoc_deu_ton_tai_trong_properties(tools):
    """`required` trỏ vào một khóa không có trong `properties` là schema hỏng."""
    for tool in tools:
        schema = tool.input_schema
        properties = set(schema.get("properties", {}))
        for ten in schema.get("required", []):
            assert ten in properties, "%s: required '%s' không có trong properties" % (tool.name, ten)


def test_tool_nhan_object_id_dung_ten_tham_so(tools):
    """Định danh đối tượng chỉ có hai dạng tên: object_id (một) và object_ids (nhiều)."""
    theo_ten = {t.name: t for t in tools}
    for ten_tool in ("get_node_info", "get_node_properties", "get_model_tree"):
        assert "object_id" in theo_ten[ten_tool].input_schema["properties"], ten_tool
    for ten_tool in ("select_objects", "hide_objects", "isolate_objects", "set_color"):
        assert "object_ids" in theo_ten[ten_tool].input_schema["properties"], ten_tool


def test_server_khai_bao_instructions(tools):
    """instructions là chỗ duy nhất dặn model gọi check_navisworks_connection trước."""
    import server

    assert server.mcp.instructions
    assert "check_navisworks_connection" in server.mcp.instructions
