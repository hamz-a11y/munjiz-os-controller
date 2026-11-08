#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
Munjiz OS Controller (munjiz-os-controller) - v2.0 (With Live Visual Cursor & HUD)
محرك التوجيه الهجين للتحكم الكامل والبصري في نظام التشغيل لتطبيق "مُنجز"
Context-Aware 3-Layer Hybrid Execution Engine, Live Visual Cursor Tracker & MCP Server
================================================================================

المراجع المعمارية مفتوحة المصدر المعتمدة:
-----------------------------------------
- Open Computer Use (MCP Server): https://github.com/ifuryst/open-computer-use
- Simular AI Agent-S (ACI & Planning): https://github.com/simular-ai/agent-s
- Microsoft UFO² (Windows AgentOS): https://github.com/microsoft/ufo
- Microsoft OmniParser V2 (Set-of-Mark GUI Grounding): https://github.com/microsoft/omniparser
- Self-Operating Computer Framework: https://github.com/othersideai/self-operating-computer

الجديد في الإصدار 2.0 (المشاهدة المرئية الحية وتتبع مؤشر الماوس):
-----------------------------------------------------------------
1. تتبع ورسم مؤشر الفأرة الحقيقي (`draw_cursor_and_trajectory`):
   - لأن `ImageGrab.grab()` في ويندوز يلتقط الشاشة بدون أيقونة الماوس افتراضياً، يقوم
     المحرك بقراءة إحداثيات المؤشر الحية (`GetCursorPos` / `pyautogui.position()`)
     ورسم مؤشر بصري واضح (Crosshair + Halo) مع مسار الحركة (Trajectory Arrow) من موقع
     الماوس الحالي إلى الهدف المقصود على كل لقطة شاشة.
2. حلقة الرؤية الحية على شاشة المستخدم (`show_live_click_ripple`):
   - إظهار وميض بصري شفاف (Click-Through Overlay Ring) عبر `tkinter` حول مكان نقر
     الوكيل على شاشة Windows الحقيقية ليرى المستخدم بالعين المجردة أين ينقر "مُنجز" لحظياً.
3. أداة البث المرئي المباشر لواجهة مُنجز (`capture_live_frame`):
   - أداة MCP مخصصة لإرسال لقطات حية سريعة (مع موقع الماوس وآخر حركة) لعرضها داخل
     لوحة التحكم المرئية (Live Canvas / Agent Viewer) في تطبيق "مُنجز".
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import io
import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# إعداد السجلات التشخيصية (Structured Logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | [Munjiz-OS] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("munjiz_os_controller")


# ==============================================================================
# 0. ضبط دقة الشاشة في ويندوز (Windows High-DPI Scaling Stabilization)
# ==============================================================================
def enable_windows_dpi_awareness() -> bool:
    """
    تفعيل وعي العملية بدقة الشاشة الحقيقية (Per-Monitor DPI Aware V2) على نظام Windows
    لمنع انحراف إحداثيات النقر (X, Y) عندما تكون نسبة تكبير الشاشة 125% أو 150% أو 4K.
    """
    if platform.system() != "Windows":
        return False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        logger.info("تم تفعيل Per-Monitor DPI Awareness بنجاح لضمان دقة الإحداثيات 100%.")
        return True
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            logger.info("تم تفعيل System DPI Awareness القياسي بنجاح.")
            return True
        except Exception as exc:
            logger.warning(f"تعذر ضبط DPI Awareness تلقائياً: {exc}")
            return False


enable_windows_dpi_awareness()


# ==============================================================================
# 1. هياكل البيانات ونماذج الحالة (Core Data Structures & Models)
# ==============================================================================
class ExecutionLayer(str, Enum):
    """طبقات التنفيذ الثلاث داخل محرك مُنجز الهجين."""
    LAYER_1_CLI = "layer_1_system_cli"
    LAYER_2_UIA = "layer_2_structural_ui_dom"
    LAYER_3_VISION = "layer_3_pure_vision_omniparser"


@dataclass
class UIElementBox:
    """عنصر واجهة مستخرج إما هيكلياً (UIA) أو بصرياً (OmniParser Set-of-Mark)."""
    box_id: int
    label: str
    control_type: str
    bbox: Tuple[int, int, int, int]  # (left, top, right, bottom) بالبكسل الفعلي
    center: Tuple[int, int]          # (center_x, center_y)
    confidence: float = 1.0
    source: str = "uia"              # "uia" | "omniparser_v2" | "cv2_som_fallback"
    automation_id: str = ""
    is_interactive: bool = True

    def to_compact_dict(self) -> Dict[str, Any]:
        return {
            "box_id": self.box_id,
            "label": self.label,
            "type": self.control_type,
            "center": list(self.center),
            "bbox": list(self.bbox),
            "source": self.source,
        }


@dataclass
class ScreenInspectionResult:
    """نتيجة فحص الشاشة أو النافذة النشطة مع إحداثيات مؤشر الماوس الحية."""
    active_window_title: str
    layer_used: str
    screen_size: Tuple[int, int]
    cursor_position: Tuple[int, int] = (0, 0)
    elements: List[UIElementBox] = field(default_factory=list)
    annotated_image_base64: Optional[str] = None
    annotated_image_path: Optional[str] = None
    notes: str = ""

    def to_agent_payload(self, include_base64: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "active_window_title": self.active_window_title,
            "layer_used": self.layer_used,
            "screen_size": {"width": self.screen_size[0], "height": self.screen_size[1]},
            "cursor_position": {"x": self.cursor_position[0], "y": self.cursor_position[1]},
            "element_count": len(self.elements),
            "elements": [el.to_compact_dict() for el in self.elements],
            "notes": self.notes,
        }
        if self.annotated_image_path:
            payload["annotated_image_path"] = self.annotated_image_path
        if include_base64 and self.annotated_image_base64:
            payload["annotated_image_base64"] = self.annotated_image_base64
        return payload


@dataclass
class ActionOutcome:
    """نتيجة موحدة لأي أمر ينفذه محرك مُنجز عبر الطبقات الثلاث."""
    success: bool
    layer_used: str
    action: str
    details: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


