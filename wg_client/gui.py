"""
Graphical frontend: a system-tray application covering every CLI operation
(connect, disconnect, reconnect, status, identity, settings). Qt gives one
codebase with a native tray on Windows, macOS and Linux; all real work goes
through :mod:`wg_client.ops`, shared with the CLI.

Run with ``wg-client-gui`` (installed by the ``gui`` extra: PySide6).
"""

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from wg_client import ops, tunnel
from wg_client.i18n import _

ICON_PATH = Path(__file__).parent / "assets" / "wdg-mark.svg"
STATUS_REFRESH_MS = 10_000


class Worker(QThread):
    """Run one ops function off the UI thread; relay progress and outcome."""

    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.succeeded.emit(self._fn(self.progress.emit))
        except ops.OpError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # unexpected: still surface it readably
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("WDG — remote access"))
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(680, 560)
        self._worker = None

        central = QWidget()
        layout = QVBoxLayout(central)

        self.identity_label = QLabel(_("Not signed in."))
        self.identity_label.setWordWrap(True)
        layout.addWidget(self.identity_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [_("Service"), _("Gateway"), _("Interface"), _("Handshake")]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.connect_btn = QPushButton(_("Connect"))
        self.reconnect_btn = QPushButton(_("Reconnect"))
        self.disconnect_btn = QPushButton(_("Disconnect"))
        self.whoami_btn = QPushButton(_("Who am I?"))
        for b in (self.connect_btn, self.reconnect_btn,
                  self.disconnect_btn, self.whoami_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        settings_box = QGroupBox(_("Settings"))
        form = QHBoxLayout(settings_box)
        form.addWidget(QLabel(_("Server:")))
        self.server_edit = QLineEdit()
        form.addWidget(self.server_edit, stretch=1)
        self.pq_check = QCheckBox(_("Require post-quantum TLS"))
        form.addWidget(self.pq_check)
        self.save_btn = QPushButton(_("Save"))
        form.addWidget(self.save_btn)
        layout.addWidget(settings_box)

        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setMaximumBlockCount(500)
        layout.addWidget(self.journal)

        self.setCentralWidget(central)

        self.connect_btn.clicked.connect(lambda: self.run_op(ops.connect))
        self.reconnect_btn.clicked.connect(self._reconnect)
        self.disconnect_btn.clicked.connect(lambda: self.run_op(ops.disconnect))
        self.whoami_btn.clicked.connect(self._whoami)
        self.save_btn.clicked.connect(self._save_settings)

        self._load_settings()
        self.refresh_status()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start(STATUS_REFRESH_MS)

    # ----- settings ---------------------------------------------------------

    def _load_settings(self):
        cfg = ops.settings()
        self.server_edit.setText(cfg.get("server", ""))
        self.pq_check.setChecked(bool(cfg.get("require_pq", False)))

    def _save_settings(self):
        ops.save_settings(self.server_edit.text().strip(),
                          self.pq_check.isChecked())
        self.log(_("Configuration saved."))

    # ----- operations -------------------------------------------------------

    def busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def run_op(self, fn, then=None):
        if self.busy():
            return
        for b in (self.connect_btn, self.reconnect_btn, self.disconnect_btn,
                  self.whoami_btn):
            b.setEnabled(False)
        self._worker = Worker(fn)
        self._worker.progress.connect(self.log)
        self._worker.failed.connect(self._op_failed)
        self._worker.succeeded.connect(
            lambda result: self._op_done(result, then))
        self._worker.start()

    def _op_done(self, result, then):
        self._release_buttons()
        if then:
            then(result)
        self.refresh_status()

    def _op_failed(self, message):
        self._release_buttons()
        self.log(_("Error: {message}").format(message=message))
        QMessageBox.warning(self, _("WDG — remote access"), message)
        self.refresh_status()

    def _release_buttons(self):
        for b in (self.connect_btn, self.reconnect_btn, self.disconnect_btn,
                  self.whoami_btn):
            b.setEnabled(True)

    def _reconnect(self):
        self.run_op(lambda progress: (ops.disconnect(progress),
                                      ops.connect(progress))[1])

    def _whoami(self):
        def show(who):
            groups = ", ".join(who["groups"]) if who["groups"] else _("(none)")
            self.identity_label.setText(
                _("Signed in as {user} — groups: {groups}").format(
                    user=who["username"], groups=groups))
        self.run_op(lambda progress: ops.identity(progress), then=show)

    # ----- status -----------------------------------------------------------

    def refresh_status(self):
        if self.busy():
            return
        entries = ops.status()
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            if not e["up"]:
                detail = _("down")
            elif e["handshake_age"] is not None:
                detail = _("handshake {age}s ago").format(
                    age=int(e["handshake_age"]))
            else:
                detail = _("no handshake data")
            for col, text in enumerate(
                    (e["service"], e["gateway"], e["iface"], detail)):
                item = QTableWidgetItem(text)
                if not e["up"]:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, col, item)
        return entries

    def log(self, message: str):
        self.journal.appendPlainText(message)


class TrayApplication:
    """The tray icon + menu; the window opens on demand and hides on close."""

    def __init__(self, app: QApplication):
        self.app = app
        self.window = MainWindow()
        self.window.closeEvent = self._hide_instead_of_close

        self.tray = QSystemTrayIcon(QIcon(str(ICON_PATH)))
        menu = QMenu()
        self.open_action = QAction(_("Open WDG"))
        self.connect_action = QAction(_("Connect"))
        self.reconnect_action = QAction(_("Reconnect"))
        self.disconnect_action = QAction(_("Disconnect"))
        self.quit_action = QAction(_("Quit"))
        for a in (self.open_action, self.connect_action, self.reconnect_action,
                  self.disconnect_action):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.quit_action)
        self.tray.setContextMenu(menu)

        self.open_action.triggered.connect(self.show_window)
        self.connect_action.triggered.connect(
            lambda: self.window.run_op(ops.connect))
        self.reconnect_action.triggered.connect(self.window._reconnect)
        self.disconnect_action.triggered.connect(
            lambda: self.window.run_op(ops.disconnect))
        self.quit_action.triggered.connect(self.quit)
        self.tray.activated.connect(self._tray_activated)

        self.tray.setToolTip(_("WDG — remote access"))
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _hide_instead_of_close(self, event):
        event.ignore()
        self.window.hide()
        self.tray.showMessage(
            _("WDG — remote access"),
            _("Still running in the system tray. Quit from the tray menu."),
            QSystemTrayIcon.MessageIcon.Information, 4000)

    def quit(self):
        self.tray.hide()
        self.app.quit()


def _check_wireguard(window: MainWindow):
    """Offer the bundled installer (Windows) or per-OS guidance."""
    if tunnel.wireguard_available():
        return
    if tunnel.bundled_windows_installer() is not None:
        answer = QMessageBox.question(
            window, _("WDG — remote access"),
            _("WireGuard is not installed. Install the bundled official "
              "WireGuard now? (administrator rights required)"))
        if answer == QMessageBox.StandardButton.Yes:
            if tunnel.install_windows_wireguard():
                window.log(_("WireGuard installed."))
                return
        window.log(tunnel.install_hint())
    else:
        QMessageBox.information(window, _("WDG — remote access"),
                                tunnel.install_hint())


def main():
    app = QApplication([])
    app.setApplicationName("wg-client-gui")
    app.setQuitOnLastWindowClosed(False)
    tray_app = TrayApplication(app)
    tray_app.show_window()
    _check_wireguard(tray_app.window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
