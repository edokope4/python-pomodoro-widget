"""Widget Pomodoro siempre visible: minutos de trabajo y de descanso."""

from __future__ import annotations

import math
import sys
import threading
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

Note = tuple[int, int, float]

WORK_MINUTES_RANGE = (1, 120)
REST_MINUTES_RANGE = (1, 60)
DEFAULT_WORK_MINUTES = 25
DEFAULT_REST_MINUTES = 5

WORK_COLOR = "#fab387"
REST_COLOR = "#8aadf4"

# Un tono al empezar el trabajo; tres tonos cortos al terminarlo.
WORK_START_NOTES: list[Note] = [(880, 180, 0.0)]
WORK_END_NOTES: list[Note] = [(1175, 90, 0.07), (1175, 90, 0.07), (1175, 90, 0.0)]

APP_STYLESHEET = """
QWidget#pomodoroWindow {
    background-color: #1c1c28;
    border: 1px solid #34344a;
}
QLabel {
    background: transparent;
    color: #f5f5f7;
}
QLabel#timeLabel {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 26px;
    color: #f8f8f2;
}
QLabel#timeLabel[paused="true"] {
    color: #b8b8cc;
}
QLabel#menuTitle {
    color: #9a9ab3;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#startButton,
QPushButton#resetButton {
    font-size: 11px;
    border: none;
    border-radius: 4px;
    min-height: 22px;
    padding: 0 6px;
}
QPushButton#startButton {
    background-color: #fab387;
    color: #1c1420;
    font-weight: 700;
}
QPushButton#startButton:hover {
    background-color: #ffc19a;
}
QPushButton#startButton[running="true"] {
    background-color: #ed8796;
    color: #1c1420;
}
QPushButton#startButton[running="true"]:hover {
    background-color: #f5a3af;
}
QPushButton#resetButton {
    background-color: #2a2a3d;
    color: #f5f5f7;
    font-weight: 600;
}
QPushButton#resetButton:hover {
    background-color: #36364e;
}
QPushButton#gearButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #b8b8c8;
    padding: 0;
}
QPushButton#gearButton:hover {
    background-color: #2e2e44;
    color: #ffffff;
}
QMenu {
    background-color: #242438;
    color: #f5f5f7;
    border: 1px solid #3d3d56;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    background: transparent;
}
QMenu::item:selected {
    background-color: #34344c;
}
QMenu::separator {
    height: 1px;
    background: #3d3d56;
    margin: 4px 8px;
}
QSpinBox {
    background-color: #2a2a3d;
    color: #f8f8f2;
    border: 1px solid #45455f;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 26px;
    min-width: 108px;
}
"""


def format_remaining(seconds: float) -> str:
    whole = max(0, math.ceil(seconds - 1e-6))
    minutes, secs = divmod(whole, 60)
    return f"{minutes:02d}:{secs:02d}"


def play_notes(notes: list[Note]) -> None:
    """Reproduce tonos sin bloquear la interfaz."""
    if sys.platform != "win32":
        app = QApplication.instance()
        if app is not None:
            for _note in notes:
                app.beep()
        return

    def run() -> None:
        import winsound

        for freq, duration_ms, gap_s in notes:
            try:
                winsound.Beep(freq, duration_ms)
            except RuntimeError:
                return
            if gap_s > 0:
                time.sleep(gap_s)

    threading.Thread(target=run, name="pomodoro-beep", daemon=True).start()


def build_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(WORK_COLOR))
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QColor("#1c1420"))
    painter.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    return QIcon(pixmap)


def _as_point(value: object) -> QPoint | None:
    if isinstance(value, QPoint):
        return value
    if isinstance(value, QPointF):
        return value.toPoint()
    return None


