"""
Navisworks MCP Server
======================
Giao tiếp chuẩn Model Context Protocol (MCP) để AI điều khiển trực tiếp Autodesk
Navisworks. Kiểm chứng trên Navisworks Manage 2026; bản cũ hơn kết nối được qua
ProgID COM tương ứng (xem PROG_IDS trong navisworks_client.py).

Hợp đồng trả về: MỌI tool đều trả về một object JSON có khóa "ok".
  * Thành công -> {"ok": true, ...dữ liệu...}
  * Thất bại   -> {"ok": false, "error": "<thông điệp tiếng Việt nói rõ cách khắc phục>"}
Không tool nào ném ngoại lệ ra ngoài, nên phía AI luôn nhận được phản hồi đọc được
thay vì một vệt lỗi COM thô.

Định danh đối tượng: chuỗi chỉ mục 1-based ngăn bởi '/', ví dụ "1/1/1/2/1", đếm từ
gốc mô hình xuống. Lấy id từ get_model_tree, find_objects hoặc get_selection.
"""

import functools
from typing import List, Optional

from mcp.server.mcpserver import MCPServer

from navisworks_client import NavisworksClient, NwError
from screenshot import ScreenshotError, capture

mcp = MCPServer(
    "Navisworks-MCP",
    instructions=(
        "Điều khiển Autodesk Navisworks trên máy này: mở/gộp/lưu mô hình, duyệt cây "
        "đối tượng, đọc thuộc tính IFC/Revit, tìm kiếm, chọn, tô màu, ẩn/hiện, "
        "cô lập, zoom và chụp ảnh cửa sổ.\n"
        "Gọi check_navisworks_connection trước tiên: nếu Navisworks chưa chạy, MCP sẽ "
        "tự khởi động một bản ẨN - muốn nhìn thấy thao tác thì gọi "
        "show_navisworks_window(visible=true).\n"
        "Đối tượng được định danh bằng chuỗi chỉ mục dạng '1/1/1/2/1' lấy từ "
        "get_model_tree, find_objects hoặc get_selection. Đừng tự bịa id.\n"
        "Mô hình lớn có hàng chục nghìn node: duyệt cây theo từng tầng bằng depth nhỏ "
        "(1-2) thay vì kéo cả cây, và dùng find_objects khi đã biết tên cần tìm."
    ),
)
nw = NavisworksClient()


