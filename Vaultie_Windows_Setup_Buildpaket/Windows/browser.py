"""PrivatBrowser: erster Windows-Desktopbrowser auf Qt WebEngine."""
import json
import html
from datetime import datetime
import os
import re
import shutil
import sys
from functools import partial
from threading import Lock
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode

from PySide6.QtCore import QStandardPaths, Qt, QUrl, QTimer
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QListWidget, QTabBar, QStackedWidget, QToolBar, QToolButton, QSlider, QCheckBox,
    QVBoxLayout, QWidget, QSizePolicy, QStyle)
from PySide6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage,
    QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView
from bandwidth_proxy import LocalBandwidthProxy
from storage_manager import StorageBudget, CLEAN_AT, HARD_LIMIT, GIB

APP_NAME = "Vaultie"
HOME = "vaultie:start"
DEFAULT_SHORTCUTS = (
    ("YouTube", "https://www.youtube.com/", "▶", "yt"),
    ("Discord", "https://discord.com/app", "◉", "discord"),
    ("WhatsApp", "https://web.whatsapp.com/", "◉", "wa"),
    ("Gmail", "https://mail.google.com/", "M", "gmail"),
    ("Drive", "https://drive.google.com/", "▲", "drive"),
)
ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
VPN_LINKS = {"Mullvad VPN": "https://mullvad.net/", "NordVPN": "https://nordvpn.com/"}
# Existing profiles from PrivatBrowser 0.1–0.8 remain on the same computer.
# Windows AppData paths can depend on the application name, so look for the
# old profile before choosing the new stable local location.
def profile_directory():
    """Store Vaultie data in LocalAppData, not Windows Roaming or OneDrive."""
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    target = local / "Vaultie"
    target.mkdir(parents=True, exist_ok=True)
    roaming = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    candidates = [
        roaming / "PrivatBrowser" / "PrivatBrowser",
        roaming / "PrivatBrowser",
        roaming / "browser" / "PrivatBrowser",
        local / "PrivatBrowser" / "PrivatBrowser",
        local / "PrivatBrowser",
        local / "browser" / "PrivatBrowser",
    ]
    # One-time migration of user-created files from previous Vaultie versions.
    # Keep old files untouched rather than deleting potentially unique user data.
    for filename in ("settings.json", "bookmarks.json", "filterliste.txt"):
        destination = target / filename
        if destination.exists():
            continue
        for old in candidates:
            source = old / filename
            if source.is_file():
                try:
                    shutil.copy2(source, destination)
                    break
                except OSError:
                    continue
    return target


DATA = profile_directory()
SETTINGS = DATA / "settings.json"
BOOKMARKS = DATA / "bookmarks.json"
PINNED = DATA / "pinned.json"
HIDDEN_SHORTCUTS = DATA / "hidden_shortcuts.json"
HISTORY = DATA / "history.json"
FILTERS = DATA / "filterliste.txt"
DOWNLOADS = DATA / "Downloads"
DOWNLOADS.mkdir(parents=True, exist_ok=True)

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "twclid", "igshid", "mc_cid", "mc_eid"
})


def clean_tracking_url(value):
    """Only strip known click/campaign identifiers; preserve auth and session data."""
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.query:
        return value, 0
    parts = parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(key, val) for key, val in parts
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS]
    removed = len(parts) - len(kept)
    if not removed:
        return value, 0
    cleaned = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                           urlencode(kept), parsed.fragment))
    return cleaned, removed


def configuration():
    saved = read_json(SETTINGS, {})
    config = {"adblock": True, "block_third_party_cookies": True,
              "strip_tracking_params": True,
              "bandwidth_enabled": False, "bandwidth_mbps": 10,
              "clear_history_on_exit": False,
              "private_session": True, **saved}
    # Always use private session; a previous setting cannot enable disk-based browsing.
    config["private_session"] = True
    config["bandwidth_enabled"] = bool(config.get("bandwidth_enabled", False))
    try:
        config["bandwidth_mbps"] = max(3, min(25, int(config.get("bandwidth_mbps", 10))))
    except (TypeError, ValueError):
        config["bandwidth_mbps"] = 10
    # Altdaten frueherer VPN-Versionen beim Start dauerhaft entfernen.
    obsolete = ("proxy", "custom_host", "custom_port", "vpn_provider",
                "vpn_country", "vpn_enabled", "vpn_location",
                "mullvad_account", "nordvpn_account")
    if any(key in config for key in obsolete):
        for key in obsolete:
            config.pop(key, None)
        write_json(SETTINGS, config)
    # Browser history is never persisted. Remove legacy on-disk web storage/cache
    # from older versions, while keeping bookmarks and user preferences.
    for old in ("web-storage", "cache"):
        old_path = DATA / old
        if old_path.exists() and old_path.is_dir():
            try:
                shutil.rmtree(old_path)
            except OSError:
                pass
    return config


def preconfigure_chromium(proxy_port):
    """Send ordinary Chromium HTTP(S) traffic through Vaultie's loopback limiter."""
    args = ["--disable-background-networking", "--disable-quic",
            "--no-pings", "--disable-features=MediaRouter",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            f"--proxy-server=http://127.0.0.1:{proxy_port}"]
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(args)


class AdBlocker(QWebEngineUrlRequestInterceptor):
    # Minimal blocker; importable host lists below improve coverage.
    PATTERNS = ("doubleclick.net", "googlesyndication.com", "googleadservices.com",
                "adnxs.com", "taboola.com", "outbrain.com", "scorecardresearch.com",
                "adsrvr.org", "criteo.com", "amazon-adsystem.com", "yieldmo.com",
                "casalemedia.com", "rubiconproject.com", "pubmatic.com", "openx.net",
                "smartadserver.com", "bidswitch.net", "quantserve.com", "moatads.com",
                "demdex.net", "advertising.com", "media.net", "lijit.com",
                "serving-sys.com", "3lift.com", "teads.tv")

    def __init__(self, enabled=True, parent=None):
        super().__init__(parent)
        self.enabled = enabled
        self.hosts = set()
        self._counters_lock = Lock()
        self.blocked_requests = 0
        self.reload()

    def reload(self):
        self.hosts.clear()
        if not FILTERS.exists():
            return
        for line in FILTERS.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip().lower()
            if not line or line.startswith(("#", "!", "[", "@@")):
                continue
            # HOSTS entries, bare domains, and simple Adblock ||domain^ rules.
            if line.startswith("||"):
                line = line[2:].split("^")[0].split("/")[0]
            elif " " in line:
                parts = line.split()
                if len(parts) != 2 or parts[0] not in ("0.0.0.0", "127.0.0.1"):
                    continue
                line = parts[1]
            if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z0-9-]+", line):
                self.hosts.add(line)

    def interceptRequest(self, info):
        if not self.enabled:
            return
        url = info.requestUrl()
        host = url.host().lower()
        if not host:
            return
        # Only block third-party requests, never directly opened websites.
        first = info.firstPartyUrl().host().lower()
        if not first or host == first or host.endswith("." + first):
            return
        domains = (*self.PATTERNS, *self.hosts)
        if any(host == item or host.endswith("." + item) for item in domains):
            info.block(True)
            with self._counters_lock:
                self.blocked_requests += 1


class BrowserPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() == "vaultie":
            # Only our internal start page may invoke vaultie:// UI actions.
            # Ordinary websites must not modify local bookmarks or trigger dialogs.
            if not is_main_frame or self.url().toString() != "about:blank":
                return False
            action = url.host() or url.path().lstrip("/")
            if action == "start":
                self.window.open_home()
            elif action == "bookmarks":
                self.window.choose_home_bookmarks()
            elif action == "unpin":
                try:
                    index = int(url.path().strip("/"))
                    QTimer.singleShot(0, lambda n=index: self.window.remove_home_shortcut(n))
                except (ValueError, IndexError):
                    pass
            elif action == "downloads":
                self.window.show_data_folder()
                QMessageBox.information(self.window, "Downloads", "Heruntergeladene Dateien werden im von dir gewählten Ordner gespeichert.")
            elif action == "privacy":
                self.window.show_security_notes()
            elif action == "history":
                self.window.show_history_policy()
            elif action == "settings":
                self.window.show_settings_menu()
            return False
        if (is_main_frame and self.window.config.get("strip_tracking_params", True)
                and url.scheme() in ("http", "https")):
            cleaned, count = clean_tracking_url(url.toString())
            if count:
                self.window.cleaned_tracking_parameters += count
                # Delay until the current navigation callback has returned.
                QTimer.singleShot(0, lambda page=self, dest=cleaned:
                                  page.setUrl(QUrl(dest)))
                return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def __init__(self, profile, window, parent=None):
        super().__init__(profile, parent)
        self.window = window

    def createWindow(self, _type):
        view = self.window.add_tab(switch=True)
        return view.page()



class BrowserTabs(QWidget):
    """Tab strip above navigation; exposes the subset of QTabWidget API in use."""
    tabCloseRequested = None
    currentChanged = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.tab_row = QWidget(self)
        self.tab_row.setObjectName("tabRow")
        row_layout = QHBoxLayout(self.tab_row)
        row_layout.setContentsMargins(12, 6, 12, 0)
        row_layout.setSpacing(4)
        self.bar = QTabBar(self.tab_row)
        self.bar.setObjectName("vaultieTabs")
        self.bar.setTabsClosable(False)
        self.bar.setMovable(True)
        self.bar.setExpanding(False)
        self.bar.setUsesScrollButtons(True)
        self.bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.bar.setDrawBase(False)
        # The tab bar takes only the width actually needed by its tabs.
        self.bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row_layout.addWidget(self.bar, 0)
        self.new_button = QToolButton(self.tab_row)
        self.new_button.setText("+")
        self.new_button.setToolTip("Neuer Tab (Strg+T)")
        self.new_button.setObjectName("newTabButton")
        row_layout.addWidget(self.new_button, 0)
        row_layout.addStretch(1)  # Empty space ALWAYS follows the + button.
        self.layout.addWidget(self.tab_row)
        self.stack = QStackedWidget(self)
        self.tabCloseRequested = self.bar.tabCloseRequested
        self.currentChanged = self.bar.currentChanged
        self.bar.currentChanged.connect(self.stack.setCurrentIndex)
        self.bar.tabMoved.connect(self._move_stack)
        self.bar.tabCloseRequested.connect(lambda _i: self._refresh_tab_width())
        self.bar.currentChanged.connect(lambda _i: self._refresh_tab_width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_tab_width()

    def _refresh_tab_width(self):
        # Keep the plus button visible even with many tabs, using Qt's scroll buttons.
        room = max(125, self.tab_row.width() - 100)
        wanted = max(125, self.bar.sizeHint().width())
        self.bar.setMaximumWidth(min(room, wanted))


    def _make_close_button(self):
        button = QToolButton(self.bar)
        button.setText("×")
        button.setToolTip("Tab schließen")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        button.setFixedSize(18, 18)
        button.setStyleSheet("QToolButton{border:0;color:#d5efee;background:transparent;font-size:13px;font-weight:600;padding:0;margin:0;}QToolButton:hover{color:#ffffff;background:#1f6a73;border-radius:9px;}")
        button.clicked.connect(self._close_from_button)
        return button

    def _close_from_button(self):
        button = self.sender()
        for index in range(self.bar.count()):
            if self.bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.bar.tabCloseRequested.emit(index)
                break

    def _move_stack(self, old, new):
        widget = self.stack.widget(old)
        if widget is None: return
        self.stack.removeWidget(widget)
        self.stack.insertWidget(new, widget)
        self.stack.setCurrentIndex(self.bar.currentIndex())

    def set_toolbar(self, toolbar):
        self.layout.addWidget(toolbar)
        self.layout.addWidget(self.stack, 1)

    def addTab(self, widget, title):
        idx = self.bar.addTab(title)
        self.stack.insertWidget(idx, widget)
        self.bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, self._make_close_button())
        self._refresh_tab_width()
        return idx

    def indexOf(self, widget): return self.stack.indexOf(widget)
    def currentWidget(self): return self.stack.currentWidget()
    def currentIndex(self): return self.bar.currentIndex()
    def setCurrentIndex(self, idx): self.bar.setCurrentIndex(idx)
    def count(self): return self.bar.count()
    def widget(self, idx): return self.stack.widget(idx)
    def setTabText(self, idx, text): self.bar.setTabText(idx, text)
    def setTabToolTip(self, idx, text): self.bar.setTabToolTip(idx, text)

    def setTabIcon(self, idx, icon): self.bar.setTabIcon(idx, icon)

    def removeTab(self, idx):
        widget = self.stack.widget(idx)
        self.bar.removeTab(idx)
        if widget is not None:
            self.stack.removeWidget(widget)
        self._refresh_tab_width()