def _read_int(settings: QSettings, key: str, default: int, low: int, high: int) -> int:
    raw = settings.value(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


class StayOpenMenu(QMenu):
    """No se cierra al manipular los campos embebidos."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        action = self.activeAction()
        if isinstance(action, QWidgetAction):
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PomodoroWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            if not app.organizationName():
                app.setOrganizationName("PomodoroWidget")
            if not app.applicationName():
                app.setApplicationName("Pomodoro")

        self.work_minutes = DEFAULT_WORK_MINUTES
        self.rest_minutes = DEFAULT_REST_MINUTES
        self._load_durations()

        self.phase = "work"
        self.running = False
        self._announced_work = False
        self.remaining = float(self.work_minutes * 60)
        self.lap_seconds = self.remaining
        self._deadline = time.monotonic()
        self._drag_offset: QPoint | None = None

        self.setObjectName("pomodoroWindow")
        self.setWindowTitle("Pomodoro")
        self.setFixedSize(150, 104)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._build_ui()
        self._build_menu()
        self._restore_position()

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

        self._apply_phase()
        self._set_running(False)
        self._update_display()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self.phase_label = QLabel("Trabajo")
        self.phase_label.setObjectName("phaseLabel")
        self.phase_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.gear_btn = QPushButton("\u2699")
        self.gear_btn.setObjectName("gearButton")
        self.gear_btn.setFont(QFont("Segoe UI Symbol", 9))
        self.gear_btn.setFixedSize(18, 18)
        self.gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear_btn.setToolTip("Configurar minutos de trabajo y descanso")
        self.gear_btn.setAccessibleName("Configuración")
        self.gear_btn.clicked.connect(self._open_menu)

        header.addWidget(self.phase_label)
        header.addStretch(1)
        header.addWidget(self.gear_btn)

        self.time_label = QLabel("25:00")
        self.time_label.setObjectName("timeLabel")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setMinimumHeight(28)

        self.bar = QProgressBar()
        self.bar.setObjectName("timeBar")
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("startButton")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setToolTip("Iniciar o pausar el temporizador")
        self.start_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.start_btn.clicked.connect(self._toggle)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setObjectName("resetButton")
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setToolTip("Reiniciar al comienzo del trabajo")
        self.reset_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.reset_btn.clicked.connect(self._reset)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.setSpacing(4)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.reset_btn)

        root.addLayout(header)
        root.addWidget(self.time_label)
        root.addWidget(self.bar)
        root.addLayout(buttons)

    def _build_menu(self) -> None:
        self.menu = StayOpenMenu(self)

        host = QWidget()
        host.setMinimumWidth(230)
        column = QVBoxLayout(host)
        column.setContentsMargins(12, 8, 12, 6)
        column.setSpacing(8)

        title = QLabel("Duración")
        title.setObjectName("menuTitle")
        column.addWidget(title)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.work_spin = self._make_spin(*WORK_MINUTES_RANGE, self.work_minutes)
        self.rest_spin = self._make_spin(*REST_MINUTES_RANGE, self.rest_minutes)
        self.work_spin.valueChanged.connect(self._on_work_minutes)
        self.rest_spin.valueChanged.connect(self._on_rest_minutes)

        form.addRow("Trabajo", self.work_spin)
        form.addRow("Descanso", self.rest_spin)
        column.addWidget(form_host)

        action = QWidgetAction(self.menu)
        action.setDefaultWidget(host)
        self.menu.addAction(action)
        self.menu.addSeparator()
        self.menu.addAction(QAction("Salir", self, triggered=self.close))
        self.menu.aboutToShow.connect(self._sync_menu_values)

    def _make_spin(self, low: int, high: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(" min")
        spin.setAccelerated(True)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        return spin

    def _open_menu(self) -> None:
        self.menu.adjustSize()
        anchor = self.gear_btn.mapToGlobal(QPoint(self.gear_btn.width(), self.gear_btn.height() + 4))
        x = anchor.x() - self.menu.sizeHint().width()
        self.menu.popup(QPoint(x, anchor.y()))

    def _sync_menu_values(self) -> None:
        self.work_spin.blockSignals(True)
        self.rest_spin.blockSignals(True)
        self.work_spin.setValue(self.work_minutes)
        self.rest_spin.setValue(self.rest_minutes)
        self.work_spin.blockSignals(False)
        self.rest_spin.blockSignals(False)

    def _load_durations(self) -> None:
        settings = QSettings()
        self.work_minutes = _read_int(
            settings, "work_minutes", DEFAULT_WORK_MINUTES, *WORK_MINUTES_RANGE
        )
        self.rest_minutes = _read_int(
            settings, "rest_minutes", DEFAULT_REST_MINUTES, *REST_MINUTES_RANGE
        )

    def _restore_position(self) -> None:
        saved = _as_point(QSettings().value("window_pos"))
        if saved is not None and self._position_on_screen(saved):
            self.move(saved)
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 28, area.top() + 28)

    def _position_on_screen(self, pos: QPoint) -> bool:
        rect = QRect(pos, self.size())
        probe = rect.adjusted(24, 24, -24, -24)
        if probe.width() <= 0 or probe.height() <= 0:
            probe = rect
        return any(
            screen.availableGeometry().intersects(probe) for screen in QApplication.screens()
        )

    def _save_settings(self) -> None:
        settings = QSettings()
        settings.setValue("work_minutes", self.work_minutes)
        settings.setValue("rest_minutes", self.rest_minutes)
        settings.setValue("window_pos", self.pos())

    def _on_work_minutes(self, minutes: int) -> None:
        previous = self.work_minutes
        self.work_minutes = minutes
        self._save_settings()
        if (
            not self.running
            and self.phase == "work"
            and not self._announced_work
            and abs(self.remaining - previous * 60) < 1
        ):
            self.remaining = float(minutes * 60)
            self.lap_seconds = self.remaining
            self._update_display()

    def _on_rest_minutes(self, minutes: int) -> None:
        previous = self.rest_minutes
        self.rest_minutes = minutes
        self._save_settings()
        if (
            not self.running
            and self.phase == "rest"
            and abs(self.remaining - previous * 60) < 1
        ):
            self.remaining = float(minutes * 60)
            self.lap_seconds = self.remaining
            self._update_display()

    def _set_running(self, running: bool) -> None:
        self.start_btn.setText("Stop" if running else "Start")
        self.start_btn.setProperty("running", "true" if running else "false")
        self.time_label.setProperty("paused", "false" if running else "true")
        for widget in (self.start_btn, self.time_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _apply_phase(self) -> None:
        if self.phase == "work":
            name, color = "Trabajo", WORK_COLOR
        else:
            name, color = "Descanso", REST_COLOR
        self.phase_label.setText(name)
        self.phase_label.setStyleSheet(
            "background: transparent;"
            "font-size: 11px;"
            "font-weight: 700;"
            f"color: {color};"
        )
        self.bar.setStyleSheet(
            "QProgressBar {"
            "background: #2a2a3d;"
            "border: none;"
            "border-radius: 1px;"
            "}"
            "QProgressBar::chunk {"
            f"background: {color};"
            "border-radius: 1px;"
            "}"
        )

    def _update_display(self) -> None:
        self.time_label.setText(format_remaining(self.remaining))
        total = self.lap_seconds if self.lap_seconds > 0 else 1.0
        portion = max(0.0, min(1.0, self.remaining / total))
        self.bar.setValue(int(round(portion * 1000)))

    def _toggle(self) -> None:
        if self.running:
            self._pause()
        else:
            self._start()

    def _start(self) -> None:
        if self.running:
            return
        if self.phase == "work" and not self._announced_work:
            play_notes(WORK_START_NOTES)
            self._announced_work = True
        self.running = True
        self._deadline = time.monotonic() + max(0.0, self.remaining)
        self.timer.start()
        self._set_running(True)
        self._update_display()

    def _pause(self) -> None:
        if not self.running:
            return
        self.remaining = max(0.0, self._deadline - time.monotonic())
        self.running = False
        self.timer.stop()
        self._set_running(False)
        self._update_display()

    def _reset(self) -> None:
        self.timer.stop()
        self.running = False
        self.phase = "work"
        self._announced_work = False
        self.remaining = float(self.work_minutes * 60)
        self.lap_seconds = self.remaining
        self._set_running(False)
        self._apply_phase()
        self._update_display()

    def _tick(self) -> None:
        if not self.running:
            return
        left = self._deadline - time.monotonic()
        if left <= 0:
            self._advance_phase()
            return
        self.remaining = left
        self._update_display()

    def _advance_phase(self) -> None:
        if self.phase == "work":
            play_notes(WORK_END_NOTES)
            self.phase = "rest"
            self._announced_work = False
            seconds = self.rest_minutes * 60
        else:
            self.phase = "work"
            seconds = self.work_minutes * 60
            play_notes(WORK_START_NOTES)
            self._announced_work = True
        self.remaining = float(seconds)
        self.lap_seconds = self.remaining
        self._deadline = time.monotonic() + self.remaining
        self._apply_phase()
        self._update_display()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.releaseMouse()
            self._save_settings()
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.timer.stop()
        self._save_settings()
        super().closeEvent(event)


def _win_app_id() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Pomodoro.Widget")


def _dark_palette() -> QPalette:
    palette = QPalette()
    text = QColor("#f5f5f7")
    palette.setColor(QPalette.ColorRole.Window, QColor("#1c1c28"))
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor("#2a2a3d"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#242438"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor("#2a2a3d"))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(WORK_COLOR))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1c1420"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#242438"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    return palette


def main() -> int:
    _win_app_id()
    app = QApplication(sys.argv)
    app.setOrganizationName("PomodoroWidget")
    app.setApplicationName("Pomodoro")
    app.setApplicationDisplayName("Pomodoro")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(APP_STYLESHEET)
    try:
        icon = build_icon()
        app.setWindowIcon(icon)
        window = PomodoroWindow()
        window.setWindowIcon(icon)
        window.show()
    except Exception as exc:
        QMessageBox.critical(None, "Pomodoro", f"No se pudo iniciar:\n{exc}")
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
