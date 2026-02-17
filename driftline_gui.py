#!/usr/bin/env python3
"""Driftline Pro GUI for controller drift calibration and compensation."""

from __future__ import annotations

import datetime as dt
import math
import pathlib
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

import drift_bot as core

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise SystemExit(
        "Missing dependency: PySide6. Install with `pip install -r requirements.txt`."
    ) from exc


ACCENT = QtGui.QColor("#D4DF3A")
BG = QtGui.QColor("#0A0B11")
PANEL_BG = QtGui.QColor("#121420")
CARD_BG = QtGui.QColor("#1A1E2C")
MUTED = QtGui.QColor("#8D96B3")
TEXT = QtGui.QColor("#E9EDF7")
GOOD = QtGui.QColor("#25D68F")
WARN = QtGui.QColor("#F3B54A")
BAD = QtGui.QColor("#F06A6A")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_vec(value: Tuple[float, float]) -> str:
    return f"({value[0]:+0.3f}, {value[1]:+0.3f})"


def response_curve(value: float, gamma: float) -> float:
    magnitude = abs(value)
    curved = magnitude ** max(0.2, gamma)
    return math.copysign(curved, value)


@dataclass
class StickPanelRefs:
    side: str
    container: QtWidgets.QFrame
    scope: "StickScope"
    auto_deadzone: QtWidgets.QCheckBox
    x_slider: QtWidgets.QSlider
    y_slider: QtWidgets.QSlider
    x_value: QtWidgets.QLabel
    y_value: QtWidgets.QLabel
    curve_slider: QtWidgets.QSlider
    curve_value: QtWidgets.QLabel
    smooth_slider: QtWidgets.QSlider
    smooth_value: QtWidgets.QLabel
    raw_label: QtWidgets.QLabel
    fixed_label: QtWidgets.QLabel
    center_label: QtWidgets.QLabel
    health_label: QtWidgets.QLabel


class StickScope(QtWidgets.QWidget):
    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.title = title
        self.raw = (0.0, 0.0)
        self.fixed = (0.0, 0.0)
        self.deadzone = 0.08
        self._trail: Deque[Tuple[float, float]] = deque(maxlen=120)
        self.setMinimumSize(250, 250)

    def set_state(self, raw: Tuple[float, float], fixed: Tuple[float, float], deadzone: float) -> None:
        self.raw = raw
        self.fixed = fixed
        self.deadzone = clamp(deadzone, 0.02, 0.6)
        self._trail.append(fixed)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(6, 6, -6, -6)
        painter.setPen(QtGui.QPen(QtGui.QColor("#2A3044"), 1))
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#0E111A")))
        painter.drawRoundedRect(rect, 12, 12)

        painter.setPen(TEXT)
        title_font = painter.font()
        title_font.setPointSize(10)
        title_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(title_font)
        painter.drawText(rect.adjusted(12, 8, -8, -8), QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, self.title)

        inner = rect.adjusted(16, 34, -16, -14)
        size = min(inner.width(), inner.height())
        square = QtCore.QRectF(
            inner.center().x() - size / 2,
            inner.center().y() - size / 2,
            size,
            size,
        )

        center = square.center()
        radius = square.width() / 2 - 8

        painter.setPen(QtGui.QPen(QtGui.QColor("#3A425D"), 1))
        painter.drawLine(
            QtCore.QPointF(center.x() - radius, center.y()),
            QtCore.QPointF(center.x() + radius, center.y()),
        )
        painter.drawLine(
            QtCore.QPointF(center.x(), center.y() - radius),
            QtCore.QPointF(center.x(), center.y() + radius),
        )

        painter.setPen(QtGui.QPen(QtGui.QColor("#495371"), 1.5))
        painter.drawEllipse(center, radius, radius)

        dz_radius = radius * self.deadzone
        painter.setPen(QtGui.QPen(ACCENT, 1.5, QtCore.Qt.DashLine))
        painter.drawEllipse(center, dz_radius, dz_radius)

        if self._trail:
            for idx, point in enumerate(self._trail):
                alpha = int(20 + (idx / len(self._trail)) * 120)
                color = QtGui.QColor(80, 230, 255, alpha)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(color)
                x = center.x() + point[0] * radius
                y = center.y() - point[1] * radius
                painter.drawEllipse(QtCore.QPointF(x, y), 2.4, 2.4)

        painter.setBrush(QtGui.QColor("#F0AD52"))
        painter.setPen(QtCore.Qt.NoPen)
        raw_point = QtCore.QPointF(
            center.x() + self.raw[0] * radius,
            center.y() - self.raw[1] * radius,
        )
        painter.drawEllipse(raw_point, 5.0, 5.0)

        painter.setBrush(QtGui.QColor("#36EFA6"))
        fixed_point = QtCore.QPointF(
            center.x() + self.fixed[0] * radius,
            center.y() - self.fixed[1] * radius,
        )
        painter.drawEllipse(fixed_point, 4.0, 4.0)


