"""
Kiểm tra bố cục repo và tính nhất quán của tài liệu.
====================================================
Những lỗi bắt ở đây là loại chỉ lộ ra khi người khác clone về: thiếu file tài
liệu, file cấu hình mẫu sai JSON hay thiếu biến môi trường, và - hay gặp nhất -
bảng tool trong README lệch với code sau khi thêm/bớt một tool.

Danh sách tool được đọc bằng AST từ chính server.py, KHÔNG import nó: nhờ vậy
nhóm test này chạy được trên mọi hệ điều hành, kể cả nơi không có pywin32.
"""

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "README.md",
    "README.vi.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "LICENSE",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "mcp.json.example",
    ".github/workflows/ci.yml",
    ".github/dependabot.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
]

# Tên tool trong bảng README nằm trong dấu backtick: `find_objects`.
TOOL_IN_DOCS = re.compile(r"`([a-z_]+)`")


def _tools_khai_bao_trong_source():
    """Tên mọi hàm mang decorator @mcp.tool() trong server.py, đọc bằng AST."""
    cay = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
    ten = []
    for node in cay.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "tool":
                ten.append(node.name)
                break
    return ten


def _tools_liet_ke_trong(duong_dan):
    """Tên tool xuất hiện trong bảng tool của một file README.

    Chỉ quét đúng mục "## Tools" / "## Danh sách tool": README còn nhiều bảng khác
    (hiệu năng, danh sách test) cũng dùng backtick, quét cả file sẽ bắt nhầm.
    """
    trong_bang = set()
    trong_muc = False
    for dong in (ROOT / duong_dan).read_text(encoding="utf-8").splitlines():
        if dong.startswith("## "):
            trong_muc = dong.strip() in ("## Tools", "## Danh sách tool")
            continue
        if trong_muc and dong.startswith("|") and "`" in dong:
            trong_bang.update(TOOL_IN_DOCS.findall(dong))
    if not trong_bang:
        raise AssertionError("%s: không tìm thấy bảng tool" % duong_dan)
    return trong_bang


@pytest.fixture(scope="module")
def tools_trong_source():
    return _tools_khai_bao_trong_source()


@pytest.mark.parametrize("ten_file", REQUIRED_FILES)
def test_file_bat_buoc_ton_tai(ten_file):
    assert (ROOT / ten_file).is_file(), "thiếu %s" % ten_file


def test_ten_tool_khong_trung_va_dung_snake_case(tools_trong_source):
    assert len(tools_trong_source) == len(set(tools_trong_source)), "có tool trùng tên"
    for ten in tools_trong_source:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", ten), ten


@pytest.mark.parametrize("readme", ["README.md", "README.vi.md"])
def test_bang_tool_trong_readme_khop_voi_source(readme, tools_trong_source):
    """Thêm tool mà quên cập nhật README (hoặc ngược lại) phải làm test đỏ."""
    trong_docs = _tools_liet_ke_trong(readme)
    thieu = set(tools_trong_source) - trong_docs
    thua = trong_docs - set(tools_trong_source)
    assert not thieu, "%s thiếu tool: %s" % (readme, sorted(thieu))
    assert not thua, "%s liệt kê tool không có thật: %s" % (readme, sorted(thua))


@pytest.mark.parametrize("readme", ["README.md", "README.vi.md"])
def test_so_tool_ghi_trong_readme_dung(readme, tools_trong_source):
    """Con số trong câu '24 tools' / '24 tool' cũng phải đi theo code."""
    noi_dung = (ROOT / readme).read_text(encoding="utf-8")
    so = re.search(r"(\d+)\s+tools?\b", noi_dung)
    assert so, "%s không ghi số lượng tool" % readme
    assert int(so.group(1)) == len(tools_trong_source)


def test_hai_readme_liet_ke_cung_mot_bo_tool():
    assert _tools_liet_ke_trong("README.md") == _tools_liet_ke_trong("README.vi.md")


def test_hai_readme_tro_ve_nhau():
    """Người đọc phải chuyển được ngôn ngữ từ bất kỳ bản nào."""
    assert "README.vi.md" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "README.md" in (ROOT / "README.vi.md").read_text(encoding="utf-8")


def test_file_cau_hinh_mau_dung_dinh_dang():
    with open(ROOT / "mcp.json.example", encoding="utf-8") as fh:
        cau_hinh = json.load(fh)

    servers = cau_hinh["mcpServers"]
    assert set(servers) == {"navisworks"}

    entry = servers["navisworks"]
    assert set(entry) >= {"command", "args", "cwd", "env"}
    assert entry["args"] and entry["args"][0].endswith("server.py")
    # stdio của MCP là văn bản UTF-8; thiếu hai biến này là gõ tiếng Việt ra rác.
    assert entry["env"].get("PYTHONIOENCODING") == "utf-8"
    assert entry["env"].get("PYTHONUNBUFFERED") == "1"


def test_khong_commit_duong_dan_rieng_cua_may_lap_trinh():
    """Đường dẫn thật trên máy tác giả lọt vào file mẫu là lỗi hay gặp khi publish."""
    noi_dung = (ROOT / "mcp.json.example").read_text(encoding="utf-8")
    assert "Users/Admin" not in noi_dung
    assert "Users\\Admin" not in noi_dung