def safe(fn):
    """Bọc một tool: không bao giờ ném lỗi, luôn trả về dict có khóa 'ok'."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        try:
            result = fn(*args, **kwargs)
        except (NwError, ScreenshotError) as exc:
            return {"ok": False, "error": str(exc)}
        except (ValueError, TypeError, KeyError) as exc:
            return {"ok": False, "error": f"Tham số không hợp lệ: {exc}"}
        except Exception as exc:                     # lưới an toàn cuối cùng
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        if isinstance(result, dict):
            return result if "ok" in result else {"ok": True, **result}
        if isinstance(result, list):
            return {"ok": True, "count": len(result), "items": result}
        return {"ok": True, "result": result}

    return wrapper


# ============================================================================
# Kết nối & tài liệu
# ============================================================================

@mcp.tool()
@safe
def check_navisworks_connection() -> dict:
    """Kiểm tra kết nối tới Navisworks: phiên bản, file đang mở, cửa sổ có hiện không.

    Nên gọi tool này đầu tiên. Nếu chưa có Navisworks nào chạy, MCP tự khởi động
    một bản ở chế độ ẩn và báo lại qua khóa launched_by_mcp.
    """
    return nw.get_status()


@mcp.tool()
@safe
def show_navisworks_window(visible: bool = True) -> dict:
    """Hiện hoặc ẩn cửa sổ Navisworks.

    :param visible: True = hiện cửa sổ (bắt buộc trước khi chụp ảnh), False = ẩn.
    """
    return nw.set_window_visible(visible)


@mcp.tool()
@safe
def open_model(file_path: str) -> dict:
    """Mở một mô hình vào Navisworks, thay thế mô hình đang mở.

    Nhận .nwd/.nwf/.nwc và cả định dạng gốc: .ifc, .rvt, .dwg, .dgn, .fbx, .stp...
    Sau khi mở, tool kiểm chứng lại tên file hiện hành nên báo "ok" nghĩa là mô
    hình đã thực sự nạp, không chỉ là lệnh được nhận.

    :param file_path: Đường dẫn tuyệt đối tới file mô hình.
    """
    return nw.open_model(file_path)


@mcp.tool()
@safe
def append_model(file_path: str) -> dict:
    """Gộp thêm một mô hình vào phiên hiện tại (giữ nguyên các mô hình đã mở).

    Dùng khi cần chồng nhiều bộ môn để kiểm tra va chạm hoặc đối chiếu.

    :param file_path: Đường dẫn tuyệt đối tới file cần gộp thêm.
    """
    return nw.append_model(file_path)


@mcp.tool()
@safe
def save_model_as(file_path: str) -> dict:
    """Lưu phiên hiện tại thành .nwd hoặc .nwf.

    .nwd đóng gói cả hình học (chia sẻ được độc lập); .nwf chỉ lưu tham chiếu tới
    các file gốc kèm viewpoint/selection set.

    :param file_path: Đường dẫn đích, đuôi phải là .nwd hoặc .nwf.
    """
    return nw.save_as(file_path)


@mcp.tool()
@safe
def get_model_info() -> dict:
    """Tổng quan mô hình: danh sách file đã nạp, số tam giác, hộp bao, số viewpoint,
    số selection set và trạng thái đã sửa đổi hay chưa."""
    return nw.get_model_info()


# ============================================================================
# Duyệt cây & thuộc tính
# ============================================================================

@mcp.tool()
@safe
def get_model_tree(object_id: str = "", depth: int = 2, max_nodes: int = 300) -> dict:
    """Duyệt cây đối tượng từ một nhánh xuống, trả về id để dùng cho các tool khác.

    Mô hình xuất từ Revit/IFC thường có cấu trúc:
    File > Assembly > IfcSite > IfcBuilding > IfcBuildingStorey > Category > Family >
    Instance > Mesh. Nên đi từng tầng với depth 1-2 thay vì kéo cả cây một lần.

    :param object_id: Nhánh gốc cần duyệt; chuỗi rỗng = gốc mô hình.
    :param depth: Số tầng con lấy thêm (0 = chỉ chính nhánh đó).
    :param max_nodes: Trần số node trả về, 1..5000. Vượt trần thì truncated = true.
    """
    return nw.get_model_tree(object_id, depth, max_nodes)


@mcp.tool()
@safe
def get_node_info(object_id: str) -> dict:
    """Thông tin một đối tượng: tên, kiểu, cờ nhóm/hình học, số con và hộp bao.

    :param object_id: Chuỗi chỉ mục dạng '1/1/1/2/1'.
    """
    return nw.get_node_info(object_id)


@mcp.tool()
@safe
def get_node_properties(object_id: str, category: Optional[str] = None) -> dict:
    """Đọc toàn bộ bảng thuộc tính của một đối tượng, gồm cả pset IFC và tham số Revit.

    :param object_id: Chuỗi chỉ mục dạng '1/1/1/2/1'.
    :param category: Lọc theo tên nhóm thuộc tính, khớp một phần và không phân biệt
        hoa thường (vd 'Element', 'Item', 'Material'). Bỏ trống = lấy hết.
    """
    return nw.get_node_properties(object_id, category)


@mcp.tool()
@safe
def find_objects(value: str, search_in: str = "name", condition: str = "contains",
                 property_category: Optional[str] = None,
                 property_name: Optional[str] = None,
                 case_sensitive: bool = False,
                 only_topmost_match: bool = False,
                 detail: str = "basic",
                 max_results: int = 200) -> dict:
    """Tìm đối tượng trong mô hình bằng bộ tìm kiếm gốc của Navisworks (nhanh hơn duyệt cây).

    :param value: Giá trị cần khớp, vd 'TAM PANEL' hoặc '*COT*' khi dùng wildcard.
    :param search_in: 'name' (tên đối tượng), 'type' (kiểu hiển thị như
        IfcBuildingElementProxy), hoặc 'internal_type'. Bỏ qua nếu đã truyền cặp
        property_category + property_name.
    :param condition: 'contains', 'equal', 'not_equal', 'wildcard', 'greater_than',
        'less_than', 'greater_or_equal', 'less_or_equal', 'has_property',
        'has_no_property', 'has_attribute', 'has_no_attribute', 'same_type'.
    :param property_category: Tên nội bộ của nhóm thuộc tính khi cần tìm theo một
        tham số bất kỳ, vd 'lcatfconsumer_Custom'. Lấy tên này từ get_node_properties
        (khóa internal_category).
    :param property_name: Tên nội bộ của thuộc tính, lấy từ get_node_properties
        (khóa internal_name). Phải đi kèm property_category.
    :param case_sensitive: True = phân biệt hoa thường. Mặc định False, vì tên đối
        tượng trong mô hình cầu đường thường viết hoa toàn bộ.
    :param only_topmost_match: True = khớp được node cha thì không liệt kê con cháu
        (hành vi mặc định của Navisworks). Mặc định False để trả về từng đối tượng.
    :param detail: 'basic' (id + tên + kiểu) hoặc 'full' (thêm cờ nhóm/hình học/lớp).
        Mỗi trường thêm là một chuyến gọi COM cho MỖI kết quả: 'full' đắt gấp khoảng
        hai lần. Cần chi tiết của một đối tượng cụ thể thì gọi get_node_info.
    :param max_results: Trần số kết quả trả về, 1..5000. total_matches vẫn báo tổng thật.
        Chi phí khoảng 40 ms/đối tượng khi cửa sổ Navisworks ẩn và ~200 ms khi cửa sổ
        đang hiện, nên xin 1000 kết quả kèm cửa sổ hiện là chờ vài phút.
    """
    return nw.find_objects(value, search_in, condition, property_category,
                           property_name, case_sensitive, only_topmost_match,
                           detail, max_results)


# ============================================================================
# Vùng chọn
# ============================================================================

@mcp.tool()
@safe
def get_selection(max_results: int = 200, detail: str = "basic") -> dict:
    """Đọc vùng chọn hiện tại trong Navisworks, kèm id của từng đối tượng.

    :param max_results: Trần số đối tượng liệt kê, tổng thật vẫn báo ở khóa count.
    :param detail: 'basic' (id + tên + kiểu) hoặc 'full' (thêm cờ nhóm/hình học/lớp).
    """
    return nw.get_selection(max_results, detail)


@mcp.tool()
@safe
def select_objects(object_ids: List[str]) -> dict:
    """Đặt vùng chọn theo danh sách id.

    :param object_ids: Danh sách chuỗi chỉ mục, vd ['1/1/1/2/1', '1/1/1/2/2'].
    """
    return nw.select_objects(object_ids)


@mcp.tool()
@safe
def clear_selection() -> dict:
    """Bỏ chọn toàn bộ."""
    return nw.clear_selection()


# ============================================================================
# Hiển thị
# ============================================================================

@mcp.tool()
@safe
def set_color(object_ids: List[str], red: float, green: float, blue: float) -> dict:
    """Tô đè màu cho các đối tượng (không sửa vật liệu gốc, reset_appearance là bỏ được).

    :param object_ids: Danh sách chuỗi chỉ mục.
    :param red: Thành phần đỏ, 0.0..1.0.
    :param green: Thành phần xanh lá, 0.0..1.0.
    :param blue: Thành phần xanh lam, 0.0..1.0.
    """
    return nw.set_color(object_ids, red, green, blue)


@mcp.tool()
@safe
def set_transparency(object_ids: List[str], transparency: float) -> dict:
    """Đặt độ trong suốt cho các đối tượng.

    :param object_ids: Danh sách chuỗi chỉ mục.
    :param transparency: 0.0 = đặc hoàn toàn, 1.0 = trong suốt hoàn toàn.
    """
    return nw.set_transparency(object_ids, transparency)


@mcp.tool()
@safe
def reset_appearance() -> dict:
    """Bỏ mọi ghi đè màu và độ trong suốt, trả hiển thị về vật liệu gốc."""
    return nw.reset_appearance()


@mcp.tool()
@safe
def hide_objects(object_ids: List[str], hidden: bool = True) -> dict:
    """Ẩn hoặc hiện lại các đối tượng chỉ định.

    :param object_ids: Danh sách chuỗi chỉ mục.
    :param hidden: True = ẩn, False = hiện lại đúng các đối tượng đó.
    """
    return nw.hide_objects(object_ids, hidden)


@mcp.tool()
@safe
def isolate_objects(object_ids: List[str]) -> dict:
    """Cô lập: chỉ hiện các đối tượng chỉ định, ẩn toàn bộ phần còn lại.

    Bỏ cô lập bằng show_all_objects.

    :param object_ids: Danh sách chuỗi chỉ mục.
    """
    return nw.isolate_objects(object_ids)


@mcp.tool()
@safe
def show_all_objects() -> dict:
    """Hiện lại toàn bộ đối tượng đang bị ẩn hoặc đang bị cô lập."""
    return nw.show_all_objects()


# ============================================================================
# Góc nhìn & ảnh
# ============================================================================

@mcp.tool()
@safe
def zoom_to_objects(object_ids: Optional[List[str]] = None) -> dict:
    """Zoom góc nhìn hiện tại vào các đối tượng, hoặc về toàn mô hình nếu bỏ trống.

    :param object_ids: Danh sách chuỗi chỉ mục; bỏ trống = zoom toàn mô hình.
    """
    return nw.zoom_to_objects(object_ids)


@mcp.tool()
@safe
def list_saved_views() -> dict:
    """Liệt kê các viewpoint đã lưu trong mô hình, kèm chỉ số và tên."""
    return nw.list_saved_views()


@mcp.tool()
@safe
def apply_saved_view(name_or_index: str) -> dict:
    """Áp dụng một viewpoint đã lưu lên góc nhìn hiện tại.

    :param name_or_index: Tên viewpoint, hoặc chỉ số lấy từ list_saved_views.
    """
    return nw.apply_saved_view(name_or_index)


@mcp.tool()
@safe
def list_selection_sets() -> dict:
    """Liệt kê các selection set (bộ chọn đã lưu) trong mô hình."""
    return nw.list_selection_sets()


@mcp.tool()
@safe
def capture_screenshot(output_path: str, bring_to_front: bool = True) -> dict:
    """Chụp cửa sổ Navisworks ra file PNG.

    Cửa sổ phải đang hiện - gọi show_navisworks_window(visible=true) trước. Kết quả
    có khóa blank_warning: nếu true nghĩa là ảnh gần như một màu, thường do vùng 3D
    chưa kịp dựng, hãy chờ một nhịp rồi chụp lại.

    :param output_path: Đường dẫn file PNG đích; thiếu đuôi .png sẽ tự thêm.
    :param bring_to_front: True = đưa cửa sổ Navisworks lên trước rồi mới chụp.
    """
    return capture(output_path, bring_to_front)


if __name__ == "__main__":
    mcp.run(transport="stdio")