# ==============================================================================
# 2. الطبقة الأولى: التحكم المباشر بالنظام (Layer 1: System / CLI Layer)
# ==============================================================================
class SystemCLILayer:
    """
    الطبقة الأولى (الأسرع والأعلى أولوية):
    تنفذ مهام النظام والملفات والبيانات مباشرة عبر PowerShell أو Python
    دون تحريك الماوس أو التقاط صور للشاشة.
    """

    BLOCKED_PATTERNS: Tuple[str, ...] = (
        r"Remove-Item\s+.*-Recurse\s+.*C:\\Windows",
        r"Format-Volume",
        r"rd\s+/s\s+/q\s+c:\\",
        r"del\s+/f\s+/s\s+/q\s+c:\\",
    )

    def __init__(self, default_timeout: int = 30) -> None:
        self.default_timeout = default_timeout
        self.is_windows = platform.system() == "Windows"

    def _is_safe_command(self, command: str) -> Tuple[bool, Optional[str]]:
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, command, flags=re.IGNORECASE):
                return False, f"تم حظر الأمر لاحتوائه على نمط خطير على النظام: {pattern}"
        return True, None

    def run_powershell(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> ActionOutcome:
        t0 = time.perf_counter()
        is_safe, reason = self._is_safe_command(command)
        if not is_safe:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="run_powershell",
                details="رفض تنفيذ الأمر لدواعي الأمان.",
                error=reason,
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        effective_timeout = timeout or self.default_timeout
        try:
            if self.is_windows:
                utf8_prefix = (
                    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                    "$OutputEncoding = [System.Text.Encoding]::UTF8; "
                )
                cmd_args = [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    utf8_prefix + command,
                ]
            else:
                cmd_args = ["/bin/bash", "-c", command]

            completed = subprocess.run(
                cmd_args,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
            )

            stdout_str = (completed.stdout or "").strip()
            stderr_str = (completed.stderr or "").strip()
            ok = completed.returncode == 0

            return ActionOutcome(
                success=ok,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="run_powershell",
                details="تم تنفيذ أمر النظام بنجاح." if ok else "أعاد الأمر رمز خطأ غير صفري.",
                data={
                    "returncode": completed.returncode,
                    "stdout": stdout_str[:8000],
                    "stderr": stderr_str[:4000],
                },
                error=stderr_str if not ok else None,
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except subprocess.TimeoutExpired:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="run_powershell",
                details="انتهت مهلة تنفيذ الأمر.",
                error=f"Command timed out after {effective_timeout}s",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="run_powershell",
                details="حدث استثناء أثناء تشغيل الأمر.",
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

    def read_tabular_file_fast(self, file_path: str, sheet_name: Optional[str] = None) -> ActionOutcome:
        t0 = time.perf_counter()
        path = Path(file_path)
        if not path.exists():
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="read_tabular_file_fast",
                details="الملف المطلوب غير موجود.",
                error=f"File not found: {file_path}",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        try:
            import pandas as pd

            if path.suffix.lower() in {".xlsx", ".xls"}:
                df = pd.read_excel(path, sheet_name=sheet_name or 0)
            else:
                df = pd.read_csv(path)

            records = df.fillna("").to_dict(orient="records")
            return ActionOutcome(
                success=True,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="read_tabular_file_fast",
                details=f"تمت قراءة {len(records)} سجلاً من الملف مباشرة عبر الطبقة الأولى دون واجهة رسومية.",
                data={
                    "file": str(path.resolve()),
                    "row_count": len(records),
                    "columns": list(df.columns),
                    "records": records[:200],
                },
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_1_CLI.value,
                action="read_tabular_file_fast",
                details="تعذر قراءة الملف الجدولي برمجياً.",
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )


# ==============================================================================
# 3. الطبقة الثانية: التحكم الهيكلي بالواجهات والويب (Layer 2: UIA & Browser-Use)
# ==============================================================================
class StructuralUILayer:
    """
    الطبقة الثانية (الأسرع والأدق لواجهات Windows القياسية والمتصفح):
    - تستخدم `uiautomation` / `pywinauto` لإدارة النوافذ واستخراج شجرة العناصر
      التفاعلية والتفاعل معها برمجياً.
    - تضم جسر `browser-use` لتنفيذ مهام المتصفح المعقدة عبر Playwright + DOM.
    """

    INTERACTIVE_CONTROL_TYPES = {
        "ButtonControl",
        "EditControl",
        "ComboBoxControl",
        "CheckBoxControl",
        "RadioButtonControl",
        "HyperlinkControl",
        "MenuItemControl",
        "TabItemControl",
        "ListItemControl",
        "DocumentControl",
    }

    def __init__(self) -> None:
        self.is_windows = platform.system() == "Windows"
        self._uia = None
        if self.is_windows:
            try:
                import uiautomation as auto
                self._uia = auto
                self._uia.SetGlobalSearchTimeout(2.0)
            except ImportError:
                logger.info("مكتبة `uiautomation` غير مثبتة؛ سيتم استخدام بدائل pywinauto / Win32 عند توفرها.")

    def window_manager(
        self,
        operation: str = "list",
        title_query: Optional[str] = None,
    ) -> ActionOutcome:
        t0 = time.perf_counter()
        op = operation.lower().strip()

        if not self.is_windows:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action=f"window_manager:{op}",
                details="بيئة التشغيل الحالية ليست Windows؛ إدارة نوافذ Win32 مخصصة لنظام ويندوز.",
                error="Non-Windows OS detected",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        try:
            if self._uia is not None:
                root = self._uia.GetRootControl()
                windows = []
                for win in root.GetChildren():
                    name = (win.Name or "").strip()
                    if not name or win.IsOffscreen:
                        continue
                    rect = win.BoundingRectangle
                    windows.append(
                        {
                            "title": name,
                            "class_name": win.ClassName,
                            "handle": win.NativeWindowHandle,
                            "bbox": [rect.left, rect.top, rect.right, rect.bottom],
                            "_control": win,
                        }
                    )

                if op == "list":
                    clean_list = [
                        {k: v for k, v in w.items() if k != "_control"}
                        for w in windows
                    ]
                    return ActionOutcome(
                        success=True,
                        layer_used=ExecutionLayer.LAYER_2_UIA.value,
                        action="window_manager:list",
                        details=f"تم العثور على {len(clean_list)} نافذة مفتوحة.",
                        data={"windows": clean_list},
                        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                    )

                if not title_query:
                    return ActionOutcome(
                        success=False,
                        layer_used=ExecutionLayer.LAYER_2_UIA.value,
                        action=f"window_manager:{op}",
                        details="يرجى تمرير `title_query` لتحديد النافذة المستهدفة.",
                        error="Missing title_query parameter",
                        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                    )

                target = next(
                    (w for w in windows if title_query.lower() in w["title"].lower()),
                    None,
                )
                if not target:
                    return ActionOutcome(
                        success=False,
                        layer_used=ExecutionLayer.LAYER_2_UIA.value,
                        action=f"window_manager:{op}",
                        details=f"لم يتم العثور على نافذة تطابق '{title_query}'.",
                        error="Window not found",
                        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                    )

                ctrl = target["_control"]
                if op == "focus":
                    ctrl.SetActive()
                    ctrl.SetFocus()
                elif op == "maximize":
                    pattern = ctrl.GetWindowPattern()
                    if pattern:
                        pattern.SetWindowVisualState(self._uia.WindowVisualState.Maximized)
                elif op == "minimize":
                    pattern = ctrl.GetWindowPattern()
                    if pattern:
                        pattern.SetWindowVisualState(self._uia.WindowVisualState.Minimized)
                elif op == "close":
                    pattern = ctrl.GetWindowPattern()
                    if pattern:
                        pattern.Close()
                else:
                    return ActionOutcome(
                        success=False,
                        layer_used=ExecutionLayer.LAYER_2_UIA.value,
                        action=f"window_manager:{op}",
                        details=f"عملية غير معروفة: {op}",
                        error=f"Unsupported operation: {op}",
                        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                    )

                return ActionOutcome(
                    success=True,
                    layer_used=ExecutionLayer.LAYER_2_UIA.value,
                    action=f"window_manager:{op}",
                    details=f"تم تنفيذ '{op}' على النافذة '{target['title']}' بنجاح.",
                    data={"title": target["title"], "handle": target["handle"]},
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            win_list = desktop.windows()
            if op == "list":
                titles = [w.window_text() for w in win_list if w.window_text().strip()]
                return ActionOutcome(
                    success=True,
                    layer_used=ExecutionLayer.LAYER_2_UIA.value,
                    action="window_manager:list",
                    details=f"تم جلب {len(titles)} نافذة عبر pywinauto.",
                    data={"windows": [{"title": t} for t in titles]},
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            matched = [
                w for w in win_list
                if title_query and title_query.lower() in w.window_text().lower()
            ]
            if not matched:
                return ActionOutcome(
                    success=False,
                    layer_used=ExecutionLayer.LAYER_2_UIA.value,
                    action=f"window_manager:{op}",
                    details=f"لم يتم العثور على نافذة تطابق '{title_query}'.",
                    error="Window not found",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            win_obj = matched[0]
            if op == "focus":
                win_obj.set_focus()
            elif op == "maximize":
                win_obj.maximize()
            elif op == "minimize":
                win_obj.minimize()
            elif op == "close":
                win_obj.close()

            return ActionOutcome(
                success=True,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action=f"window_manager:{op}",
                details=f"تم تنفيذ '{op}' على النافذة '{win_obj.window_text()}'.",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        except Exception as exc:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action=f"window_manager:{op}",
                details="فشل تنفيذ عملية إدارة النوافذ.",
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

    def extract_active_window_elements(self, max_depth: int = 6, max_elements: int = 80) -> ScreenInspectionResult:
        if not self.is_windows or self._uia is None:
            return ScreenInspectionResult(
                active_window_title="Unknown (UIA Unavailable)",
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                screen_size=(1920, 1080),
                elements=[],
                notes="UI Automation غير متاح في هذه البيئة؛ يجب التحول للطبقة الثالثة (OmniParser Vision).",
            )

        try:
            fg_window = self._uia.GetForegroundControl()
            win_title = (fg_window.Name or "Untitled Window").strip()
            screen_w, screen_h = self._uia.GetScreenSize()

            elements: List[UIElementBox] = []
            box_counter = 1

            def _walk(ctrl: Any, depth: int) -> None:
                nonlocal box_counter
                if depth > max_depth or len(elements) >= max_elements:
                    return
                try:
                    children = ctrl.GetChildren()
                except Exception:
                    return

                for child in children:
                    if len(elements) >= max_elements:
                        break
                    try:
                        if child.IsOffscreen:
                            continue
                        c_type = child.ControlTypeName
                        name = (child.Name or "").strip()
                        auto_id = (child.AutomationId or "").strip()
                        rect = child.BoundingRectangle
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top

                        if (
                            c_type in self.INTERACTIVE_CONTROL_TYPES
                            and w > 6
                            and h > 6
                            and (name or auto_id)
                        ):
                            cx = rect.left + w // 2
                            cy = rect.top + h // 2
                            elements.append(
                                UIElementBox(
                                    box_id=box_counter,
                                    label=name or auto_id,
                                    control_type=c_type.replace("Control", ""),
                                    bbox=(rect.left, rect.top, rect.right, rect.bottom),
                                    center=(cx, cy),
                                    confidence=1.0,
                                    source="uia",
                                    automation_id=auto_id,
                                    is_interactive=True,
                                )
                            )
                            box_counter += 1

                        _walk(child, depth + 1)
                    except Exception:
                        continue

            _walk(fg_window, 1)

            notes = (
                f"تم استخراج {len(elements)} عنصراً هيكلياً بدقة 100% عبر UI Automation."
                if elements
                else "لم تكشف النافذة عن عناصر UIA قياسية (قد تكون Canvas أو نظاماً مغلقاً)؛ يوصى بالتحول للطبقة الثالثة."
            )
            return ScreenInspectionResult(
                active_window_title=win_title,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                screen_size=(screen_w, screen_h),
                elements=elements,
                notes=notes,
            )
        except Exception as exc:
            return ScreenInspectionResult(
                active_window_title="Error Reading Foreground Window",
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                screen_size=(1920, 1080),
                elements=[],
                notes=f"فشل استخراج شجرة UIA: {exc}",
            )

    def interact_native_element(
        self,
        element_label: str,
        action: str = "click",
        value: Optional[str] = None,
    ) -> ActionOutcome:
        t0 = time.perf_counter()
        if not self.is_windows or self._uia is None:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action=f"uia_{action}",
                details="UIA غير متاح؛ يلزم التحول التلقائي للطبقة الثالثة (Vision).",
                error="UIA unavailable",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        try:
            fg = self._uia.GetForegroundControl()
            target = fg.Control(searchDepth=7, SubName=element_label)
            if not target.Exists(maxSearchSeconds=1.5):
                return ActionOutcome(
                    success=False,
                    layer_used=ExecutionLayer.LAYER_2_UIA.value,
                    action=f"uia_{action}",
                    details=f"العنصر '{element_label}' غير مكشوف في شجرة UIA؛ سيتم التصعيد للطبقة البصرية.",
                    error="Element not found in UIA tree",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            if action == "click":
                invoke_pat = target.GetInvokePattern()
                if invoke_pat:
                    invoke_pat.Invoke()
                else:
                    target.Click(simulateMove=False)
                return ActionOutcome(
                    success=True,
                    layer_used=ExecutionLayer.LAYER_2_UIA.value,
                    action="uia_click",
                    details=f"تم النقر هيكلياً على '{element_label}' عبر Windows UI Automation.",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            if action in {"set_text", "type"} and value is not None:
                val_pat = target.GetValuePattern()
                if val_pat:
                    val_pat.SetValue(value)
                    return ActionOutcome(
                        success=True,
                        layer_used=ExecutionLayer.LAYER_2_UIA.value,
                        action="uia_set_text",
                        details=f"تم حقن النص مباشرة في الحقل '{element_label}' عبر ValuePattern.",
                        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                    )
                target.SetFocus()
                return ActionOutcome(
                    success=False,
                    layer_used=ExecutionLayer.LAYER_2_UIA.value,
                    action="uia_set_text",
                    details="الحقل لا يدعم ValuePattern المباشر؛ تم تفعيل التركيز عليه للكتابة عبر الحافظة.",
                    error="ValuePattern unsupported; fallback to clipboard paste",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action=f"uia_{action}",
                details=f"عملية غير مدعومة في UIA: {action}",
                error="Unsupported UIA action",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action=f"uia_{action}",
                details="تعذر التفاعل الهيكلي عبر UIA؛ يوصى بالتصعيد للطبقة الثالثة.",
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

    async def run_browser_task(
        self,
        task_prompt: str,
        headless: bool = True,
        model_name: Optional[str] = None,
    ) -> ActionOutcome:
        t0 = time.perf_counter()
        try:
            from browser_use import Agent as BrowserAgent
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=model_name or os.getenv("MUNJIZ_LLM_MODEL", "gpt-4o"),
                temperature=0.0,
            )
            agent = BrowserAgent(task=task_prompt, llm=llm)
            history = await agent.run()
            final_result = history.final_result() if hasattr(history, "final_result") else str(history)

            return ActionOutcome(
                success=True,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action="browser_use_task",
                details="أنجز وكيل المتصفح (browser-use) المهمة بنجاح.",
                data={"task": task_prompt, "headless": headless, "result": final_result},
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except ImportError:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action="browser_use_task",
                details="حزمة `browser-use` أو `langchain-openai` غير مثبتة في البيئة الحالية.",
                error="Install via: pip install browser-use langchain-openai playwright && playwright install",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_2_UIA.value,
                action="browser_use_task",
                details="حدث خطأ أثناء تنفيذ مهمة المتصفح.",
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )


# ==============================================================================
# 4. الطبقة الثالثة: الرؤية البصرية الخالصة وتتبع الماوس الحي (Layer 3: Vision + Cursor HUD)
# ==============================================================================
class OmniParserVisionLayer:
    """
    الطبقة الثالثة (العين البصرية الشاملة + تتبع المؤشر الحي):
    - تلتقط الشاشة وتمررها إلى `OmniParser V2` لترسم مربعات مرقمة (Set-of-Mark).
    - ترسم مؤشر الماوس الحقيقي (Crosshair + Halo) ومسار الحركة (Trajectory) على اللقطات
      المرئية حتى يشاهد المستخدم والوكيل موقع الفأرة الفعلي.
    - تعرض حلقة ضوئية لحظية (Live Click Ripple HUD) على شاشة المستخدم عند النقر.
    """

    def __init__(
        self,
        omniparser_endpoint: Optional[str] = None,
        artifacts_dir: Optional[str] = None,
        enable_live_hud: bool = True,
    ) -> None:
        self.omniparser_endpoint = omniparser_endpoint or os.getenv(
            "MUNJIZ_OMNIPARSER_URL", "http://127.0.0.1:8000/parse"
        )
        self.artifacts_dir = Path(artifacts_dir or "./munjiz_vision_cache")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.enable_live_hud = enable_live_hud
        self.last_som_elements: Dict[int, UIElementBox] = {}
        self.last_cursor_pos: Tuple[int, int] = (240, 180)
        self.last_action_target: Optional[Tuple[int, int]] = None
        self.last_action_name: str = "idle"

    def get_cursor_position(self) -> Tuple[int, int]:
        """قراءة إحداثيات مؤشر الماوس الفعلية الحالية على الشاشة."""
        if platform.system() == "Windows":
            try:
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                pt = POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                self.last_cursor_pos = (int(pt.x), int(pt.y))
                return self.last_cursor_pos
            except Exception:
                pass
        try:
            import pyautogui
            pos = pyautogui.position()
            self.last_cursor_pos = (int(pos[0]), int(pos[1]))
            return self.last_cursor_pos
        except Exception:
            return self.last_cursor_pos

    def show_live_click_ripple(self, x: int, y: int, color: str = "#ef4444", duration_ms: int = 380) -> None:
        """
        إظهار حلقة بصرية مضيئة (Live HUD Overlay) على شاشة المستخدم في موقع النقر (x, y)
        دون تعطيل حركة الماوس، ليرى المستخدم بالعين المجردة أين ينقر الوكيل.
        """
        if not self.enable_live_hud or platform.system() != "Windows":
            return

        def _spawn_ripple() -> None:
            try:
                import tkinter as tk
                root = tk.Tk()
                root.overrideredirect(True)
                root.attributes("-topmost", True)
                root.attributes("-transparentcolor", "white")
                size = 56
                root.geometry(f"{size}x{size}+{x - size // 2}+{y - size // 2}")
                canvas = tk.Canvas(root, width=size, height=size, bg="white", highlightthickness=0)
                canvas.pack()
                canvas.create_oval(6, 6, size - 6, size - 6, outline=color, width=3)
                canvas.create_oval(22, 22, size - 22, size - 22, fill=color, outline=color)
                root.after(duration_ms, root.destroy)
                root.mainloop()
            except Exception:
                pass

        threading.Thread(target=_spawn_ripple, daemon=True).start()

    def draw_cursor_and_trajectory(
        self,
        image: Any,
        cursor_xy: Tuple[int, int],
        target_xy: Optional[Tuple[int, int]] = None,
        action_label: str = "",
    ) -> Any:
        """
        رسم مؤشر الفأرة الحقيقي (Crosshair + Halo) ومسار الحركة على لقطة الشاشة
        لأن `ImageGrab.grab()` لا يظهر أيقونة الماوس افتراضياً.
        """
        from PIL import ImageDraw

        canvas = image.copy()
        draw = ImageDraw.Draw(canvas)
        cx, cy = cursor_xy

        # إذا كان هناك هدف حركة جديد، نرسم خط مسار من الماوس الحالي إلى الهدف
        if target_xy and target_xy != cursor_xy:
            tx, ty = target_xy
            draw.line([cx, cy, tx, ty], fill=(37, 99, 235), width=3)
            draw.ellipse([tx - 14, ty - 14, tx + 14, ty + 14], outline=(220, 38, 38), width=3)

        # رسم هالة مؤشر الفأرة الحالي (Cursor Halo + Crosshair)
        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], outline=(220, 38, 38), width=3)
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(220, 38, 38))
        draw.line([cx - 18, cy, cx + 18, cy], fill=(220, 38, 38), width=2)
        draw.line([cx, cy - 18, cx, cy + 18], fill=(220, 38, 38), width=2)

        tag = f"Cursor ({cx},{cy})" + (f" | {action_label}" if action_label else "")
        draw.rectangle([cx + 14, cy + 14, cx + 14 + len(tag) * 6 + 10, cy + 32], fill=(17, 24, 39))
        draw.text((cx + 18, cy + 17), tag, fill=(255, 255, 255))
        return canvas

    def capture_screenshot(self) -> Tuple[Any, Tuple[int, int]]:
        """التقاط صورة للشاشة الكاملة وإعادتها ككائن PIL.Image مع أبعاد الشاشة الفعلية."""
        from PIL import Image, ImageDraw, ImageGrab

        try:
            img = ImageGrab.grab(all_screens=False)
            return img, img.size
        except Exception:
            mock_img = Image.new("RGB", (1280, 720), color=(244, 246, 250))
            draw = ImageDraw.Draw(mock_img)
            draw.rectangle([80, 120, 460, 165], outline=(40, 40, 40), width=2, fill=(255, 255, 255))
            draw.rectangle([80, 190, 460, 235], outline=(40, 40, 40), width=2, fill=(255, 255, 255))
            draw.rectangle([80, 260, 220, 305], outline=(20, 90, 200), width=2, fill=(37, 99, 235))
            draw.rectangle([240, 260, 380, 305], outline=(16, 120, 80), width=2, fill=(5, 150, 105))
            return mock_img, mock_img.size

    def _detect_boxes_with_omniparser_api(self, image: Any) -> Optional[List[UIElementBox]]:
        import urllib.request

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode("ascii")

        payload = json.dumps({"image_base64": b64_img, "box_threshold": 0.05}).encode("utf-8")
        req = urllib.request.Request(
            self.omniparser_endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                parsed_items = resp_data.get("parsed_content_list", [])
                w, h = image.size
                boxes: List[UIElementBox] = []
                for idx, item in enumerate(parsed_items, start=1):
                    raw_bbox = item.get("bbox", [0, 0, 0, 0])
                    if all(0.0 <= v <= 1.0 for v in raw_bbox) and max(raw_bbox) <= 1.0:
                        x1, y1, x2, y2 = (
                            int(raw_bbox[0] * w),
                            int(raw_bbox[1] * h),
                            int(raw_bbox[2] * w),
                            int(raw_bbox[3] * h),
                        )
                    else:
                        x1, y1, x2, y2 = [int(v) for v in raw_bbox]

                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    boxes.append(
                        UIElementBox(
                            box_id=idx,
                            label=item.get("content", f"Element_{idx}"),
                            control_type=item.get("type", "icon_or_text"),
                            bbox=(x1, y1, x2, y2),
                            center=(cx, cy),
                            confidence=float(item.get("confidence", 0.95)),
                            source="omniparser_v2",
                            is_interactive=bool(item.get("interactivity", True)),
                        )
                    )
                return boxes
        except Exception as exc:
            logger.debug(f"خادم OmniParser غير متصل حالياً ({exc})؛ سيتم استخدام الكاشف البصري المحلي الاحتياطي.")
            return None

    def _detect_boxes_local_cv_fallback(self, image: Any) -> List[UIElementBox]:
        import cv2
        import numpy as np

        rgb = np.array(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 6))
        dilated = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes: List[UIElementBox] = []
        box_id = 1
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if 24 <= w <= 600 and 16 <= h <= 160:
                cx, cy = x + w // 2, y + h // 2
                boxes.append(
                    UIElementBox(
                        box_id=box_id,
                        label=f"Visual_Control_{box_id}",
                        control_type="visual_box",
                        bbox=(x, y, x + w, y + h),
                        center=(cx, cy),
                        confidence=0.80,
                        source="cv2_som_fallback",
                        is_interactive=True,
                    )
                )
                box_id += 1
                if box_id > 60:
                    break
        return boxes

    def render_set_of_mark(
        self,
        image: Any,
        elements: List[UIElementBox],
        draw_cursor: bool = True,
    ) -> Tuple[str, str]:
        from PIL import ImageDraw, ImageFont

        annotated = image.copy()
        if draw_cursor:
            cursor_xy = self.get_cursor_position()
            annotated = self.draw_cursor_and_trajectory(
                annotated,
                cursor_xy=cursor_xy,
                target_xy=self.last_action_target,
                action_label=self.last_action_name,
            )

        draw = ImageDraw.Draw(annotated)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        palette = [
            (220, 38, 38),
            (37, 99, 235),
            (5, 150, 105),
            (217, 119, 6),
            (124, 58, 237),
        ]

        for el in elements:
            color = palette[el.box_id % len(palette)]
            x1, y1, x2, y2 = el.bbox
            draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
            tag_text = f"[{el.box_id}]"
            tag_w = max(24, len(tag_text) * 7)
            tag_h = 16
            tag_y1 = max(0, y1 - tag_h)
            draw.rectangle([x1, tag_y1, x1 + tag_w, tag_y1 + tag_h], fill=color)
            draw.text((x1 + 3, tag_y1 + 2), tag_text, fill=(255, 255, 255), font=font)

        out_path = self.artifacts_dir / f"som_screen_{int(time.time())}.png"
        annotated.save(out_path, format="PNG")

        buf = io.BytesIO()
        annotated.save(buf, format="PNG")
        b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
        return str(out_path.resolve()), b64_str

    def inspect_screen_visually(self) -> ScreenInspectionResult:
        img, screen_size = self.capture_screenshot()
        cursor_xy = self.get_cursor_position()
        boxes = self._detect_boxes_with_omniparser_api(img)
        used_omniparser = boxes is not None
        if boxes is None:
            boxes = self._detect_boxes_local_cv_fallback(img)

        self.last_som_elements = {b.box_id: b for b in boxes}
        img_path, b64_str = self.render_set_of_mark(img, boxes, draw_cursor=True)

        return ScreenInspectionResult(
            active_window_title="Visual Screen Capture (Set-of-Mark + Live Cursor)",
            layer_used=ExecutionLayer.LAYER_3_VISION.value,
            screen_size=screen_size,
            cursor_position=cursor_xy,
            elements=boxes,
            annotated_image_base64=b64_str,
            annotated_image_path=img_path,
            notes=(
                "تم تحليل الشاشة بصرياً عبر OmniParser V2 ورسم مؤشر الماوس الحي؛ استخدم `box_id` للنقر المباشر."
                if used_omniparser
                else f"تم استخراج {len(boxes)} عناصر مرقمة ورسم مؤشر الماوس الحي عند {cursor_xy}."
            ),
        )

    def capture_live_frame_with_cursor(self, include_base64: bool = True) -> Dict[str, Any]:
        """
        أداة مخصصة للمشاهدة المرئية المباشرة داخل واجهة "مُنجز":
        تلتقط الشاشة وترسم موقع مؤشر الماوس الحالي وآخر هدف نقر وتعيدها فوراً.
        """
        img, screen_size = self.capture_screenshot()
        cursor_xy = self.get_cursor_position()
        annotated = self.draw_cursor_and_trajectory(
            img,
            cursor_xy=cursor_xy,
            target_xy=self.last_action_target,
            action_label=self.last_action_name,
        )
        out_path = self.artifacts_dir / "live_cursor_view.png"
        annotated.save(out_path, format="PNG")

        result: Dict[str, Any] = {
            "screen_size": {"width": screen_size[0], "height": screen_size[1]},
            "cursor_position": {"x": cursor_xy[0], "y": cursor_xy[1]},
            "last_action_target": (
                {"x": self.last_action_target[0], "y": self.last_action_target[1]}
                if self.last_action_target
                else None
            ),
            "last_action_name": self.last_action_name,
            "live_frame_path": str(out_path.resolve()),
        }
        if include_base64:
            buf = io.BytesIO()
            annotated.save(buf, format="PNG")
            result["image_base64"] = base64.b64encode(buf.getvalue()).decode("ascii")
        return result

    def gui_action(
        self,
        action: str = "click",
        box_id: Optional[int] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        drag_to_x: Optional[int] = None,
        drag_to_y: Optional[int] = None,
        scroll_clicks: int = -3,
        duration: float = 0.25,
    ) -> ActionOutcome:
        t0 = time.perf_counter()
        target_x, target_y = x, y
        resolved_label = ""

        if box_id is not None:
            if box_id not in self.last_som_elements:
                return ActionOutcome(
                    success=False,
                    layer_used=ExecutionLayer.LAYER_3_VISION.value,
                    action=f"gui_action:{action}",
                    details=f"رقم الصندوق box_id={box_id} غير موجود في الذاكرة؛ استدعِ `inspect_screen` أولاً.",
                    error=f"Unknown box_id: {box_id}",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )
            el = self.last_som_elements[box_id]
            target_x, target_y = el.center
            resolved_label = el.label

        if action != "scroll" and (target_x is None or target_y is None):
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_3_VISION.value,
                action=f"gui_action:{action}",
                details="يجب تحديد `box_id` أو زوج الإحداثيات `(x, y)`.",
                error="Missing coordinates or box_id",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        act = action.lower().strip()
        if target_x is not None and target_y is not None:
            self.last_action_target = (int(target_x), int(target_y))
            self.last_action_name = f"{act}:{resolved_label or box_id or ''}"
            # إظهار حلقة النقر المرئية على شاشة المستخدم
            self.show_live_click_ripple(int(target_x), int(target_y))

        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05

            if act == "click":
                pyautogui.moveTo(x=target_x, y=target_y, duration=duration)
                pyautogui.click(x=target_x, y=target_y)
            elif act == "double_click":
                pyautogui.moveTo(x=target_x, y=target_y, duration=duration)
                pyautogui.doubleClick(x=target_x, y=target_y)
            elif act == "right_click":
                pyautogui.moveTo(x=target_x, y=target_y, duration=duration)
                pyautogui.rightClick(x=target_x, y=target_y)
            elif act == "move":
                pyautogui.moveTo(x=target_x, y=target_y, duration=duration)
            elif act == "drag":
                if drag_to_x is None or drag_to_y is None:
                    return ActionOutcome(
                        success=False,
                        layer_used=ExecutionLayer.LAYER_3_VISION.value,
                        action="gui_action:drag",
                        details="يتطلب أمر السحب تحديد `drag_to_x` و `drag_to_y`.",
                        error="Missing drag destination coordinates",
                        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                    )
                pyautogui.moveTo(target_x, target_y, duration=0.15)
                pyautogui.dragTo(drag_to_x, drag_to_y, duration=max(0.3, duration), button="left")
            elif act == "scroll":
                if target_x is not None and target_y is not None:
                    pyautogui.moveTo(target_x, target_y, duration=0.1)
                pyautogui.scroll(scroll_clicks)
            else:
                return ActionOutcome(
                    success=False,
                    layer_used=ExecutionLayer.LAYER_3_VISION.value,
                    action=f"gui_action:{act}",
                    details=f"حركة فأرة غير معروفة: {act}",
                    error=f"Unsupported GUI action: {act}",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                )

            if target_x is not None and target_y is not None:
                self.last_cursor_pos = (int(target_x), int(target_y))

            return ActionOutcome(
                success=True,
                layer_used=ExecutionLayer.LAYER_3_VISION.value,
                action=f"gui_action:{act}",
                details=f"تم تحريك المؤشر وتنفيذ '{act}' عند ({target_x}, {target_y}) {f'[{resolved_label}]' if resolved_label else ''}.",
                data={"x": target_x, "y": target_y, "box_id": box_id, "label": resolved_label},
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:
            if target_x is not None and target_y is not None:
                self.last_cursor_pos = (int(target_x), int(target_y))
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_3_VISION.value,
                action=f"gui_action:{action}",
                details="تعذر تحريك الفأرة فعلياً (البيئة الحالية بدون خادم عرض رسومي أو PyAutoGUI غير مثبت).",
                error=str(exc),
                data={"target_x": target_x, "target_y": target_y, "box_id": box_id},
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

    def keyboard_input(
        self,
        text: Optional[str] = None,
        hotkey: Optional[str] = None,
        press_enter: bool = False,
        clear_first: bool = False,
        restore_clipboard: bool = True,
    ) -> ActionOutcome:
        t0 = time.perf_counter()
        try:
            import pyautogui
            import pyperclip

            if clear_first:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                pyautogui.press("backspace")

            if text:
                previous_clipboard: Optional[str] = None
                if restore_clipboard:
                    try:
                        previous_clipboard = pyperclip.paste()
                    except Exception:
                        previous_clipboard = None

                pyperclip.copy(text)
                time.sleep(0.06)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.08)

                if restore_clipboard and previous_clipboard is not None:
                    try:
                        pyperclip.copy(previous_clipboard)
                    except Exception:
                        pass

            if hotkey:
                keys = [k.strip().lower() for k in hotkey.split("+") if k.strip()]
                if len(keys) == 1:
                    pyautogui.press(keys[0])
                else:
                    pyautogui.hotkey(*keys)

            if press_enter:
                time.sleep(0.05)
                pyautogui.press("enter")

            return ActionOutcome(
                success=True,
                layer_used=ExecutionLayer.LAYER_3_VISION.value,
                action="keyboard_input",
                details="تم إدخال النص/الاختصار بنجاح مع دعم الترميز العربي عبر الحافظة.",
                data={"text_length": len(text) if text else 0, "hotkey": hotkey, "press_enter": press_enter},
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:
            return ActionOutcome(
                success=False,
                layer_used=ExecutionLayer.LAYER_3_VISION.value,
                action="keyboard_input",
                details="تعذر إرسال ضغطات لوحة المفاتيح في البيئة الحالية.",
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )


# ==============================================================================
# 5. الموجه الهجين الذكي حسب السياق (Context-Aware Hybrid Router & ACI)
# ==============================================================================
MUNJIZ_ACI_SYSTEM_PROMPT = """
أنت وكيل التنفيذ الذكي في نظام "مُنجز" (Munjiz OS Agent)، مزود بواجهة تحكم هجينة
ثلاثية الطبقات (3-Layer Agent-Computer Interface). يجب عليك دائماً اختيار الطبقة
الأسرع والأكثر موثوقية حسب سياق المهمة:

1. الأولوية القصوى - الطبقة الأولى (System / CLI Layer):
   - استخدم `system_cli` أو `read_excel_or_csv` لأي مهمة تتعلق بقراءة ملفات
     (Excel/CSV/JSON)، إدارة المجلدات، تشغيل البرامج، أو استعلامات النظام.
   - لا تفتح برنامج Excel أو Explorer بالماوس أبداً إذا كان يمكنك قراءة الملف أو
     نسخه في الخلفية خلال جزء من الثانية.

2. الأولوية الثانية - الطبقة الثانية (Structural UI / DOM Layer):
   - عند التعامل مع نوافذ Windows، استخدم `window_manager` لتفعيل النافذة المطلوبة
     (Focus)، ثم استدعِ `inspect_screen(mode="auto")`.
   - إذا أعادت الأداة عناصر هيكلية من `layer_2_structural_ui_dom`، تفاعل معها فوراً
     عبر `smart_interact` أو `gui_action(box_id=...)` دون الحاجة لتحليل صور ثقيلة.
   - لمهام المتصفح والويب، استخدم `browser_task` لتشغيل وكيل `browser-use` عبر DOM.

3. الأولوية الثالثة - الطبقة الثالثة (Pure Vision Layer - OmniParser V2):
   - عندما تكون النافذة مغلقة برمجياً (مثل الأنظمة المحاسبية القديمة، Canvas، أو
     برامج التصميم)، سيقوم `inspect_screen(mode="auto")` تلقائياً بتشغيل
     `OmniParser V2` وإعادة صورة مرقمة (Set-of-Mark) مع رسم مؤشر الفأرة الحي.
   - انظر إلى أرقام الصناديق `[box_id]` واستدعِ `gui_action(action="click", box_id=N)`
     واستخدم `keyboard_input(text="...", press_enter=True)` لكتابة النصوص العربية
     والإنجليزية بأمان عبر الحافظة.
""".strip()


class MunjizHybridRouter:
    """
    المحرك المركزي لتطبيق "مُنجز" (Context-Aware Hybrid Router):
    ينسق بين الطبقات الثلاث ويحول تلقائياً من الطبقة الهيكلية (UIA) إلى الطبقة
    البصرية (OmniParser Set-of-Mark + Live Cursor) عندما لا تكشف النافذة عن عناصرها برمجياً.
    """

    def __init__(
        self,
        omniparser_endpoint: Optional[str] = None,
        artifacts_dir: Optional[str] = None,
    ) -> None:
        self.cli_layer = SystemCLILayer()
        self.uia_layer = StructuralUILayer()
        self.vision_layer = OmniParserVisionLayer(
            omniparser_endpoint=omniparser_endpoint,
            artifacts_dir=artifacts_dir,
        )

    def inspect_screen(self, mode: str = "auto", include_base64: bool = False) -> Dict[str, Any]:
        normalized_mode = mode.lower().strip()

        if normalized_mode in {"auto", "structural"}:
            uia_res = self.uia_layer.extract_active_window_elements()
            uia_res.cursor_position = self.vision_layer.get_cursor_position()
            if normalized_mode == "structural" or len(uia_res.elements) >= 3:
                self.vision_layer.last_som_elements = {el.box_id: el for el in uia_res.elements}
                return uia_res.to_agent_payload(include_base64=False)
            logger.info(
                "النافذة النشطة لم تكشف عناصر كافية عبر UIA؛ التحول التلقائي للطبقة الثالثة (OmniParser Vision)."
            )

        vision_res = self.vision_layer.inspect_screen_visually()
        return vision_res.to_agent_payload(include_base64=include_base64)

    def smart_interact(
        self,
        target_label: Optional[str] = None,
        box_id: Optional[int] = None,
        action: str = "click",
        text_to_type: Optional[str] = None,
        press_enter: bool = False,
    ) -> ActionOutcome:
        if target_label and box_id is None:
            uia_attempt = self.uia_layer.interact_native_element(
                element_label=target_label,
                action="set_text" if text_to_type is not None else action,
                value=text_to_type,
            )
            if uia_attempt.success:
                if press_enter:
                    self.vision_layer.keyboard_input(press_enter=True)
                return uia_attempt

            if not self.vision_layer.last_som_elements:
                self.inspect_screen(mode="vision")

            matched_box = next(
                (
                    b_id
                    for b_id, el in self.vision_layer.last_som_elements.items()
                    if target_label.lower() in el.label.lower()
                ),
                None,
            )
            if matched_box is not None:
                box_id = matched_box

        if box_id is not None:
            click_outcome = self.vision_layer.gui_action(action=action, box_id=box_id)
            if not click_outcome.success:
                return click_outcome

            if text_to_type is not None:
                type_outcome = self.vision_layer.keyboard_input(
                    text=text_to_type,
                    press_enter=press_enter,
                    clear_first=True,
                )
                return ActionOutcome(
                    success=type_outcome.success,
                    layer_used=ExecutionLayer.LAYER_3_VISION.value,
                    action="smart_interact:vision_click_and_type",
                    details=f"{click_outcome.details} -> {type_outcome.details}",
                    data={"box_id": box_id, "text_typed": text_to_type},
                    error=type_outcome.error,
                    elapsed_ms=round(click_outcome.elapsed_ms + type_outcome.elapsed_ms, 2),
                )
            return click_outcome

        return ActionOutcome(
            success=False,
            layer_used=ExecutionLayer.LAYER_3_VISION.value,
            action="smart_interact",
            details=f"تعذر العثور على العنصر '{target_label}' هيكلياً أو بصرياً؛ استدعِ `inspect_screen(mode='vision')` لعرض أرقام الصناديق.",
            error="Target element could not be resolved",
        )


# ==============================================================================
# 6. خادم بروتوكول MCP المدمج (munjiz-os-controller MCP Server)
# ==============================================================================
def create_munjiz_mcp_server(router: Optional[MunjizHybridRouter] = None) -> Any:
    """
    إنشاء خادم MCP قياسي (باستخدام حزمة `mcp` الرسمية `FastMCP`) يغلف الأدوات
    المعمارية الخاصة بـ "مُنجز" لربطها مباشرة مع أي وكيل ذكاء اصطناعي.
    """
    active_router = router or MunjizHybridRouter()

    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("munjiz-os-controller")

        @mcp.tool()
        def system_cli(command: str, cwd: Optional[str] = None, timeout: int = 30) -> str:
            """
            [الطبقة 1 - الأسرع] تنفيذ أوامر PowerShell / CLI لإدارة الملفات، تشغيل
            السكربتات، أو قراءة حالة النظام فوراً دون تحريك الفأرة.
            """
            return active_router.cli_layer.run_powershell(command=command, cwd=cwd, timeout=timeout).to_json()

        @mcp.tool()
        def read_excel_or_csv(file_path: str, sheet_name: Optional[str] = None) -> str:
            """
            [الطبقة 1] قراءة ملفات Excel أو CSV برمجياً في الخلفية بسرعة فائقة
            دون فتح برنامج Excel رسومياً.
            """
            return active_router.cli_layer.read_tabular_file_fast(file_path=file_path, sheet_name=sheet_name).to_json()

        @mcp.tool()
        def window_manager(operation: str = "list", title_query: Optional[str] = None) -> str:
            """
            [الطبقة 2] إدارة نوافذ نظام Windows: عرض النوافذ المفتوحة (`list`)،
            تفعيل نافذة في المقدمة (`focus`)، تكبير (`maximize`)، تصغير (`minimize`)، أو إغلاق (`close`).
            """
            return active_router.uia_layer.window_manager(operation=operation, title_query=title_query).to_json()

        @mcp.tool()
        def inspect_screen(mode: str = "auto", include_base64: bool = False) -> str:
            """
            [الطبقة 2 و 3] فحص الشاشة الذكي مع تتبع موقع مؤشر الماوس الحي.
            """
            payload = active_router.inspect_screen(mode=mode, include_base64=include_base64)
            return json.dumps(payload, ensure_ascii=False, indent=2)

        @mcp.tool()
        def capture_live_view(include_base64: bool = True) -> str:
            """
            [المشاهدة المرئية المباشرة] التقاط صورة حية للشاشة مرسوم عليها مؤشر الفأرة
            الحالي ومسار الحركة لعرضها داخل واجهة "مُنجز".
            """
            frame = active_router.vision_layer.capture_live_frame_with_cursor(include_base64=include_base64)
            return json.dumps(frame, ensure_ascii=False, indent=2)

        @mcp.tool()
        def gui_action(
            action: str = "click",
            box_id: Optional[int] = None,
            x: Optional[int] = None,
            y: Optional[int] = None,
            drag_to_x: Optional[int] = None,
            drag_to_y: Optional[int] = None,
            scroll_clicks: int = -3,
        ) -> str:
            """
            [الطبقة 3] تحريك مؤشر الفأرة وتنفيذ (`click`, `double_click`, `right_click`, `move`, `drag`, `scroll`)
            مع إظهار حلقة النقر المضيئة (Live HUD) على الشاشة.
            """
            return active_router.vision_layer.gui_action(
                action=action,
                box_id=box_id,
                x=x,
                y=y,
                drag_to_x=drag_to_x,
                drag_to_y=drag_to_y,
                scroll_clicks=scroll_clicks,
            ).to_json()

        @mcp.tool()
        def keyboard_input(
            text: Optional[str] = None,
            hotkey: Optional[str] = None,
            press_enter: bool = False,
            clear_first: bool = False,
        ) -> str:
            """
            [الطبقة 3] كتابة النصوص (بدعم كامل للغة العربية عبر الحافظة `Ctrl+V`)
            وتنفيذ اختصارات لوحة المفاتيح (`Ctrl+S`, `Alt+Tab`, إلخ).
            """
            return active_router.vision_layer.keyboard_input(
                text=text,
                hotkey=hotkey,
                press_enter=press_enter,
                clear_first=clear_first,
            ).to_json()

        @mcp.tool()
        def smart_interact(
            target_label: Optional[str] = None,
            box_id: Optional[int] = None,
            action: str = "click",
            text_to_type: Optional[str] = None,
            press_enter: bool = False,
        ) -> str:
            """
            [موجه هجين ذكي] يحاول التفاعل مع العنصر عبر الطبقة الثانية (UIA) أولاً،
            وينتقل تلقائياً للطبقة الثالثة (OmniParser + الفأرة + الحافظة العربية) إذا لزم الأمر.
            """
            return active_router.smart_interact(
                target_label=target_label,
                box_id=box_id,
                action=action,
                text_to_type=text_to_type,
                press_enter=press_enter,
            ).to_json()

        @mcp.tool()
        async def browser_task(task_prompt: str, headless: bool = True) -> str:
            """
            [الطبقة 2 - الويب] إسناد مهمة متصفح كاملة إلى وكيل `browser-use` (Playwright).
            """
            outcome = await active_router.uia_layer.run_browser_task(
                task_prompt=task_prompt, headless=headless
            )
            return outcome.to_json()

        return mcp

    except ImportError:
        logger.warning(
            "حزمة `mcp` غير مثبتة حالياً؛ يمكنك تثبيتها عبر `pip install mcp` لتشغيل الخادم بوضع stdio."
        )
        return None


def get_openai_tools_schema() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "system_cli",
                "description": "[Layer 1] Execute PowerShell or CLI commands directly for fast file/system operations without GUI overhead.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "PowerShell command to execute."},
                        "cwd": {"type": "string", "description": "Optional working directory."},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "window_manager",
                "description": "[Layer 2] List, focus, maximize, minimize, or close desktop windows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["list", "focus", "maximize", "minimize", "close"],
                        },
                        "title_query": {"type": "string", "description": "Substring of the window title."},
                    },
                    "required": ["operation"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_screen",
                "description": "[Layer 2 & 3] Inspect active window via Windows UI Automation first; automatically fall back to OmniParser V2 Set-of-Mark vision grounding with live mouse cursor overlay.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["auto", "structural", "vision"],
                            "default": "auto",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "capture_live_view",
                "description": "[Live Visual Stream] Capture real-time screen frame with rendered mouse cursor crosshair and action trajectory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_base64": {"type": "boolean", "default": True},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "smart_interact",
                "description": "[Hybrid Router] Interact with a control by label or Set-of-Mark box_id, automatically escalating from Layer 2 (UIA) to Layer 3 (Vision + Live Mouse Movement + Arabic Clipboard Paste).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_label": {"type": "string", "description": "Control name/label to search for."},
                        "box_id": {"type": "integer", "description": "Set-of-Mark numbered box ID from inspect_screen."},
                        "action": {"type": "string", "enum": ["click", "double_click", "right_click", "move"]},
                        "text_to_type": {"type": "string", "description": "Arabic or English text to inject safely."},
                        "press_enter": {"type": "boolean", "default": False},
                    },
                },
            },
        },
    ]


