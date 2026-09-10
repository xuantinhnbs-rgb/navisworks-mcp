"""
Chụp ảnh cửa sổ Navisworks
===========================
COM API có hàm CreatePicture nhưng trên Navisworks 2026 nó ném "Catastrophic
failure" ở mọi biến thể tham số, kể cả khi cửa sổ đang hiện - đã đo, không dùng
được. Vì vậy ảnh được chụp từ chính cửa sổ Roamer.exe qua GDI.

Hai điểm dễ sai, đã xử lý sẵn:
  * DPI: không khai báo DPI-aware thì Windows trả về kích thước cửa sổ đã bị co
    theo tỉ lệ hiển thị, ảnh ra thiếu một phần bên phải/dưới.
  * Vùng vẽ 3D của Navisworks do GPU dựng. BitBlt thường ra ô đen; PrintWindow
    với cờ PW_RENDERFULLCONTENT mới lấy được nội dung. Giữ cả hai đường và tự
    kiểm tra kết quả để chọn đường cho ảnh không đen.
"""

from __future__ import annotations

import ctypes
import os
import time
from typing import Any, Dict, Optional

import win32con
import win32gui
import win32process
import win32ui
from PIL import Image

PW_RENDERFULLCONTENT = 0x00000002
NAVISWORKS_EXE = "roamer.exe"


class ScreenshotError(Exception):
    """Không chụp được ảnh, kèm lý do đọc được."""


def _set_dpi_aware() -> None:
    """Bắt buộc trước mọi phép đo cửa sổ, nếu không kích thước trả về bị co lại."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _process_name(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # LIMITED_INFO
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def find_navisworks_window() -> Optional[int]:
    """Tìm cửa sổ chính của Navisworks đang hiện trên màn hình."""
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.GetParent(hwnd):
            return
        if _process_name(hwnd) != NAVISWORKS_EXE:
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        found.append((hwnd, (right - left) * (bottom - top)))

    win32gui.EnumWindows(visit, None)
    if not found:
        return None
    found.sort(key=lambda item: item[1], reverse=True)      # cửa sổ chính là cái to nhất
    return found[0][0]


def _grab(hwnd: int, use_print_window: bool) -> Image.Image:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ScreenshotError("Cửa sổ Navisworks có kích thước bằng 0 (đang thu nhỏ?).")

    window_dc = win32gui.GetWindowDC(hwnd)
    src_dc = win32ui.CreateDCFromHandle(window_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(src_dc, width, height)
    mem_dc.SelectObject(bitmap)
    try:
        if use_print_window:
            ok = ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(),
                                                  PW_RENDERFULLCONTENT)
            if not ok:
                raise ScreenshotError("PrintWindow thất bại.")
        else:
            mem_dc.BitBlt((0, 0), (width, height), src_dc, (0, 0), win32con.SRCCOPY)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                                bits, "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        mem_dc.DeleteDC()
        src_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)


def _looks_blank(image: Image.Image) -> bool:
    """Ảnh gần như một màu = vùng 3D chưa được vẽ vào DC."""
    small = image.resize((32, 32))
    colors = small.getcolors(32 * 32) or []
    if not colors:
        return False
    dominant = max(count for count, _ in colors)
    return dominant > (32 * 32) * 0.98


def capture(output_path: str, bring_to_front: bool = True,
            settle_seconds: float = 0.6) -> Dict[str, Any]:
    """Chụp cửa sổ Navisworks ra file PNG, trả về đường dẫn và kích thước ảnh."""
    _set_dpi_aware()
    hwnd = find_navisworks_window()
    if hwnd is None:
        raise ScreenshotError(
            "Không thấy cửa sổ Navisworks nào đang hiện. Gọi show_navisworks_window "
            "với visible=true trước khi chụp."
        )
    if bring_to_front:
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass                       # Windows có thể từ chối; vẫn chụp được
        time.sleep(settle_seconds)

    resolved = os.path.abspath(os.path.expanduser(output_path))
    folder = os.path.dirname(resolved)
    if folder and not os.path.isdir(folder):
        raise ScreenshotError(f"Thư mục đích không tồn tại: {folder}")
    if not resolved.lower().endswith(".png"):
        resolved += ".png"

    image = _grab(hwnd, use_print_window=True)
    method = "PrintWindow"
    if _looks_blank(image):                    # GPU chưa đổ nội dung -> thử BitBlt
        fallback = _grab(hwnd, use_print_window=False)
        if not _looks_blank(fallback):
            image, method = fallback, "BitBlt"

    image.save(resolved, "PNG")
    if not os.path.isfile(resolved):
        raise ScreenshotError(f"Lưu ảnh thất bại: {resolved}")
    return {
        "file": resolved,
        "width": image.width,
        "height": image.height,
        "method": method,
        "size_bytes": os.path.getsize(resolved),
        "blank_warning": _looks_blank(image),
    }