class ControllerCanvas(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.left_raw = (0.0, 0.0)
        self.right_raw = (0.0, 0.0)
        self.left_fixed = (0.0, 0.0)
        self.right_fixed = (0.0, 0.0)
        self.setMinimumSize(520, 360)

    def set_state(
        self,
        left_raw: Tuple[float, float],
        right_raw: Tuple[float, float],
        left_fixed: Tuple[float, float],
        right_fixed: Tuple[float, float],
    ) -> None:
        self.left_raw = left_raw
        self.right_raw = right_raw
        self.left_fixed = left_fixed
        self.right_fixed = right_fixed
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(6, 6, -6, -6)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QtGui.QColor("#121622"))
        gradient.setColorAt(1.0, QtGui.QColor("#191127"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#2F3550"), 1))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawRoundedRect(rect, 20, 20)

        center = rect.center()
        body_w = rect.width() * 0.74
        body_h = rect.height() * 0.54
        body_rect = QtCore.QRectF(
            center.x() - body_w / 2,
            center.y() - body_h / 2,
            body_w,
            body_h,
        )

        body_gradient = QtGui.QLinearGradient(body_rect.topLeft(), body_rect.bottomRight())
        body_gradient.setColorAt(0.0, QtGui.QColor("#3E465F"))
        body_gradient.setColorAt(0.5, QtGui.QColor("#262D3D"))
        body_gradient.setColorAt(1.0, QtGui.QColor("#576077"))

        painter.setPen(QtGui.QPen(QtGui.QColor("#8D99B3"), 1.2))
        painter.setBrush(QtGui.QBrush(body_gradient))
        painter.drawRoundedRect(body_rect, 72, 72)

        grip_left = QtCore.QRectF(body_rect.left() - 56, body_rect.center().y() - 30, 92, 152)
        grip_right = QtCore.QRectF(body_rect.right() - 36, body_rect.center().y() - 30, 92, 152)
        painter.drawRoundedRect(grip_left, 44, 44)
        painter.drawRoundedRect(grip_right, 44, 44)

        touchpad = QtCore.QRectF(body_rect.center().x() - 90, body_rect.top() + 34, 180, 74)
        painter.setBrush(QtGui.QColor("#1A1E27"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#7382A8"), 1))
        painter.drawRoundedRect(touchpad, 16, 16)

        left_base = QtCore.QPointF(body_rect.center().x() - 106, body_rect.center().y() + 42)
        right_base = QtCore.QPointF(body_rect.center().x() + 106, body_rect.center().y() + 42)
        stick_radius = 38

        self._draw_stick(painter, left_base, self.left_raw, self.left_fixed, stick_radius)
        self._draw_stick(painter, right_base, self.right_raw, self.right_fixed, stick_radius)

        top_font = painter.font()
        top_font.setPointSize(9)
        top_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(top_font)
        painter.setPen(MUTED)
        painter.drawText(rect.adjusted(20, 14, -20, -14), QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, "DRIFTLINE PRO")
        painter.drawText(
            rect.adjusted(20, 14, -20, -14),
            QtCore.Qt.AlignTop | QtCore.Qt.AlignRight,
            "Live Controller View",
        )

    def _draw_stick(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        raw: Tuple[float, float],
        fixed: Tuple[float, float],
        radius: float,
    ) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("#12161E"), 1))
        painter.setBrush(QtGui.QColor("#1E2431"))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QtGui.QPen(QtGui.QColor("#56607A"), 1.2))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, radius * 0.64, radius * 0.64)

        raw_point = QtCore.QPointF(center.x() + raw[0] * radius * 0.55, center.y() - raw[1] * radius * 0.55)
        fixed_point = QtCore.QPointF(
            center.x() + fixed[0] * radius * 0.55,
            center.y() - fixed[1] * radius * 0.55,
        )

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#F0AD52"))
        painter.drawEllipse(raw_point, 3.6, 3.6)
        painter.setBrush(QtGui.QColor("#36EFA6"))
        painter.drawEllipse(fixed_point, 3.2, 3.2)


class DriftlineMainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Driftline Pro - Industry Stick Drift Studio")
        self.resize(1500, 900)

        self.joystick: Optional[core.pygame.joystick.Joystick] = None
        self.controller_info: Optional[core.ControllerInfo] = None
        self.profile: Optional[core.ControllerProfile] = None
        self.profile_path: Optional[pathlib.Path] = None
        self.live_running = False

        self._prev_left = (0.0, 0.0)
        self._prev_right = (0.0, 0.0)

        core.init_input_system()

        self._build_ui()
        self.refresh_controllers(select_first=True)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._poll_input)
        self.timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        self.live_running = False
        if self.joystick is not None:
            try:
                self.joystick.quit()
            except Exception:
                pass
            self.joystick = None
        core.shutdown_input_system()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #090B12;
            }
            QWidget {
                color: #E9EDF7;
                font-family: 'Avenir Next', 'SF Pro Display', 'Helvetica Neue', sans-serif;
                font-size: 12px;
            }
            QFrame#topBar, QFrame#panelCard, QFrame#centerCard, QFrame#logCard {
                background: #131727;
                border: 1px solid #2A3047;
                border-radius: 14px;
            }
            QLabel#brand {
                font-size: 20px;
                font-weight: 700;
                color: #D4DF3A;
                letter-spacing: 1px;
            }
            QLabel#statusBadge {
                background: #1D2538;
                border: 1px solid #374361;
                border-radius: 12px;
                padding: 5px 10px;
                color: #C9D3EE;
                font-weight: 600;
            }
            QPushButton {
                background: #1E263A;
                border: 1px solid #3B4663;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #25304A;
                border: 1px solid #4A587B;
            }
            QPushButton#primary {
                background: #D4DF3A;
                color: #171A24;
                border: none;
                font-weight: 700;
            }
            QPushButton#danger {
                background: #D85F5F;
                color: #FFFFFF;
                border: none;
                font-weight: 700;
            }
            QComboBox {
                background: #1C2235;
                border: 1px solid #3B4460;
                border-radius: 8px;
                padding: 7px 10px;
                min-width: 340px;
            }
            QTabWidget::pane {
                border: 1px solid #2D344B;
                border-radius: 8px;
                background: #121722;
            }
            QTabBar::tab {
                background: #171D2B;
                border: 1px solid #2C354D;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 6px 10px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #222B3F;
                color: #D4DF3A;
                border-color: #4A5575;
            }
            QSlider::groove:horizontal {
                border: 1px solid #2E3751;
                height: 6px;
                background: #1C2233;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #D4DF3A;
                border: 1px solid #B8C230;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QPlainTextEdit {
                background: #0D111A;
                border: 1px solid #28324C;
                border-radius: 10px;
                color: #C6D0EA;
            }
            """
        )

        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(14)

        top = QtWidgets.QFrame(objectName="topBar")
        top_layout = QtWidgets.QHBoxLayout(top)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(10)

        brand = QtWidgets.QLabel("DRIFTLINE PRO", objectName="brand")
        top_layout.addWidget(brand)
        top_layout.addSpacing(12)

        self.controller_combo = QtWidgets.QComboBox()
        top_layout.addWidget(self.controller_combo)

        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_controllers)
        top_layout.addWidget(refresh_btn)

        connect_btn = QtWidgets.QPushButton("Connect")
        connect_btn.clicked.connect(self.connect_selected)
        top_layout.addWidget(connect_btn)

        top_layout.addStretch(1)

        self.status_badge = QtWidgets.QLabel("Idle", objectName="statusBadge")
        top_layout.addWidget(self.status_badge)

        outer.addWidget(top)

        center_split = QtWidgets.QHBoxLayout()
        center_split.setSpacing(14)

        self.left_panel = self._build_stick_panel("Left Stick")
        center_split.addWidget(self.left_panel.container, 3)

        center_card = QtWidgets.QFrame(objectName="centerCard")
        center_layout = QtWidgets.QVBoxLayout(center_card)
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(10)

        self.controller_canvas = ControllerCanvas()
        center_layout.addWidget(self.controller_canvas, 8)

        stats_row = QtWidgets.QHBoxLayout()
        self.connected_label = QtWidgets.QLabel("Connected: none")
        self.profile_label = QtWidgets.QLabel("Profile: none")
        self.quality_label = QtWidgets.QLabel("Drift grade: unknown")
        stats_row.addWidget(self.connected_label)
        stats_row.addSpacing(8)
        stats_row.addWidget(self.profile_label, 1)
        stats_row.addWidget(self.quality_label)
        center_layout.addLayout(stats_row)

        center_split.addWidget(center_card, 5)

        self.right_panel = self._build_stick_panel("Right Stick")
        center_split.addWidget(self.right_panel.container, 3)

        outer.addLayout(center_split, 10)

        controls = QtWidgets.QFrame(objectName="centerCard")
        controls_layout = QtWidgets.QHBoxLayout(controls)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(8)

        quickfix_btn = QtWidgets.QPushButton("Quick Fix")
        quickfix_btn.setObjectName("primary")
        quickfix_btn.clicked.connect(self.quick_fix)
        controls_layout.addWidget(quickfix_btn)

        calibrate_btn = QtWidgets.QPushButton("Calibrate")
        calibrate_btn.clicked.connect(self.calibrate_controller)
        controls_layout.addWidget(calibrate_btn)

        start_btn = QtWidgets.QPushButton("Start Live")
        start_btn.clicked.connect(self.start_live)
        controls_layout.addWidget(start_btn)

        stop_btn = QtWidgets.QPushButton("Stop Live")
        stop_btn.setObjectName("danger")
        stop_btn.clicked.connect(self.stop_live)
        controls_layout.addWidget(stop_btn)

        save_btn = QtWidgets.QPushButton("Save Profile")
        save_btn.clicked.connect(self.save_profile_as)
        controls_layout.addWidget(save_btn)

        load_btn = QtWidgets.QPushButton("Load Profile")
        load_btn.clicked.connect(self.load_profile_dialog)
        controls_layout.addWidget(load_btn)

        export_btn = QtWidgets.QPushButton("Export Steam Hint")
        export_btn.clicked.connect(self.export_steam_hint)
        controls_layout.addWidget(export_btn)

        doctor_btn = QtWidgets.QPushButton("Doctor")
        doctor_btn.clicked.connect(self.run_doctor)
        controls_layout.addWidget(doctor_btn)

        controls_layout.addStretch(1)
        outer.addWidget(controls)

        log_card = QtWidgets.QFrame(objectName="logCard")
        log_layout = QtWidgets.QVBoxLayout(log_card)
        log_layout.setContentsMargins(10, 10, 10, 10)
        log_layout.setSpacing(6)
        log_title = QtWidgets.QLabel("Session Log")
        log_layout.addWidget(log_title)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(130)
        log_layout.addWidget(self.log_box)
        outer.addWidget(log_card)

        self._set_status("Ready")

    def _build_stick_panel(self, title: str) -> StickPanelRefs:
        card = QtWidgets.QFrame(objectName="panelCard")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel(title)
        heading_font = heading.font()
        heading_font.setPointSize(14)
        heading_font.setWeight(QtGui.QFont.DemiBold)
        heading.setFont(heading_font)
        layout.addWidget(heading)

        scope = StickScope(f"{title} Scope")
        layout.addWidget(scope, 5)

        tabs = QtWidgets.QTabWidget()

        deadzone_tab = QtWidgets.QWidget()
        deadzone_layout = QtWidgets.QVBoxLayout(deadzone_tab)
        deadzone_layout.setContentsMargins(10, 10, 10, 10)
        deadzone_layout.setSpacing(10)

        auto_check = QtWidgets.QCheckBox("Auto deadzone from calibration")
        auto_check.setChecked(True)
        deadzone_layout.addWidget(auto_check)

        x_slider, x_value = self._slider_row("X deadzone", deadzone_layout)
        y_slider, y_value = self._slider_row("Y deadzone", deadzone_layout)

        deadzone_layout.addStretch(1)

        tuning_tab = QtWidgets.QWidget()
        tuning_layout = QtWidgets.QVBoxLayout(tuning_tab)
        tuning_layout.setContentsMargins(10, 10, 10, 10)
        tuning_layout.setSpacing(10)

        curve_slider, curve_value = self._slider_row(
            "Response curve", tuning_layout, minimum=50, maximum=200, value=100, suffix="%"
        )
        smooth_slider, smooth_value = self._slider_row(
            "Smoothing", tuning_layout, minimum=0, maximum=90, value=35, suffix="%"
        )
        tuning_layout.addStretch(1)

        diag_tab = QtWidgets.QWidget()
        diag_layout = QtWidgets.QVBoxLayout(diag_tab)
        diag_layout.setContentsMargins(10, 10, 10, 10)
        diag_layout.setSpacing(8)

        raw_label = QtWidgets.QLabel("Raw: (0.000, 0.000)")
        fixed_label = QtWidgets.QLabel("Fixed: (0.000, 0.000)")
        center_label = QtWidgets.QLabel("Center offset: n/a")
        health_label = QtWidgets.QLabel("Health: unknown")
        for widget in (raw_label, fixed_label, center_label, health_label):
            diag_layout.addWidget(widget)
        diag_layout.addStretch(1)

        tabs.addTab(deadzone_tab, "Deadzone")
        tabs.addTab(tuning_tab, "Sensitivity")
        tabs.addTab(diag_tab, "Diagnostics")

        layout.addWidget(tabs, 4)

        panel = StickPanelRefs(
            side="Left" if "Left" in title else "Right",
            container=card,
            scope=scope,
            auto_deadzone=auto_check,
            x_slider=x_slider,
            y_slider=y_slider,
            x_value=x_value,
            y_value=y_value,
            curve_slider=curve_slider,
            curve_value=curve_value,
            smooth_slider=smooth_slider,
            smooth_value=smooth_value,
            raw_label=raw_label,
            fixed_label=fixed_label,
            center_label=center_label,
            health_label=health_label,
        )

        auto_check.toggled.connect(lambda checked, p=panel: self._toggle_manual_sliders(p, checked))
        x_slider.valueChanged.connect(lambda value, label=x_value: label.setText(f"{value}%"))
        y_slider.valueChanged.connect(lambda value, label=y_value: label.setText(f"{value}%"))
        curve_slider.valueChanged.connect(lambda value, label=curve_value: label.setText(f"{value}%"))
        smooth_slider.valueChanged.connect(lambda value, label=smooth_value: label.setText(f"{value}%"))

        self._toggle_manual_sliders(panel, True)
        return panel

    def _slider_row(
        self,
        label_text: str,
        parent_layout: QtWidgets.QVBoxLayout,
        minimum: int = 1,
        maximum: int = 35,
        value: int = 8,
        suffix: str = "%",
    ) -> tuple[QtWidgets.QSlider, QtWidgets.QLabel]:
        row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(label_text)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        value_label = QtWidgets.QLabel(f"{value}{suffix}")
        value_label.setMinimumWidth(46)
        value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(value_label)

        parent_layout.addLayout(row)
        return slider, value_label

    def _toggle_manual_sliders(self, panel: StickPanelRefs, auto_enabled: bool) -> None:
        panel.x_slider.setEnabled(not auto_enabled)
        panel.y_slider.setEnabled(not auto_enabled)

    def _log(self, message: str) -> None:
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {message}")
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _set_status(self, message: str) -> None:
        self.status_badge.setText(message)

    def refresh_controllers(self, select_first: bool = False) -> None:
        self.controller_combo.clear()
        controllers = core.list_controllers()
        for controller in controllers:
            text = (
                f"[{controller.index}] {controller.name} "
                f"(axes={controller.axis_count}, buttons={controller.button_count})"
            )
            self.controller_combo.addItem(text, controller.index)

        if controllers and select_first:
            self.controller_combo.setCurrentIndex(0)

        if not controllers:
            self._set_status("No controller")
            self.connected_label.setText("Connected: none")
        else:
            self._set_status("Controllers found")

    def connect_selected(self) -> None:
        if self.controller_combo.count() == 0:
            self.refresh_controllers(select_first=True)
            if self.controller_combo.count() == 0:
                QtWidgets.QMessageBox.warning(self, "No controller", "Connect a controller and try again.")
                return

        index = self.controller_combo.currentData()
        if index is None:
            QtWidgets.QMessageBox.warning(self, "Selection error", "Could not read selected controller index.")
            return

        if self.joystick is not None:
            try:
                self.joystick.quit()
            except Exception:
                pass
            self.joystick = None

        joystick, info = core.init_controller(int(index))
        self.joystick = joystick
        self.controller_info = info
        self.connected_label.setText(f"Connected: {info.name} (index {info.index})")
        self._set_status("Connected")
        self._log(f"Connected {info.name} (guid={info.guid})")

        self.profile_path = core.choose_profile_path(info, None)
        self.profile_label.setText(f"Profile: {self.profile_path}")

        if self.profile_path.exists():
            try:
                self.profile = core.load_profile(self.profile_path)
                self._log(f"Loaded profile {self.profile_path}")
                self._sync_panels_with_profile()
                self._update_quality_badge()
            except Exception as exc:
                self.profile = None
                self._log(f"Profile read failed, recalibration needed: {exc}")
        else:
            self.profile = None

    def _sync_panels_with_profile(self) -> None:
        if self.profile is None:
            return

        left = self.profile.left
        right = self.profile.right

        self.left_panel.x_slider.setValue(int(round(left.x.deadzone * 100)))
        self.left_panel.y_slider.setValue(int(round(left.y.deadzone * 100)))
        self.right_panel.x_slider.setValue(int(round(right.x.deadzone * 100)))
        self.right_panel.y_slider.setValue(int(round(right.y.deadzone * 100)))

        self.left_panel.center_label.setText(
            f"Center offset: x={left.x.center:+0.4f}, y={left.y.center:+0.4f}"
        )
        self.right_panel.center_label.setText(
            f"Center offset: x={right.x.center:+0.4f}, y={right.y.center:+0.4f}"
        )

        self.left_panel.health_label.setText(
            f"Health: x={core.axis_health(left.x.deadzone)}, y={core.axis_health(left.y.deadzone)}"
        )
        self.right_panel.health_label.setText(
            f"Health: x={core.axis_health(right.x.deadzone)}, y={core.axis_health(right.y.deadzone)}"
        )

    def _update_quality_badge(self) -> None:
        if self.profile is None:
            self.quality_label.setText("Drift grade: unknown")
            return

        quality, findings = core.profile_quality(self.profile)
        if quality == "good":
            text = "Drift grade: stable"
        elif quality == "warn":
            text = "Drift grade: heavy but compensated"
        else:
            text = "Drift grade: severe"
        self.quality_label.setText(text)
        if findings:
            self._log(" | ".join(findings))

    def _sample_axis_spans(self, seconds: float) -> list[float]:
        if self.joystick is None:
            raise RuntimeError("Controller is not connected.")

        axis_count = self.joystick.get_numaxes()
        mins = [1.0] * axis_count
        maxs = [-1.0] * axis_count
        end = time.monotonic() + seconds

        while time.monotonic() < end:
            core.pygame.event.pump()
            for axis in range(axis_count):
                value = float(self.joystick.get_axis(axis))
                mins[axis] = min(mins[axis], value)
                maxs[axis] = max(maxs[axis], value)
            QtWidgets.QApplication.processEvents()
            time.sleep(1 / 220)

        return [maxs[i] - mins[i] for i in range(axis_count)]

    def _run_mapping_wizard(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        if self.joystick is None:
            raise RuntimeError("Connect a controller first.")

        if self.joystick.get_numaxes() < 4:
            raise RuntimeError("Controller reports fewer than 4 axes.")

        steps = [
            "Move ONLY LEFT stick in full circles for 2.5 seconds, then click OK.",
            "Keep moving ONLY LEFT stick in full circles for another 2.5 seconds, then click OK.",
            "Move ONLY RIGHT stick in full circles for 2.5 seconds, then click OK.",
            "Keep moving ONLY RIGHT stick in full circles for another 2.5 seconds, then click OK.",
        ]

        detected: list[int] = []
        spans: list[float] = []

        for step in steps:
            QtWidgets.QMessageBox.information(self, "Axis Mapping", step)
            axis_spans = self._sample_axis_spans(2.5)
            axis, span = core.pick_top_axis(axis_spans, excluded=detected)
            detected.append(axis)
            spans.append(span)
            self._log(f"Mapping: detected axis {axis} span={span:.3f}")

        left_axes = (detected[0], detected[1])
        right_axes = (detected[2], detected[3])

        if min(spans) < 0.18:
            self._log("Mapping confidence low. Falling back to left=(0,1), right=(2,3).")
            left_axes = (0, 1)
            right_axes = (2, 3)

        return left_axes, right_axes

    def calibrate_controller(self) -> None:
        if self.controller_info is None or self.joystick is None:
            self.connect_selected()
            if self.controller_info is None or self.joystick is None:
                return

        try:
            left_axes, right_axes = self._run_mapping_wizard()
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(self, "Calibration", str(exc))
            return

        attempts = 3
        best_profile: Optional[core.ControllerProfile] = None
        best_score = float("inf")

        progress = QtWidgets.QProgressDialog("Calibrating... keep sticks untouched", "Cancel", 0, attempts, self)
        progress.setWindowTitle("Calibration")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.show()

        for attempt in range(attempts):
            if progress.wasCanceled():
                self._log("Calibration canceled by user")
                return

            progress.setValue(attempt)
            progress.setLabelText(f"Calibration pass {attempt + 1}/{attempts} in progress...")
            QtWidgets.QApplication.processEvents()

            samples = core.collect_axis_samples(
                self.joystick,
                [left_axes[0], left_axes[1], right_axes[0], right_axes[1]],
                3.5,
            )

            candidate = core.ControllerProfile(
                controller_name=self.controller_info.name,
                controller_guid=self.controller_info.guid,
                generated_at=dt.datetime.now().astimezone().isoformat(),
                axis_count=self.joystick.get_numaxes(),
                left=core.StickCalibration(
                    x=core.build_axis_calibration(samples[left_axes[0]], left_axes[0]),
                    y=core.build_axis_calibration(samples[left_axes[1]], left_axes[1]),
                ),
                right=core.StickCalibration(
                    x=core.build_axis_calibration(samples[right_axes[0]], right_axes[0]),
                    y=core.build_axis_calibration(samples[right_axes[1]], right_axes[1]),
                ),
            )

            quality, _ = core.profile_quality(candidate)
            score = (
                candidate.left.x.deadzone
                + candidate.left.y.deadzone
                + candidate.right.x.deadzone
                + candidate.right.y.deadzone
                + abs(candidate.left.x.center)
                + abs(candidate.left.y.center)
                + abs(candidate.right.x.center)
                + abs(candidate.right.y.center)
            )

            if score < best_score:
                best_profile = candidate
                best_score = score

            self._log(f"Calibration pass {attempt + 1}: quality={quality}, score={score:.3f}")
            if quality == "good":
                break

        progress.setValue(attempts)

        if best_profile is None:
            QtWidgets.QMessageBox.critical(self, "Calibration", "Calibration failed.")
            return

        self.profile = best_profile
        self._sync_panels_with_profile()
        self._update_quality_badge()

        if self.profile_path is None:
            self.profile_path = core.profile_path_for_controller(self.controller_info)

        core.save_profile(best_profile, self.profile_path)
        hint_path = core.write_steam_hint(best_profile, self.profile_path)
        self.profile_label.setText(f"Profile: {self.profile_path}")
        self._log(f"Saved profile {self.profile_path}")
        self._log(f"Saved Steam hint {hint_path}")
        self._set_status("Calibrated")

        QtWidgets.QMessageBox.information(
            self,
            "Calibration complete",
            "Calibration complete and profile saved.\nYou can now run live compensation.",
        )

    def quick_fix(self) -> None:
        if self.controller_info is None:
            self.connect_selected()
            if self.controller_info is None:
                return

        if self.profile is None:
            if self.profile_path and self.profile_path.exists():
                try:
                    self.profile = core.load_profile(self.profile_path)
                    self._sync_panels_with_profile()
                    self._update_quality_badge()
                    self._log(f"Loaded profile {self.profile_path}")
                except Exception:
                    self.profile = None

        if self.profile is None:
            self.calibrate_controller()
            if self.profile is None:
                return

        self.start_live()
        self._set_status("Quick Fix Active")

    def start_live(self) -> None:
        if self.profile is None:
            QtWidgets.QMessageBox.warning(self, "No profile", "Calibrate or load a profile first.")
            return
        if self.joystick is None:
            QtWidgets.QMessageBox.warning(self, "No controller", "Connect a controller first.")
            return
        self.live_running = True
        self._set_status("Live compensation")
        self._log("Live compensation started")

    def stop_live(self) -> None:
        self.live_running = False
        self._set_status("Paused")
        self._log("Live compensation stopped")

    def _manual_or_auto_axis(
        self,
        axis: core.AxisCalibration,
        value_percent: int,
        auto_enabled: bool,
    ) -> core.AxisCalibration:
        if auto_enabled:
            return axis
        manual_deadzone = clamp(value_percent / 100.0, 0.01, 0.35)
        return core.AxisCalibration(axis=axis.axis, center=axis.center, deadzone=manual_deadzone)

    def _apply_side(
        self,
        raw: Tuple[float, float],
        x_axis: core.AxisCalibration,
        y_axis: core.AxisCalibration,
        panel: StickPanelRefs,
        prev_state: Tuple[float, float],
    ) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
        ax = self._manual_or_auto_axis(x_axis, panel.x_slider.value(), panel.auto_deadzone.isChecked())
        ay = self._manual_or_auto_axis(y_axis, panel.y_slider.value(), panel.auto_deadzone.isChecked())

        fixed_x = core.compensate_axis(raw[0], ax)
        fixed_y = core.compensate_axis(raw[1], ay)

        gamma = panel.curve_slider.value() / 100.0
        fixed_x = response_curve(fixed_x, gamma)
        fixed_y = response_curve(fixed_y, gamma)

        smooth_strength = panel.smooth_slider.value() / 100.0
        alpha = clamp(1.0 - smooth_strength, 0.05, 1.0)
        smooth_x = prev_state[0] + alpha * (fixed_x - prev_state[0])
        smooth_y = prev_state[1] + alpha * (fixed_y - prev_state[1])

        deadzone_draw = max(ax.deadzone, ay.deadzone)
        return (smooth_x, smooth_y), (ax.deadzone, ay.deadzone), deadzone_draw

    def _poll_input(self) -> None:
        if not self.live_running:
            return
        if self.joystick is None or self.profile is None:
            return

        try:
            core.pygame.event.pump()
            left_raw = core.read_stick(self.joystick, self.profile.left)
            right_raw = core.read_stick(self.joystick, self.profile.right)
        except core.pygame.error:
            self.live_running = False
            self._set_status("Disconnected")
            self._log("Controller disconnected")
            return

        left_fixed, _, left_dz = self._apply_side(
            left_raw,
            self.profile.left.x,
            self.profile.left.y,
            self.left_panel,
            self._prev_left,
        )
        right_fixed, _, right_dz = self._apply_side(
            right_raw,
            self.profile.right.x,
            self.profile.right.y,
            self.right_panel,
            self._prev_right,
        )

        self._prev_left = left_fixed
        self._prev_right = right_fixed

        self.left_panel.scope.set_state(left_raw, left_fixed, left_dz)
        self.right_panel.scope.set_state(right_raw, right_fixed, right_dz)
        self.controller_canvas.set_state(left_raw, right_raw, left_fixed, right_fixed)

        self.left_panel.raw_label.setText(f"Raw:   {format_vec(left_raw)}")
        self.left_panel.fixed_label.setText(f"Fixed: {format_vec(left_fixed)}")
        self.right_panel.raw_label.setText(f"Raw:   {format_vec(right_raw)}")
        self.right_panel.fixed_label.setText(f"Fixed: {format_vec(right_fixed)}")

    def save_profile_as(self) -> None:
        if self.profile is None:
            QtWidgets.QMessageBox.warning(self, "No profile", "Calibrate or load a profile first.")
            return

        default_path = str(self.profile_path or pathlib.Path("profiles/custom_profile.json"))
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save profile",
            default_path,
            "JSON files (*.json)",
        )
        if not filename:
            return

        path = pathlib.Path(filename)
        core.save_profile(self.profile, path)
        self.profile_path = path
        self.profile_label.setText(f"Profile: {path}")
        self._log(f"Saved profile {path}")

    def load_profile_dialog(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load profile",
            str(pathlib.Path("profiles")),
            "JSON files (*.json)",
        )
        if not filename:
            return

        path = pathlib.Path(filename)
        try:
            profile = core.load_profile(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Load failed", str(exc))
            return

        self.profile = profile
        self.profile_path = path
        self.profile_label.setText(f"Profile: {path}")
        self._sync_panels_with_profile()
        self._update_quality_badge()
        self._log(f"Loaded profile {path}")

    def export_steam_hint(self) -> None:
        if self.profile is None:
            QtWidgets.QMessageBox.warning(self, "No profile", "Calibrate or load a profile first.")
            return
        if self.profile_path is None:
            QtWidgets.QMessageBox.warning(self, "No profile path", "Save profile first.")
            return

        hint_path = core.write_steam_hint(self.profile, self.profile_path)
        self._log(f"Exported Steam hint {hint_path}")
        QtWidgets.QMessageBox.information(self, "Steam hint", f"Saved:\n{hint_path}")

    def run_doctor(self) -> None:
        if self.profile is None:
            QtWidgets.QMessageBox.warning(self, "No profile", "Calibrate or load a profile first.")
            return

        quality, findings = core.profile_quality(self.profile)
        if quality == "good":
            summary = "Profile quality is stable."
        elif quality == "warn":
            summary = "Profile quality is usable but drift is heavy."
        else:
            summary = "Profile quality is severe; hardware wear may be high."

        details = "\n".join(findings) if findings else "No warnings detected."
        QtWidgets.QMessageBox.information(self, "Drift Doctor", f"{summary}\n\n{details}")
        self._log(f"Doctor result: {summary}")


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = DriftlineMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