class Browser(QMainWindow):
    def __init__(self, config, bandwidth_proxy):
        super().__init__()
        self.config = config
        self.bandwidth_proxy = bandwidth_proxy
        self.storage = StorageBudget(DATA)
        self.storage_warning_shown = False
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        icon = ASSETS / "vaultie.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.bookmarks = read_json(BOOKMARKS, [])
        self.pinned = read_json(PINNED, [])
        self.hidden_shortcuts = read_json(HIDDEN_SHORTCUTS, [])
        self.history = read_json(HISTORY, [])
        if not isinstance(self.bookmarks, list):
            self.bookmarks = []
        if not isinstance(self.pinned, list):
            self.pinned = []
        if not isinstance(self.hidden_shortcuts, list):
            self.hidden_shortcuts = []
        if not isinstance(self.history, list):
            self.history = []
        self.session_downloads = []
        self.cleaned_tracking_parameters = 0
        # Off-the-record Qt WebEngine profile by default: website cookies,
        # cache and storage remain in memory and are discarded on exit.
        # User-owned settings/bookmarks remain on disk, never uploaded by us.
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        # Only in-memory visited links; never write browser history to disk.
        # Permissions must be granted again after restarting the browser.
        self.profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.StoreInMemory)
        self.cookie_filter = lambda request: (
            not self.config.get("block_third_party_cookies", True)
            or not request.thirdParty)
        self.profile.cookieStore().setCookieFilter(self.cookie_filter)
        privacy = self.profile.settings()
        attributes = QWebEngineSettings.WebAttribute
        for name in ("LocalContentCanAccessRemoteUrls", "LocalContentCanAccessFileUrls",
                     "JavascriptCanAccessClipboard", "JavascriptCanPaste",
                     "HyperlinkAuditingEnabled", "DnsPrefetchEnabled",
                     "JavascriptCanOpenWindows", "ScreenCaptureEnabled"):
            privacy.setAttribute(getattr(attributes, name), False)
        # Limit WebRTC exposure of private LAN interface addresses.
        # This does not hide the public IP address or provide a VPN.
        privacy.setAttribute(attributes.WebRTCPublicInterfacesOnly, True)
        # Do not start an internal spell-check network service.
        self.profile.setSpellCheckEnabled(False)
        self.blocker = AdBlocker(config["adblock"], self)
        self.profile.setUrlRequestInterceptor(self.blocker)
        self.profile.downloadRequested.connect(self.download_requested)
        self.storage_timer = QTimer(self)
        self.storage_timer.setInterval(60_000)
        self.storage_timer.timeout.connect(self.check_storage_budget)
        self.storage_timer.start()
        QTimer.singleShot(1500, self.check_storage_budget)
        self.tabs = BrowserTabs(self)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.refresh_ui)
        self.tabs.new_button.clicked.connect(lambda: self.add_tab(HOME))
        self.setCentralWidget(self.tabs)
        self.create_controls()
        self.apply_design()
        self.add_tab(HOME)
        self.statusBar().showMessage("Vaultie · Verlauf und Lesezeichen lokal gespeichert · Keine Cloud-Synchronisierung")

    def connection_status(self):
        return "Verlauf ausschließlich lokal gespeichert"

    def apply_design(self):
        self.setStyleSheet("""
            QMainWindow {background:#041d24;}
            QWidget#tabRow {background:#062830; border-bottom:1px solid #104852;}
            QTabBar#vaultieTabs {background:transparent; border:0;}
            QTabBar#vaultieTabs::tab {background:#0c3843; color:#b5e8e7;
                border:1px solid #23606a; border-bottom:0;
                padding:8px 12px 8px 14px; min-width:96px; max-width:210px;
                margin:3px 4px 0px 0px; border-top-left-radius:11px; border-top-right-radius:11px;}
            QTabBar#vaultieTabs::tab:selected {background:#0c4852; color:#ffffff;
                border-color:#18c6c6; font-weight:600;}
            QTabBar#vaultieTabs::tab:hover:!selected {background:#14505d;}
            QTabBar#vaultieTabs::tab:selected {margin-top:1px;}
            QToolBar {background:#082c36; border:0; border-bottom:1px solid #126a72;
                spacing:5px; padding:5px 10px;}
            QToolButton {border:0; color:#b9faf4; font-size:16px; padding:6px;
                border-radius:7px; background:transparent;}
            QToolButton:hover {background:#14515a;}
            QToolButton#newTabButton {font-size:22px; min-width:28px;}
            QToolButton#vpnRecommend {font-size:12px; font-weight:600;
                background:#0a3f49; color:#affbf1; border:1px solid #168d8c; padding:7px 9px;}
            QToolButton#vpnRecommend:hover {background:#16616b;}
            QToolButton#adblockState {font-size:12px; color:#8cfbe0; font-weight:600;}
            QLineEdit#address {background:#0c3944; color:#f5ffff;
                border:1px solid #258d99; border-radius:13px;
                padding:8px 13px; font-size:13px; min-height:18px;}
            QLineEdit#address:focus {border:2px solid #21e2d2;}
            QMenu {background:#082a34; border:1px solid #1b858a; color:#ddfbf8; padding:7px;}
            QMenu::item {padding:8px 25px;}
            QMenu::item:selected {background:#145962;}
            QStatusBar {background:#0b2b2e; color:#d1e5e2; border:0; font-size:11px;}
        """)

    def toolbar_button(self, bar, label, callback, tip, name=None):
        button = QToolButton(self)
        button.setText(label)
        button.setToolTip(tip)
        if name:
            button.setObjectName(name)
        button.clicked.connect(callback)
        bar.addWidget(button)
        return button

    def create_controls(self):
        bar = QToolBar("Navigation", self)
        bar.setMovable(False)
        self.tabs.set_toolbar(bar)
        self.toolbar_button(bar, "←", lambda: self.current() and self.current().back(), "Zurück (Alt+Links)")
        self.toolbar_button(bar, "→", lambda: self.current() and self.current().forward(), "Vorwärts (Alt+Rechts)")
        self.toolbar_button(bar, "↻", lambda: self.current() and self.current().reload(), "Neu laden (Strg+R)")
        self.toolbar_button(bar, "⌂", self.open_home, "Startseite")
        self.address = QLineEdit()
        self.address.setObjectName("address")
        self.address.setMinimumWidth(260)
        self.address.setPlaceholderText("Webadresse eingeben oder suchen")
        self.address.returnPressed.connect(self.navigate)
        bar.addWidget(self.address)
        self.toolbar_button(bar, "☆", self.bookmark_current, "Lesezeichen speichern (Strg+D)")
        folder = self.toolbar_button(bar, "★", self.show_bookmarks, "Lesezeichen-Ordner öffnen und verwalten")
        folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        folder.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adblock_button = self.toolbar_button(bar, "◆  Schutz aktiv", self.toggle_blocker,
            "Werbeblocker ein- oder ausschalten", "adblockState")
        self.refresh_blocker_status()
        self.bandwidth_button = self.toolbar_button(
            bar, "", self.show_bandwidth_dialog,
            "Vaultie-Bandbreite zwischen 3 und 25 Mbit/s begrenzen")
        self.refresh_bandwidth_status()
        vpn_button = QToolButton(self)
        vpn_button.setObjectName("vpnRecommend")
        vpn_button.setText("VPN  ▾")
        vpn_button.setToolTip("Mullvad und NordVPN: ausschließlich Empfehlungen, kein eingebautes VPN")
        vpn_menu = QMenu(self)
        vpn_menu.addAction("Mullvad VPN – Webseite öffnen", lambda: self.open_vpn_recommendation("Mullvad VPN"))
        vpn_menu.addAction("NordVPN – Webseite öffnen", lambda: self.open_vpn_recommendation("NordVPN"))
        vpn_menu.addSeparator()
        vpn_menu.addAction("Wichtiger Hinweis", self.show_vpn_notice)
        vpn_button.setMenu(vpn_menu)
        vpn_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bar.addWidget(vpn_button)
        self.menu_button = QToolButton(self)
        self.menu_button.setText("☰")
        self.menu_button.setToolTip("Menü und Einstellungen")
        menu = QMenu(self)
        menu.addAction("Lesezeichen verwalten", self.show_bookmarks)
        menu.addAction("Downloads anzeigen", self.show_downloads)
        menu.addAction("Lokalen Speicher prüfen / bereinigen", self.show_storage_status)
        menu.addAction("Bandbreitenlimit (3-25 Mbit/s)", self.show_bandwidth_dialog)
        menu.addAction("Werbeblocker umschalten", self.toggle_blocker)
        menu.addAction("Link-Tracking-Schutz umschalten", self.toggle_tracking_parameters)
        menu.addAction("Trackingschutz-Bericht", self.show_tracking_report)
        menu.addAction("Filterliste importieren", self.import_filters)
        menu.addAction("Drittanbieter-Cookies umschalten", self.toggle_third_party_cookies)
        menu.addAction("Cookies und Cache löschen", self.clear_site_data)
        menu.addAction("Lokalen Verlauf anzeigen", self.show_history_policy)
        menu.addAction("Lokalen Datenordner anzeigen", self.show_data_folder)
        menu.addSeparator()
        menu.addAction("Datenschutzhinweise", self.show_security_notes)
        self.menu_button.setMenu(menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bar.addWidget(self.menu_button)
        self.main_menu = menu
        shortcuts = [
            ("Ctrl+L", lambda: (self.address.setFocus(), self.address.selectAll())),
            ("Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex())),
            ("Ctrl+T", lambda: self.add_tab(HOME)),
            ("Ctrl+D", self.bookmark_current),
            ("Ctrl+R", lambda: self.current() and self.current().reload()),
            ("Alt+Left", lambda: self.current() and self.current().back()),
            ("Alt+Right", lambda: self.current() and self.current().forward()),
        ]
        for key, callback in shortcuts:
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(callback)
            self.addAction(a)

    def refresh_blocker_status(self):
        if hasattr(self, "adblock_button"):
            enabled = self.config.get("adblock", True)
            self.adblock_button.setText("◈  Werbeblocker: An" if enabled else "◇  Werbeblocker: Aus")
            self.adblock_button.setToolTip("Einfacher Werbe-/Trackerfilter: " + ("aktiv" if enabled else "inaktiv"))

    def refresh_bandwidth_status(self):
        enabled = self.config.get("bandwidth_enabled", False)
        mbps = self.config.get("bandwidth_mbps", 10)
        label = f"BW: {mbps} Mbit/s" if enabled else "BW: AUS"
        self.bandwidth_button.setText(label)
        self.bandwidth_button.setToolTip(
            "Lokales Bandbreitenlimit für Vaulties HTTP(S)-Verbindungen. "
            "Download und Upload teilen sich den eingestellten Grenzwert.")

    def show_bandwidth_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Vaultie - Bandbreitenlimit")
        dialog.resize(420, 220)
        layout = QVBoxLayout(dialog)
        enabled = QCheckBox("Bandbreite begrenzen")
        enabled.setChecked(self.config.get("bandwidth_enabled", False))
        layout.addWidget(enabled)
        description = QLabel("Gesamtlimit für Browser-Downloads und -Uploads. "
                             "Gilt gleichzeitig für alle Tabs.")
        description.setWordWrap(True)
        layout.addWidget(description)
        value_label = QLabel()
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(3, 25)
        slider.setSingleStep(1)
        slider.setTickInterval(1)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setValue(self.config.get("bandwidth_mbps", 10))
        layout.addWidget(slider)
        note = QLabel(
            "Alle Werte in Mbit/s (Megabit pro Sekunde), nicht MB/s. "
            "Bei AUS wird nicht gedrosselt. Technisch wird nur Vaulties "
            "Webverkehr über einen lokalen Proxy geleitet. Andere Windows-"
            "Programme werden nicht begrenzt. Vorhandene Systemproxy-"
            "Einstellungen können dadurch für Vaultie übersteuert werden.")
        note.setWordWrap(True)
        layout.addWidget(note)

        def apply():
            new_enabled = enabled.isChecked()
            new_mbps = slider.value()
            value_label.setText(f"{new_mbps} Mbit/s")
            slider.setEnabled(new_enabled)
            self.bandwidth_proxy.configure(new_enabled, new_mbps)
            self.config["bandwidth_enabled"] = new_enabled
            self.config["bandwidth_mbps"] = new_mbps
            self.refresh_bandwidth_status()

        def persist():
            write_json(SETTINGS, self.config)

        enabled.toggled.connect(lambda _checked: (apply(), persist()))
        slider.valueChanged.connect(lambda _value: apply())
        slider.sliderReleased.connect(persist)
        layout.addWidget(QLabel("3 Mbit/s                               25 Mbit/s"))
        done = QPushButton("Fertig")
        done.clicked.connect(lambda: (persist(), dialog.accept()))
        layout.addWidget(done)
        apply()
        dialog.exec()

    def show_settings_menu(self):
        self.main_menu.popup(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))

    def open_home(self):
        if self.current():
            self.current().setHtml(self.start_page_html(), QUrl("about:blank"))

    def open_vpn_recommendation(self, provider):
        url = VPN_LINKS.get(provider)
        if url:
            self.add_tab(url)

    def show_vpn_notice(self):
        QMessageBox.information(self, "VPN-Empfehlungen",
            "Mullvad und NordVPN werden nur empfohlen. Der Browser richtet "
            "keine VPN-Verbindung ein, speichert keine VPN-Anmeldedaten "
            "und zeigt keinen VPN-Verbindungsstatus. Die offiziellen "
            "Windows-Anwendungen der Anbieter sind separat zu installieren. "
            "Ein Windows-VPN kann auch andere Programme beeinflussen.")

    def visible_home_shortcuts(self):
        defaults = [(name, url, icon, style) for name, url, icon, style
                    in DEFAULT_SHORTCUTS if url not in self.hidden_shortcuts]
        default_urls = {item[1] for item in DEFAULT_SHORTCUTS}
        custom = []
        for url in self.pinned:
            if url in default_urls:
                continue
            bookmark = next((b for b in self.bookmarks if b.get("url") == url), None)
            if bookmark:
                custom.append((bookmark.get("title", "Lesezeichen"), url, "☆", ""))
        return defaults + custom

    def start_page_html(self):
        content = (ASSETS / "startseite.html").read_text(encoding="utf-8")
        cards = []
        for index, (name, url, icon, style) in enumerate(self.visible_home_shortcuts()):
            safe_url = html.escape(url, quote=True)
            safe_title = html.escape(name, quote=True)
            safe_icon = html.escape(icon)
            safe_class = html.escape(style, quote=True)
            cards.append(
                '<div class="pinned-tile"><a class="tile" href="' + safe_url
                + '"><span class="appicon ' + safe_class + '">' + safe_icon
                + '</span><strong>' + safe_title
                + '</strong></a><a class="pin-remove" title="Von Startseite entfernen" '
                + 'href="vaultie://unpin/' + str(index) + '">×</a></div>')
        cards.append('<a class="tile" href="vaultie://bookmarks">'
                     '<span class="appicon add">＋</span><strong>Lesezeichen</strong></a>')
        content, separator, after_grid = content.partition('<div class="shortcutgrid">')
        if not separator:
            return content
        _, separator, tail = after_grid.partition('</div>\n<div class="panel">')
        if not separator:
            return content + '<div class="shortcutgrid">' + after_grid
        content += '<div class="shortcutgrid">' + "".join(cards) + '</div>\n<div class="panel">' + tail
        content = content.replace(
            '<div class="panel">',
            '<style>.pinned-tile{position:relative;min-width:0}'
            '.pinned-tile .tile{height:100%;padding:10px;overflow-wrap:anywhere}'
            '.pin-remove{position:absolute;top:5px;right:8px;z-index:2;'
            'font-size:22px;color:#d5ffff;text-decoration:none;'
            'padding:1px 7px;border-radius:8px;background:#174752}'
            '.pin-remove:hover{background:#ad3546;color:white}</style>'
            '<div class="panel">', 1)
        content = content.replace('Der Verlauf wird niemals gespeichert.',
                                  'Verlauf wird nur lokal gespeichert.')
        return content

    def current(self):
        return self.tabs.currentWidget()

    def add_tab(self, url=None, switch=True):
        view = QWebEngineView(self)
        page = BrowserPage(self.profile, self, view)
        view.setPage(page)
        view.titleChanged.connect(lambda title, v=view: self.set_tab_title(v, title))
        view.loadFinished.connect(lambda ok, v=view: self.record_history(v) if ok else None)
        view.urlChanged.connect(lambda _url, v=view: self.update_address(v))
        view.loadProgress.connect(lambda n: self.statusBar().showMessage(f"Lade {n} %" if n < 100 else self.connection_status()))
        idx = self.tabs.addTab(view, "Neuer Tab")
        self.tabs.setTabIcon(idx, QIcon(str(ASSETS / "vaultie.ico")))
        if switch:
            self.tabs.setCurrentIndex(idx)
        if url == HOME:
            view.setHtml(self.start_page_html(), QUrl("about:blank"))
        elif url:
            view.setUrl(QUrl(url))
        return view

    def set_tab_title(self, view, title):
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabText(index, title[:22] or "Neuer Tab")
            self.tabs.setTabToolTip(index, title)
        if self.current() is view:
            clean = (title or "").strip()
            if clean and APP_NAME.lower() in clean.lower():
                self.setWindowTitle(clean)
            else:
                self.setWindowTitle(f"{clean} – {APP_NAME}" if clean else APP_NAME)

    def update_address(self, view):
        if view is self.current():
            self.address.setText("" if view.url().toString() == "about:blank" else view.url().toString())

    def refresh_ui(self, _index):
        if self.current():
            self.update_address(self.current())
            title = self.current().title()
            clean = (title or "").strip()
            if clean and APP_NAME.lower() in clean.lower():
                self.setWindowTitle(clean)
            else:
                self.setWindowTitle(f"{clean} – {APP_NAME}" if clean else APP_NAME)

    def navigate(self):
        text = self.address.text().strip()
        if not text:
            return
        if re.match(r"^https?://", text, flags=re.I):
            dest = text
        elif "." in text and " " not in text and not text.startswith(("javascript:", "file:")):
            dest = "https://" + text
        else:
            dest = "https://www.startpage.com/sp/search?query=" + quote_plus(text)
        self.current().setUrl(QUrl(dest))

    def close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget:
            self.tabs.removeTab(index)
            widget.deleteLater()
        if self.tabs.count() == 0:
            self.add_tab(HOME)

    def bookmark_current(self):
        view = self.current()
        if not view:
            return
        url = view.url().toString()
        if urlsplit(url).scheme not in ("https", "http"):
            self.statusBar().showMessage("Nur Webseiten lassen sich als Lesezeichen speichern", 3000)
            return
        value = {"title": view.title() or url, "url": url}
        if not any(item.get("url") == url for item in self.bookmarks):
            self.bookmarks.append(value)
            write_json(BOOKMARKS, self.bookmarks)
            self.statusBar().showMessage("Lesezeichen gespeichert", 3000)
        else:
            self.statusBar().showMessage("Lesezeichen bereits vorhanden", 3000)

    def refresh_home_if_visible(self):
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if view and view.url().toString() == "about:blank" and "Vaultie" in view.title():
                view.setHtml(self.start_page_html(), QUrl("about:blank"))

    def choose_home_bookmarks(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Lesezeichen auf der Startseite auswählen")
        dialog.resize(600, 450)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Schnellwahl auswählen: auch die fünf Standard-Kacheln sind entfernbar und wiederherstellbar."))
        search = QLineEdit(dialog)
        search.setPlaceholderText("Lesezeichen suchen")
        layout.addWidget(search)
        items = QListWidget(dialog)
        items.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(items)
        from PySide6.QtWidgets import QListWidgetItem
        default_urls = {url for _name, url, _icon, _style in DEFAULT_SHORTCUTS}
        for name, url, _icon, _style in DEFAULT_SHORTCUTS:
            item = QListWidgetItem("Standard: " + name + " — " + url)
            item.setData(Qt.ItemDataRole.UserRole, url)
            items.addItem(item)
            item.setSelected(url not in self.hidden_shortcuts)
        for bookmark in self.bookmarks:
            url = bookmark.get("url", "")
            if urlsplit(url).scheme not in ("https", "http") or url in default_urls:
                continue
            item = QListWidgetItem(bookmark.get("title", url) + " — " + url)
            item.setData(Qt.ItemDataRole.UserRole, url)
            items.addItem(item)
            if url in self.pinned:
                item.setSelected(True)
        search.textChanged.connect(
            lambda q: [items.item(i).setHidden(q.casefold() not in items.item(i).text().casefold())
                       for i in range(items.count())])
        row = QHBoxLayout()
        save = QPushButton("Auswahl auf Startseite anzeigen")
        save.clicked.connect(lambda: (
            self.save_pinned([items.item(i).data(Qt.ItemDataRole.UserRole)
                              for i in range(items.count()) if items.item(i).isSelected()]),
            dialog.accept()))
        close = QPushButton("Abbrechen")
        close.clicked.connect(dialog.reject)
        row.addWidget(save)
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec()

    def save_pinned(self, urls):
        selected = set(urls)
        default_urls = {url for _name, url, _icon, _style in DEFAULT_SHORTCUTS}
        allowed = {item.get("url") for item in self.bookmarks}
        self.hidden_shortcuts = [url for url in default_urls if url not in selected]
        self.pinned = list(dict.fromkeys(
            url for url in urls if url in allowed and url not in default_urls))
        write_json(HIDDEN_SHORTCUTS, self.hidden_shortcuts)
        write_json(PINNED, self.pinned)
        self.refresh_home_if_visible()

    def remove_home_shortcut(self, index):
        shortcuts = self.visible_home_shortcuts()
        if not 0 <= index < len(shortcuts):
            return
        url = shortcuts[index][1]
        default_urls = {entry[1] for entry in DEFAULT_SHORTCUTS}
        if url in default_urls:
            if url not in self.hidden_shortcuts:
                self.hidden_shortcuts.append(url)
                write_json(HIDDEN_SHORTCUTS, self.hidden_shortcuts)
        else:
            self.pinned = [entry for entry in self.pinned if entry != url]
            write_json(PINNED, self.pinned)
        self.refresh_home_if_visible()

    def show_bookmarks(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Lokale Lesezeichen verwalten")
        dialog.resize(760, 490)
        layout = QVBoxLayout(dialog)
        search = QLineEdit(dialog)
        search.setPlaceholderText("Lesezeichen durchsuchen")
        layout.addWidget(search)
        items = QListWidget(dialog)
        layout.addWidget(items)
        from PySide6.QtWidgets import QListWidgetItem

        def refresh():
            items.clear()
            for entry in self.bookmarks:
                url = entry.get("url", "")
                item = QListWidgetItem(
                    ("★ " if url in self.pinned else "") +
                    entry.get("title", "Webseite") + " — " + url)
                item.setData(Qt.ItemDataRole.UserRole, url)
                items.addItem(item)
            filter_items(search.text())

        def filter_items(query):
            for i in range(items.count()):
                item = items.item(i)
                item.setHidden(query.casefold() not in item.text().casefold())

        def selected():
            item = items.currentItem()
            if not item:
                return None
            return next((b for b in self.bookmarks
                         if b.get("url") == item.data(Qt.ItemDataRole.UserRole)), None)

        def open_selected():
            entry = selected()
            if entry and self.current():
                self.current().setUrl(QUrl(entry["url"]))
                dialog.accept()

        def edit_selected():
            entry = selected()
            if not entry:
                return
            title, ok = QInputDialog.getText(dialog, "Lesezeichen bearbeiten",
                                             "Name:", text=entry.get("title", ""))
            if not ok:
                return
            url, ok = QInputDialog.getText(dialog, "Lesezeichen bearbeiten",
                                           "Webadresse:", text=entry.get("url", ""))
            if not ok or urlsplit(url.strip()).scheme not in ("https", "http"):
                return
            old = entry["url"]
            if url != old and any(b.get("url") == url for b in self.bookmarks):
                QMessageBox.warning(dialog, "Lesezeichen", "Diese Adresse ist bereits gespeichert.")
                return
            entry.update(title=title.strip() or url, url=url.strip())
            self.pinned = [url if u == old else u for u in self.pinned]
            write_json(BOOKMARKS, self.bookmarks)
            write_json(PINNED, self.pinned)
            refresh()
            self.refresh_home_if_visible()

        def remove_selected():
            entry = selected()
            if not entry:
                return
            if QMessageBox.question(dialog, "Lesezeichen löschen",
                                    "Lesezeichen vollständig löschen?") != QMessageBox.StandardButton.Yes:
                return
            self.bookmarks.remove(entry)
            self.pinned = [u for u in self.pinned if u != entry["url"]]
            write_json(BOOKMARKS, self.bookmarks)
            write_json(PINNED, self.pinned)
            refresh()
            self.refresh_home_if_visible()

        def toggle_pin():
            entry = selected()
            if not entry:
                return
            url = entry["url"]
            if url in self.pinned:
                self.pinned.remove(url)
            else:
                self.pinned.append(url)
            write_json(PINNED, self.pinned)
            refresh()
            self.refresh_home_if_visible()

        row = QHBoxLayout()
        for label, callback in (("Öffnen", open_selected),
                                ("Bearbeiten", edit_selected),
                                ("Anheften / Entfernen", toggle_pin),
                                ("Löschen", remove_selected),
                                ("Schließen", dialog.reject)):
            button = QPushButton(label, dialog)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        search.textChanged.connect(filter_items)
        items.itemDoubleClicked.connect(lambda _item: open_selected())
        refresh()
        dialog.exec()

    def show_downloads(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Downloads dieser Sitzung")
        dialog.resize(650, 340)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Dateien bleiben in den von dir gewählten lokalen Ordnern."))
        items = QListWidget(dialog)
        items.addItems(self.session_downloads)
        layout.addWidget(items)
        row = QHBoxLayout()

        def open_selected():
            item = items.currentItem()
            if item and Path(item.text()).exists():
                if sys.platform == "win32":
                    os.startfile(item.text())
            elif item:
                QMessageBox.warning(dialog, "Download", "Die ausgewählte Datei wurde nicht gefunden.")

        def show_folder():
            item = items.currentItem()
            if item and sys.platform == "win32":
                parent = Path(item.text()).parent
                if parent.is_dir():
                    os.startfile(str(parent))

        for label, handler in (("Datei öffnen", open_selected),
                               ("Ordner öffnen", show_folder),
                               ("Schließen", dialog.reject)):
            button = QPushButton(label, dialog)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        dialog.exec()

    def toggle_tracking_parameters(self):
        enabled = not self.config.get("strip_tracking_params", True)
        self.config["strip_tracking_params"] = enabled
        write_json(SETTINGS, self.config)
        QMessageBox.information(
            self, "Lokaler Trackingschutz",
            "Bekannte Trackingparameter werden bei neuen Hauptseitenaufrufen "
            + ("entfernt." if enabled else "nicht mehr entfernt.")
            + "\\nAnmeldeparameter und Formulardaten werden nicht pauschal verändert.")

    def show_tracking_report(self):
        with self.blocker._counters_lock:
            blocked = self.blocker.blocked_requests
        QMessageBox.information(
            self, "Lokaler Trackingschutz",
            f"Seit Programmstart blockierte bekannte Werbe-/Tracker-Anfragen: {blocked}\\n"
            f"Seit Programmstart entfernte Trackingparameter: {self.cleaned_tracking_parameters}\\n"
            f"Lokale Domainregeln: {len(self.blocker.PATTERNS) + len(self.blocker.hosts)} "
            "(einschließlich möglicher Überschneidungen).\\n"
            "Es werden weder Webseitenprotokolle noch Berichte online gespeichert. "
            "Die Zähler werden beim Beenden verworfen.")

    def toggle_blocker(self):
        self.config["adblock"] = not self.config["adblock"]
        self.blocker.enabled = self.config["adblock"]
        self.refresh_blocker_status()
        write_json(SETTINGS, self.config)
        state = "aktiv" if self.blocker.enabled else "inaktiv"
        QMessageBox.information(self, "Werbeblocker", f"Werbeblocker {state}. Neue Seitenanfragen verwenden die Einstellung.")

    def toggle_third_party_cookies(self):
        enabled = not self.config.get("block_third_party_cookies", True)
        self.config["block_third_party_cookies"] = enabled
        write_json(SETTINGS, self.config)
        state = "blockiert" if enabled else "erlaubt"
        QMessageBox.information(self, "Datenschutz",
            f"Drittanbieter-Cookies sind jetzt {state}.\n"
            "Einige Login- oder Videodienste benoetigen Drittanbieter-Cookies.\n"
            "Die Aenderung gilt fuer neue Zugriffe.")

    def set_history_auto_clear(self, enabled):
        self.config["clear_history_on_exit"] = enabled
        write_json(SETTINGS, self.config)

    def closeEvent(self, event):
        if self.config.get("clear_history_on_exit", False):
            self.history.clear()
            write_json(HISTORY, self.history)
        super().closeEvent(event)

    def record_history(self, view):
        url = view.url().toString()
        if urlsplit(url).scheme not in ("http", "https"):
            return
        title = view.title() or url
        if self.history and isinstance(self.history[-1], dict) and self.history[-1].get("url") == url:
            self.history[-1]["title"] = title
            self.history[-1]["visited"] = datetime.now().isoformat(timespec="seconds")
        else:
            self.history.append({
                "url": url, "title": title,
                "visited": datetime.now().isoformat(timespec="seconds")})
        # Bounded local history, independent of WebKit's in-memory session.
        self.history = self.history[-2000:]
        write_json(HISTORY, self.history)

    def show_history_policy(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Lokaler Verlauf")
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Zuletzt besuchte Seiten. Nur auf diesem PC gespeichert."))
        auto_clear = QCheckBox("Lokalen Verlauf beim Beenden automatisch löschen")
        auto_clear.setChecked(self.config.get("clear_history_on_exit", False))
        auto_clear.toggled.connect(lambda checked: self.set_history_auto_clear(checked))
        layout.addWidget(auto_clear)
        search = QLineEdit(dialog)
        search.setPlaceholderText("Im Verlauf suchen")
        layout.addWidget(search)
        items = QListWidget(dialog)
        layout.addWidget(items)
        from PySide6.QtWidgets import QListWidgetItem

        def refresh():
            items.clear()
            for entry in reversed(self.history):
                item = QListWidgetItem(
                    entry.get("visited", "") + "  " +
                    entry.get("title", "") + " — " + entry.get("url", ""))
                item.setData(Qt.ItemDataRole.UserRole, entry.get("url", ""))
                items.addItem(item)
            filter_items(search.text())

        def filter_items(value):
            for i in range(items.count()):
                item = items.item(i)
                item.setHidden(value.casefold() not in item.text().casefold())

        def open_selected():
            item = items.currentItem()
            if item and self.current():
                self.current().setUrl(QUrl(item.data(Qt.ItemDataRole.UserRole)))
                dialog.accept()

        def remove_selected():
            item = items.currentItem()
            if not item:
                return
            # Exact row in reverse chronological history, including duplicates.
            index = len(self.history) - 1 - items.row(item)
            if 0 <= index < len(self.history):
                del self.history[index]
                write_json(HISTORY, self.history)
                refresh()

        def delete_all():
            if QMessageBox.question(
                    dialog, "Verlauf löschen", "Den gesamten lokalen Verlauf löschen?"
                ) != QMessageBox.StandardButton.Yes:
                return
            self.history.clear()
            write_json(HISTORY, self.history)
            refresh()

        row = QHBoxLayout()
        for label, callback in (("Öffnen", open_selected),
                                ("Ausgewählten Eintrag löschen", remove_selected),
                                ("Gesamten Verlauf löschen", delete_all),
                                ("Schließen", dialog.reject)):
            button = QPushButton(label, dialog)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        search.textChanged.connect(filter_items)
        items.itemDoubleClicked.connect(lambda _item: open_selected())
        refresh()
        dialog.exec()

    def clear_site_data(self):
        result = QMessageBox.question(self, "Lokale Website-Daten loeschen",
            "Cookies, Cache und Besuchslinks entfernen?\n"
            "Du wirst dadurch eventuell von Webseiten abgemeldet.\n"
            "Lesezeichen und Einstellungen bleiben erhalten.\n"
            "Schliesse den Browser nach dem Loeschen und starte ihn erneut.")
        if result != QMessageBox.StandardButton.Yes:
            return
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearHttpCache()
        self.profile.clearAllVisitedLinks()
        # LocalStorage/IndexedDB/service workers cannot be fully erased using
        # these APIs. Full deletion requires browser shutdown and profile removal.
        QMessageBox.information(self, "Datenschutz",
            "Cookies, HTTP-Cache und Besuchslinks werden geloescht.\n"
            "WICHTIG: Website-Speicher wie IndexedDB und LocalStorage koennen verbleiben.\n"
            "Fuer vollstaendige Loeschung den Browser beenden und im Datenordner\n"
            "die Ordner 'web-storage' und 'cache' entfernen.")

    def show_data_folder(self):
        # Use the Windows shell to open the local folder; no upload is performed.
        if sys.platform == "win32":
            os.startfile(str(DATA))
        else:
            QMessageBox.information(self, "Lokaler Datenordner", str(DATA))

    def import_filters(self):
        path, _ = QFileDialog.getOpenFileName(self, "HOSTS- oder einfache Filterliste auswählen", "", "Textdateien (*.txt);;Alle Dateien (*)")
        if not path:
            return
        raw = Path(path).read_bytes()
        if len(raw) > 12_000_000:
            QMessageBox.warning(self, "Filterliste", "Die Datei darf maximal 12 MB groß sein.")
            return
        FILTERS.write_bytes(raw)
        self.blocker.reload()
        QMessageBox.information(self, "Filterliste", f"{len(self.blocker.hosts)} Domainregeln geladen. Komplexe EasyList-Regeln werden noch nicht unterstützt.")

    def show_security_notes(self):
        QMessageBox.information(self, "Sicherheit",
            "Diese Version hat keine VPN-Integration. "
            "Der Browser verwendet die normalen Windows-Netzwerkeinstellungen. "
            "Ein separat eingeschaltetes Windows-VPN kann trotzdem den Browser betreffen.\n\n"
            "Lokale Lesezeichen und Einstellungen werden nicht in eine Browser-Cloud hochgeladen. "
            "Der Verlauf wird ausschließlich lokal gespeichert; Cookies und Cache bleiben nur fuer die Sitzung bestehen. "
            "Passwoerter werden nicht in einer eigenen Passwortdatenbank gespeichert.\n\n"
            "Der Werbeblocker nutzt einfache Domainfilter. Dies ist keine unabhaengig "
            "sicherheitsgepruefte Browser-Version. Websites erhalten weiterhin "
            "technisch erforderliche Anfragen und von dir eingegebene Daten.")

    def check_storage_budget(self):
        before, after, freed = self.storage.check()
        if before >= CLEAN_AT and freed > 0:
            self.statusBar().showMessage(
                f"Browser-Cache bereinigt: {freed / (1024 ** 2):.1f} MiB freigegeben.", 5000)
        if after >= HARD_LIMIT and not self.storage_warning_shown:
            self.storage_warning_shown = True
            QMessageBox.warning(
                self, "Vaultie - Browser-Speicher",
                "Der interne Browser-Speicher liegt bei mindestens 5 GB. "
                "Automatisch entfernbare Cache-Dateien wurden bereinigt. "
                "Verbleibende Daten können nicht immer während des Betriebs "
                "entfernt werden. Downloads sind von dieser Grenze vollständig "
                "ausgenommen und bleiben uneingeschränkt möglich.")
        elif after < HARD_LIMIT:
            self.storage_warning_shown = False

    def show_storage_status(self):
        before, after, freed = self.storage.check(force=True)
        QMessageBox.information(
            self, "Vaultie - Browser-Speicher",
            f"Browser-Daten: {after / GIB:.2f} GB von 5,00 GB.\n"
            f"Automatische Bereinigung ab: {CLEAN_AT / GIB:.2f} GB.\n"
            f"Bei dieser Prüfung bereinigt: {freed / (1024 ** 2):.1f} MiB.\n"
            "Prüfung automatisch jede Minute.\n"
            "Downloads werden NICHT mitgerechnet, begrenzt oder gelöscht.\n"
            "Lesezeichen und Einstellungen bleiben erhalten.")

    def download_requested(self, item: QWebEngineDownloadRequest):
        # Downloads are user files and entirely outside the internal browser
        # storage budget. Never cancel them because of the 5 GB threshold.
        suggested = Path(item.downloadFileName() or "download").name
        if not suggested or suggested in (".", ".."):
            suggested = "download"
        output = DOWNLOADS / suggested
        stem, suffix = output.stem, output.suffix
        counter = 1
        while output.exists():
            output = DOWNLOADS / f"{stem}-{counter}{suffix}"
            counter += 1
        item.setDownloadDirectory(str(DOWNLOADS))
        item.setDownloadFileName(output.name)
        item.accept()
        self.session_downloads.append(str(output))

def main():
    config = configuration()
    try:
        local_proxy = LocalBandwidthProxy(
            config.get("bandwidth_enabled", False),
            config.get("bandwidth_mbps", 10))
    except OSError as exc:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "Vaultie - Bandbreitenlimit",
            "Der lokale Netzwerkbegrenzer konnte nicht gestartet werden. "
            "Vaultie startet aus Sicherheitsgründen nicht mit einem "
            f"unbemerkten Netzwerkausnahmefall.\n\n{exc}")
        return 1
    preconfigure_chromium(local_proxy.port)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vaultie.PrivatBrowser.Windows")
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ASSETS / "vaultie.ico")))
    app.setOrganizationName("Vaultie Local")
    app.setApplicationName(APP_NAME)
    window = Browser(config, local_proxy)
    window.show()
    result = app.exec()
    local_proxy.stop()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
