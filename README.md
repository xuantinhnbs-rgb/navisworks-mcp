# navisworks-mcp

[![CI](https://github.com/xuantinhnbs-rgb/navisworks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/xuantinhnbs-rgb/navisworks-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#c%C3%A0i-%C4%91%E1%BA%B7t)

Điều khiển Autodesk Navisworks trực tiếp từ AI qua Model Context Protocol.

Kiểm chứng trên **Navisworks Manage 2026** (Roamer 23.3.1460.83), Python 3.14,
Windows 10. Toàn bộ 36 phép thử end-to-end chạy trên mô hình thật đều PASS.

## Cách nó nói chuyện với Navisworks

Navisworks đăng ký một COM server ngoài tiến trình:

```
HKLM\SOFTWARE\Classes\Navisworks.Document.23\CLSID
  -> LocalServer32 = C:\Program Files\Autodesk\Navisworks Manage 2026\Roamer.exe
```

Từ đó lấy được **toàn bộ** COM API chứ không chỉ vài lệnh mở/lưu file:

```python
doc   = win32com.client.Dispatch("Navisworks.Document.23")
state = doc.State          # InwOpState10: cây đối tượng, thuộc tính, tìm kiếm,
                           # vùng chọn, tô màu, ẩn/hiện, viewpoint...
```

Không cần viết add-in .NET, không cần biên dịch gì. Server tự **bám vào bản
Navisworks đang mở** nếu có (`GetActiveObject`), nếu chưa có thì khởi động một bản
ở chế độ ẩn.

## Yêu cầu

- Windows
- Autodesk Navisworks (Manage hoặc Simulate) — kiểm chứng trên **2026**, các bản
  2022–2025 kết nối qua ProgID tương ứng trong `PROG_IDS` nhưng chưa kiểm chứng
- Python 3.10 trở lên

## Cài đặt

```powershell
git clone https://github.com/xuantinhnbs-rgb/navisworks-mcp.git
cd navisworks-mcp
pip install -r requirements.txt
python test_connection.py          # tự tìm một file .nwd/.nwc trên máy để kiểm thử
```

Khai báo server trong file cấu hình MCP của bạn (thay `<ĐƯỜNG-DẪN>` bằng nơi vừa
clone về, và `<PYTHON>` bằng đường dẫn tới python.exe):

```json
{
  "mcpServers": {
    "navisworks": {
      "command": "<PYTHON>/python.exe",
      "args": ["<ĐƯỜNG-DẪN>/navisworks-mcp/server.py"],
      "cwd": "<ĐƯỜNG-DẪN>/navisworks-mcp",
      "env": { "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

`PYTHONIOENCODING=utf-8` không phải tùy chọn: console Windows mặc định là cp1252 và
mọi thông điệp tiếng Việt sẽ làm server chết vì `UnicodeEncodeError`.

## Định danh đối tượng

Đối tượng được đánh địa chỉ bằng **chuỗi chỉ mục 1-based** tính từ gốc mô hình:

```
""                 gốc mô hình (cả file)
"1"                con thứ nhất của gốc
"1/1/1/2/1/1/1"    đi 7 tầng xuống
```

Đây chính là `InwOaPath.ArrayData` của Navisworks, chuyển hai chiều được. Lấy id từ
`get_model_tree`, `find_objects` hoặc `get_selection` — đừng tự bịa.

Mô hình xuất từ Revit/IFC có cây điển hình:

```
File > Assembly > IfcSite > IfcBuilding > IfcBuildingStorey > Category > Family
     > Instance > Mesh
```

## Danh sách tool

| Nhóm | Tool |
|---|---|
| Kết nối | `check_navisworks_connection`, `show_navisworks_window` |
| Tài liệu | `open_model`, `append_model`, `save_model_as`, `get_model_info` |
| Cây & thuộc tính | `get_model_tree`, `get_node_info`, `get_node_properties` |
| Tìm kiếm | `find_objects` |
| Vùng chọn | `get_selection`, `select_objects`, `clear_selection` |
| Hiển thị | `set_color`, `set_transparency`, `reset_appearance`, `hide_objects`, `isolate_objects`, `show_all_objects` |
| Góc nhìn | `zoom_to_objects`, `list_saved_views`, `apply_saved_view`, `list_selection_sets` |
| Ảnh | `capture_screenshot` |

Mọi tool trả về JSON có khóa `ok`. Lỗi ra `{"ok": false, "error": "..."}` bằng tiếng
Việt, không bao giờ ném ngoại lệ COM thô.

## Hiệu năng: đọc trước khi truy vấn lớn

Mỗi trường trong một kết quả là một chuyến gọi COM liên tiến trình. Đo trên máy này:

| Điều kiện | Chi phí mỗi đối tượng |
|---|---|
| Cửa sổ ẩn, `detail="basic"` | ~19 ms |
| Cửa sổ ẩn, `detail="full"` | ~26 ms |
| **Cửa sổ đang hiện**, `detail="basic"` | **~200 ms** |

Cửa sổ hiện làm mỗi lời gọi kéo theo một nhịp vẽ lại giao diện, đắt gấp 5–10 lần.
Vì vậy: **truy vấn hàng loạt thì ẩn cửa sổ, chỉ hiện khi cần nhìn hoặc chụp ảnh.**
`find_objects` mặc định `detail="basic"`; cần chi tiết một đối tượng thì gọi
`get_node_info` cho riêng nó.

## Ba hành vi dễ hiểu nhầm của Navisworks

**1. Tìm kiếm phân biệt hoa thường theo mặc định của Navisworks.** Server đặt
`case_sensitive=False` làm mặc định, vì tên cấu kiện cầu đường hầu hết viết hoa
(`TAM PANEL...`). Tìm `"panel"` với `case_sensitive=True` trả về 0 kết quả trong khi
`"PANEL"` trả về 374.

**2. Kết quả tìm kiếm bị gộp về node cha.** Navisworks mặc định "disjoint": khớp
được một node thì con cháu của nó không liệt kê riêng. Tìm type chứa `"Ifc"` vì thế
ra đúng **1** dòng (IfcSite — tổ tiên của mọi thứ) thay vì 779. Server tắt gộp theo
mặc định; bật lại bằng `only_topmost_match=True`.

**3. `isolate_objects` phải tự tính phần bù.** `InwOpSelection.Invert()` không cho
phần bù theo cây: gọi nó trên một vùng chọn một node trả về **rỗng**, nên cách làm
"chọn rồi đảo rồi ẩn" sẽ báo thành công mà ẩn đúng 0 đối tượng. Server đi từ gốc và
ẩn mọi nhánh không phải tổ tiên cũng không phải con cháu của mục tiêu.

## Ba cạm bẫy pywin32 với API này

1. `doc.State` là **thuộc tính**, không phải hàm. `doc.State()` báo `Member not found`.
2. Thuộc tính có tham số phải gọi qua tiền tố `Set`/`Get`:
   `state.SetSelectionHidden(sel, True)`.
3. Con trỏ lấy qua `GetActiveObject` và qua `Dispatch` **không bind giống nhau**: cùng
   một `IsModified`, một bên là hàm, bên kia là `bool` sẵn. Đọc qua helper `_member`.

## Những thứ CHƯA làm được

Nói rõ để khỏi mất công thử:

- **Clash Detective**: chưa nối. Clash nằm ngoài `InwOpState10`, cần đi qua
  `Navisworks.Clash.Mfc.Interop` — chưa kiểm chứng nên không đưa vào.
- **TimeLiner / Quantification**: tương tự, chưa nối.
- **`state.CreatePicture`**: COM có hàm này nhưng trên Navisworks 2026 nó ném
  `Catastrophic failure` ở mọi biến thể tham số, kể cả khi cửa sổ đang hiện. Vì vậy
  `capture_screenshot` chụp thẳng cửa sổ Roamer qua GDI (`PrintWindow` với cờ
  `PW_RENDERFULLCONTENT`, dự phòng `BitBlt`), có tự phát hiện ảnh trắng/đen trơn.
- **`InwOaPath.Serialise`**: Navisworks trả về `Not implemented`, nên id dùng dãy chỉ
  mục thay vì chuỗi serialise.
- **Tạo/sửa selection set và viewpoint**: mới đọc và áp dụng, chưa tạo mới.

## Kiểm thử

```powershell
python test_connection.py                                  # tự tìm mô hình
python test_connection.py "D:\du_an\cau_super_t.nwd"       # chỉ định mô hình
```

Script chạy thật 36 thao tác trên mô hình thật, gồm cả các phép thử **âm** (id sai,
màu ngoài khoảng, đuôi file sai phải báo lỗi) và một phép thử ngữ nghĩa: cô lập mà ẩn
0 nhánh bị tính là FAIL, vì đó là kiểu hỏng "báo ok nhưng màn hình không đổi".

## Phát triển

```powershell
pip install -r requirements-dev.txt
ruff check .        # lint
pytest              # 30 test, KHÔNG cần Navisworks được cài
```

`tests/` chạy được trên máy không có Navisworks vì client kết nối lazy — việc đăng ký
tool không chạm vào COM. Phần cần Navisworks thật nằm ở `test_connection.py`, chạy
thủ công.

## Giấy phép

[MIT](LICENSE) © 2026 Xuân Tình