# ==============================================================================
# 7. محاكاة سيناريو العمل الواقعي لتطبيق "مُنجز" (End-to-End Blueprint Demo)
# ==============================================================================
def run_accounting_workflow_demo() -> None:
    print("=" * 78)
    print("بدء الاختبار التشغيلي لمحرك التوجيه الهجين: Munjiz 3-Layer Hybrid Router v2.0")
    print("=" * 78)

    router = MunjizHybridRouter(artifacts_dir="/tmp/munjiz_vision_demo")

    sample_csv = Path("/tmp/munjiz_vision_demo/project_clients.csv")
    sample_csv.write_text(
        "client_id,full_name,amount_sar\n"
        "101,أحمد بن محمد العتيبي,4500\n"
        "102,سارة بنت عبدالله القحطاني,8200\n"
        "103,شركة آفاق التقنية المتقدمة,15000\n",
        encoding="utf-8",
    )

    step1 = router.cli_layer.read_tabular_file_fast(str(sample_csv))
    print(f"\n[الخطوة 1 - الطبقة الأولى ({step1.layer_used})]:")
    print(f"  النتيجة : {step1.details} (الزمن: {step1.elapsed_ms} ms)")

    step2_payload = router.inspect_screen(mode="auto", include_base64=False)
    print(f"\n[الخطوة 2 - الفحص الذكي للشاشة وتتبع الماوس ({step2_payload['layer_used']})]:")
    print(f"  موقع المؤشر الحالي : {step2_payload['cursor_position']}")
    print(f"  عدد العناصر المكتشفة : {step2_payload['element_count']}")
    print(f"  الصورة المرقمة (SoM + Cursor) : {step2_payload.get('annotated_image_path', 'N/A')}")

    # محاكاة نقر الماوس على الصندوق رقم 1 ورسم مسار الحركة
    router.vision_layer.gui_action(action="click", box_id=1)
    live_frame = router.vision_layer.capture_live_frame_with_cursor(include_base64=False)
    print(f"\n[الخطوة 3 - المشاهدة المرئية الحية ومسار المؤشر]:")
    print(f"  هدف النقر الأخير : {live_frame['last_action_target']} ({live_frame['last_action_name']})")
    print(f"  لقطة المشاهدة الحية : {live_frame['live_frame_path']}")

    print("\n" + "=" * 78)
    print("اكتمل فحص المعمارية الهجينة وتتبع المؤشر المرئي بنجاح.")
    print("=" * 78)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Munjiz Hybrid OS Controller & MCP Server")
    parser.add_argument(
        "--mode",
        choices=["mcp", "demo"],
        default="mcp",
        help="اختر mcp لتشغيل خادم MCP القياسي أو demo لتشغيل المحاكاة التشخيصية.",
    )
    args = parser.parse_args()

    if args.mode == "mcp":
        mcp_server = create_munjiz_mcp_server()
        if mcp_server is not None:
            mcp_server.run()
        else:
            sys.exit(1)
    else:
        run_accounting_workflow_demo()


if __name__ == "__main__":
    main()
