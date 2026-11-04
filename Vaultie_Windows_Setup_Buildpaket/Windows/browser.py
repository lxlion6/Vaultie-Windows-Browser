"""PrivatBrowser: erster Windows-Desktopbrowser auf Qt WebEngine."""
import json
import html
from datetime import datetime
import os
import re
import secrets
import subprocess
import shutil
import sys
from functools import partial
from threading import Lock
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode

from PySide6.QtCore import QStandardPaths, Qt, QUrl, QTimer
from PySide6.QtGui import QAction, QKeySequence, QIcon, QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QListWidget, QTabBar, QStackedWidget, QToolBar, QToolButton, QSlider, QCheckBox,
    QVBoxLayout, QWidget, QSizePolicy, QStyle)
from PySide6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage,
    QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor,
    QWebEngineScript)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from bandwidth_proxy import LocalBandwidthProxy
from storage_manager import StorageBudget, CLEAN_AT, HARD_LIMIT, GIB
from credentials import CredentialVault, secure_origin

APP_NAME = "Vaultie"
APP_VERSION = "3.6"
RELEASE_API = "https://api.github.com/repos/lxlion6/Vaultie-Windows-Browser/releases/tags/windows-latest"
HOME = "vaultie:start"
STREAM_HOSTS = ("primevideo.com", "netflix.com", "disneyplus.com",
                "disneyplus.de", "max.com", "wowtv.de", "paramountplus.com")

def needs_native_media_engine(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http"):
        return False
    host = (parsed.hostname or "").lower()
    return any(host == name or host.endswith("." + name)
               for name in STREAM_HOSTS)

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
CREDENTIALS = DATA / "credentials.dat"
FILTERS = DATA / "filterliste.txt"
def download_directory():
    """Default to the user's ordinary Windows Downloads directory."""
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation)
    folder = Path(location) if location else DATA / "Downloads"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    except OSError:
        fallback = DATA / "Downloads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DOWNLOADS = download_directory()

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
              "private_session": True,
              "remember_website_sessions": False, **saved}
    # Login details live in a small encrypted file, not persistent site storage.
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
    # Never silently erase user website data or previously stored sessions.
    return config


def preconfigure_chromium(proxy_port=None):
    """Use native networking when the optional bandwidth limit is disabled."""
    args = ["--disable-background-networking",
            "--no-pings", "--disable-features=MediaRouter",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
    if proxy_port is not None:
        # Explicit throttling requires the local proxy and disables QUIC only
        # in that mode, since the limiter implements HTTP and HTTPS TCP.
        args.extend(["--disable-quic",
                     f"--proxy-server=http://127.0.0.1:{proxy_port}"])
    # Widevine is not bundled. Accept only an existing, user-selected DLL.
    cdm = read_json(SETTINGS, {}).get("widevine_path", "")
    if (sys.platform == "win32" and isinstance(cdm, str)
            and Path(cdm).name.lower() == "widevinecdm.dll"
            and Path(cdm).is_file()):
        args.append('--widevine-path="' + Path(cdm).as_posix() + '"')
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
                self.window.show_downloads()
            elif action == "privacy":
                self.window.show_security_notes()
            elif action == "history":
                self.window.show_history_policy()
            elif action == "settings":
                self.window.show_settings_menu()
            return False
        if is_main_frame and needs_native_media_engine(url.toString()):
            QTimer.singleShot(0, lambda address=url.toString():
                              self.window.open_native_video(address))
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
        self.download_items = []
        self.downloads_dialog = None
        self.native_video_processes = []
        self.cleaned_tracking_parameters = 0
        # Off-the-record Qt WebEngine: cookies, HTTP cache, website storage
        # and browser-side login sessions are discarded on exit.
        # Only passwords the user explicitly saves are encrypted on disk.
        if self.config.get("remember_website_sessions", False):
            # Explicit opt-in: Chromium needs a disk-backed profile to restore
            # authentication cookies after the app closes.
            self.profile = QWebEngineProfile("VaultieSessions", self)
            session_dir = DATA / "website-sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            self.profile.setPersistentStoragePath(str(session_dir))
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        else:
            self.profile = QWebEngineProfile(self)
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.StoreInMemory)
        self.vault = None
        self.vault_error = None
        try:
            self.vault = CredentialVault(CREDENTIALS)
        except (OSError, ValueError, KeyError, UnicodeDecodeError) as exc:
            self.vault_error = str(exc)
        # Document-start privacy protection without a background process.
        fingerprint_source = ASSETS / "fingerprint.js"
        if fingerprint_source.is_file():
            privacy_script = QWebEngineScript()
            privacy_script.setName("Vaultie Fingerprinting-Schutz")
            privacy_script.setInjectionPoint(
                QWebEngineScript.InjectionPoint.DocumentCreation)
            privacy_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            privacy_script.setRunsOnSubFrames(True)
            privacy_script.setSourceCode(
                fingerprint_source.read_text(encoding="utf-8").replace(
                    "VAULTIE_SESSION_SEED", secrets.token_hex(16)))
            self.profile.scripts().insert(privacy_script)
        # The update request uses the existing asynchronous Qt event loop.
        self.update_network = QNetworkAccessManager(self)
        self.update_checked = False
        QTimer.singleShot(12000, self.check_for_updates)
        # Prime Video signs in across Amazon domains. Third-party auth
        # cookies for trusted Amazon domains must be allowed in its context.
        def allow_cookie(request):
            if not self.config.get("block_third_party_cookies", True):
                return True
            if not request.thirdParty:
                return True
            first = request.firstPartyUrl.host().lower()
            site = request.origin.host().lower()
            def amazon_domain(host):
                return (host == "primevideo.com" or host.endswith(".primevideo.com")
                        or host == "amazon.com" or host.endswith(".amazon.com")
                        or host == "amazon.de" or host.endswith(".amazon.de")
                        or host == "amazon.co.uk" or host.endswith(".amazon.co.uk"))
            return amazon_domain(first) and amazon_domain(site)
        self.cookie_filter = allow_cookie
        self.profile.cookieStore().setCookieFilter(self.cookie_filter)
        privacy = self.profile.settings()
        attributes = QWebEngineSettings.WebAttribute
        privacy.setAttribute(attributes.FullScreenSupportEnabled, True)
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
        self.statusBar().showMessage("Vaultie · Zugangsdaten auf Wunsch lokal verschlüsselt · Keine Cloud-Synchronisierung")

    def check_for_updates_manual(self):
        self.update_checked = False
        self.check_for_updates()

    def check_for_updates(self):
        """One background-free, asynchronous release check per launch."""
        if self.update_checked:
            return
        self.update_checked = True
        request = QNetworkRequest(QUrl(RELEASE_API))
        request.setRawHeader(b"User-Agent", b"Vaultie-Windows-UpdateCheck")
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setTransferTimeout(8000)
        reply = self.update_network.get(request)
        reply.finished.connect(lambda r=reply: self.process_update_response(r))

    def process_update_response(self, reply):
        try:
            if reply.error() != reply.NetworkError.NoError:
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            info = re.search(r"Version:\s*(\d+\.\d+(?:\.\d+)?)",
                             payload.get("body", ""))
            if not info:
                return
            found = tuple(int(n) for n in info.group(1).split("."))
            current = tuple(int(n) for n in APP_VERSION.split("."))
            if found <= current:
                return
            installer = next((a.get("browser_download_url") for a in
                              payload.get("assets", [])
                              if a.get("name") == "Vaultie-Setup.exe"), None)
            if not installer or not installer.startswith(
                    "https://github.com/lxlion6/Vaultie-Windows-Browser/releases/"):
                return
            decision = QMessageBox.question(
                self, "Vaultie-Update verfügbar",
                f"Vaultie {info.group(1)} ist verfügbar (installiert: {APP_VERSION}).\n"
                "Den neuen Installer von GitHub herunterladen?\n\n"
                "Da der Installer noch unsigniert ist, wird er nicht "
                "automatisch ausgeführt.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if decision == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(installer))
        except (ValueError, TypeError, AttributeError):
            return
        finally:
            reply.deleteLater()

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
        self.toolbar_button(bar, "🔑", self.show_login_actions,
            "Zugangsdaten: speichern, ausfüllen oder verwalten")
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
        self.download_button = self.toolbar_button(
            bar, "↓ Downloads", self.show_downloads,
            "Downloads, Fortschritt und Speicherordner anzeigen")
        self.menu_button = QToolButton(self)
        self.menu_button.setText("☰")
        self.menu_button.setToolTip("Menü und Einstellungen")
        menu = QMenu(self)
        menu.addAction("Lesezeichen verwalten", self.show_bookmarks)
        menu.addAction("Login dieser Website speichern", self.save_login_from_page)
        menu.addAction("Gespeichertes Login jetzt ausfüllen", self.fill_current_login)
        menu.addAction("Gespeicherte Logins verwalten", self.show_saved_logins)
        menu.addAction("Auf Updates prüfen", self.check_for_updates_manual)
        menu.addAction("Video-Codecs und DRM prüfen", self.show_video_diagnostics)
        menu.addAction("Lokale Widevine-Datei wählen", self.choose_widevine_binary)
        menu.addAction("Downloads anzeigen", self.show_downloads)
        menu.addAction("Lokalen Speicher prüfen / bereinigen", self.show_storage_status)
        menu.addAction("Bandbreitenlimit (3-25 Mbit/s)", self.show_bandwidth_dialog)
        menu.addAction("Werbeblocker umschalten", self.toggle_blocker)
        menu.addAction("Link-Tracking-Schutz umschalten", self.toggle_tracking_parameters)
        menu.addAction("Trackingschutz-Bericht", self.show_tracking_report)
        menu.addAction("Filterliste importieren", self.import_filters)
        menu.addAction("Drittanbieter-Cookies umschalten", self.toggle_third_party_cookies)
        menu.addAction("Angemeldet bleiben nach Neustart (optional)", self.toggle_session_persistence)
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
            "Bei AUS nutzt Vaultie direkt das Windows-Netzwerk ohne eigenen Proxy. "
            "Bei EIN wird der lokale Proxy für das Limit verwendet. "
            "Änderungen von EIN/AUS werden nach einem Neustart wirksam.")
        note.setWordWrap(True)
        layout.addWidget(note)

        def apply():
            new_enabled = enabled.isChecked()
            new_mbps = slider.value()
            value_label.setText(f"{new_mbps} Mbit/s")
            slider.setEnabled(new_enabled)
            if self.bandwidth_proxy is not None:
                self.bandwidth_proxy.configure(
                    new_enabled and self.bandwidth_proxy is not None, new_mbps)
            self.config["bandwidth_enabled"] = new_enabled
            self.config["bandwidth_mbps"] = new_mbps
            self.refresh_bandwidth_status()

        def persist():
            write_json(SETTINGS, self.config)
            current_proxy = self.bandwidth_proxy is not None
            if enabled.isChecked() != current_proxy:
                self.statusBar().showMessage(
                    "Bandbreitenlimit: Änderung erst nach Neustart wirksam", 7000)

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

    def open_native_video(self, url):
        """Select the native media engine automatically for supported domains."""
        if not needs_native_media_engine(url):
            return False
        location = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                    else Path(__file__).parent) / "Vaultie.Streaming.exe"
        if not location.is_file():
            QMessageBox.warning(
                self, "Videowiedergabe",
                "Die native Medien-Engine fehlt. Bitte Vaultie vollständig aktualisieren.")
            return True
        try:
            process = subprocess.Popen([str(location), url],
                                       cwd=str(location.parent), close_fds=True)
            self.native_video_processes = [
                p for p in self.native_video_processes if p.poll() is None]
            self.native_video_processes.append(process)
        except OSError as error:
            QMessageBox.warning(self, "Videowiedergabe", str(error))
        return True

    def add_tab(self, url=None, switch=True):
        view = QWebEngineView(self)
        page = BrowserPage(self.profile, self, view)
        view.setPage(page)
        page.fullScreenRequested.connect(lambda request, v=view:
                                         self.handle_fullscreen_request(request, v))
        view.titleChanged.connect(lambda title, v=view: self.set_tab_title(v, title))
        view.loadFinished.connect(lambda ok, v=view: self.record_history(v) if ok else None)
        view.loadFinished.connect(lambda ok, v=view: self.schedule_login_fill(v) if ok else None)
        view.urlChanged.connect(lambda _url, v=view: self.update_address(v))
        view.loadProgress.connect(lambda n: self.statusBar().showMessage(f"Lade {n} %" if n < 100 else self.connection_status()))
        idx = self.tabs.addTab(view, "Neuer Tab")
        self.tabs.setTabIcon(idx, QIcon(str(ASSETS / "vaultie.ico")))
        if switch:
            self.tabs.setCurrentIndex(idx)
        if url == HOME:
            view.setHtml(self.start_page_html(), QUrl("about:blank"))
        elif url:
            if not self.open_native_video(url):
                view.setUrl(QUrl(url))
        return view

    def handle_fullscreen_request(self, request, view):
        """Enable Qt fullscreen transitions for HTML5 players."""
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def choose_widevine_binary(self):
        """Specify a locally installed CDM, without copying or distributing it."""
        if sys.platform != "win32":
            QMessageBox.information(self, "Widevine", "Nur unter Windows verfügbar.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Vorhandene Widevine-DLL auswählen", "",
            "Widevine (widevinecdm.dll)")
        if not path:
            return
        if Path(path).name.lower() != "widevinecdm.dll" or not Path(path).is_file():
            QMessageBox.warning(self, "Widevine", "Nur eine vorhandene widevinecdm.dll auswählen.")
            return
        saved = read_json(SETTINGS, {})
        saved["widevine_path"] = path
        write_json(SETTINGS, saved)
        QMessageBox.information(self, "Widevine",
            "Die Datei ist für den nächsten Vaultie-Start vorgemerkt. "
            "Eine Freigabe durch Streamingdienste ist dadurch nicht garantiert.")

    def show_video_diagnostics(self):
        """Probe media codecs on a private internal page; probe DRM separately."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Vaultie – Video-Codecs und DRM")
        dialog.resize(665, 390)
        layout = QVBoxLayout(dialog)
        label = QLabel("Interne Codec-Prüfung wird gestartet …", dialog)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)
        details = QLabel(
            "Der Codec-Test läuft auf einer eigenen internen Seite und "
            "ist unabhängig von Prime Video. Widevine wird getrennt geprüft. "
            "Eine DRM-API-Zusage garantiert noch keine Filmwiedergabe.",
            dialog)
        details.setWordWrap(True)
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        # Keep the QWebEnginePage alive for the lifetime of the dialog.
        # No remote URL or third-party scripts are loaded for codec testing.
        probe = QWebEnginePage(self.profile, dialog)
        state = {"codec_done": False, "drm_done": False,
                 "codecs": None, "drm": "Noch nicht geprüft"}
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.setInterval(10000)

        def render():
            codecs = state["codecs"]
            if codecs is None:
                codec_lines = ["Codec-Test: läuft …"]
            elif "error" in codecs:
                codec_lines = ["Codec-Test: " + str(codecs["error"])]
            else:
                codec_lines = [
                    "H.264 (MP4): " + str(codecs.get("h264", "unbekannt")),
                    "AAC (MP4): " + str(codecs.get("aac", "unbekannt")),
                    "H.264 + AAC (MP4): " + str(codecs.get("mp4", "unbekannt")),
                    "VP9 + Opus (WebM): " + str(codecs.get("webm", "unbekannt")),
                    "MSE (MediaSource): " + str(codecs.get("mse", "unbekannt"))]
            label.setText("\\n".join(codec_lines + ["", "Widevine / DRM: " + state["drm"]]))

        def parse_json(raw):
            # JSON string sidesteps JS/QVariant conversion differences.
            if not isinstance(raw, str):
                return {"error": "Kein gültiger Rückgabewert aus der Browser-Engine"}
            try:
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("JSON-Objekt erwartet")
                return result
            except (ValueError, TypeError):
                return {"error": "Diagnosedaten konnten nicht gelesen werden"}

        def codec_result(raw):
            if state["codec_done"] or not dialog.isVisible():
                return
            state["codec_done"] = True
            state["codecs"] = parse_json(raw)
            render()

        codec_script = r"""
        (() => {
          try {
            const media = document.createElement('video');
            const can = mime => media.canPlayType(mime) || 'nein';
            return JSON.stringify({
              h264: can('video/mp4; codecs="avc1.42E01E"'),
              aac: can('audio/mp4; codecs="mp4a.40.2"'),
              mp4: can('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'),
              webm: can('video/webm; codecs="vp9, opus"'),
              mse: typeof MediaSource !== 'undefined'
            });
          } catch (e) {
            return JSON.stringify({error: String(e)});
          }
        })()
        """

        def ready(ok):
            if state["codec_done"] or not dialog.isVisible():
                return
            if not ok:
                codec_result(json.dumps(
                    {"error": "Interne Diagnoseseite konnte nicht geladen werden"}))
                return
            probe.runJavaScript(codec_script, codec_result)

        probe.loadFinished.connect(ready)
        probe.setHtml("<!doctype html><html><head><meta charset='utf-8'>"
                      "</head><body>Vaultie-Mediatest</body></html>")

        view = self.current()
        if not view or view.url().scheme() != "https":
            state["drm_done"] = True
            state["drm"] = "Für Widevine bitte eine HTTPS-Webseite öffnen"
        else:
            # The active HTTPS origin is required for this EME permission test.
            drm_script = r"""
            (() => {
              try {
                if (!window.isSecureContext)
                  return JSON.stringify({state:'Nicht sicherer Kontext'});
                if (typeof navigator.requestMediaKeySystemAccess !== 'function')
                  return JSON.stringify({state:'EME-API fehlt'});
                const request = navigator.requestMediaKeySystemAccess(
                  'com.widevine.alpha', [{
                    initDataTypes: ['cenc'],
                    videoCapabilities: [{
                      contentType: 'video/mp4; codecs="avc1.42E01E"'
                    }]
                  }]);
                window.__vaultieMediaDrm = JSON.stringify(
                  {state:'Widevine-Abfrage läuft'});
                request.then(
                  () => { window.__vaultieMediaDrm =
                    JSON.stringify({state:'Widevine-Zugang für H.264 angeboten'}); },
                  err => { window.__vaultieMediaDrm =
                    JSON.stringify({state:'Widevine nicht verfügbar: ' +
                      (err && err.name ? err.name : 'unbekannt')}); }
                );
                return JSON.stringify({state:'Widevine-Abfrage läuft'});
              } catch (e) {
                return JSON.stringify({state:'DRM-Abfrage fehlgeschlagen: ' +
                  String(e)});
              }
            })()
            """
            def drm_result(raw):
                if state["drm_done"] or not dialog.isVisible():
                    return
                result = parse_json(raw)
                state["drm"] = str(result.get("state", result.get("error", "Unbekannt")))
                if state["drm"] != "Widevine-Abfrage läuft":
                    state["drm_done"] = True
                render()

            def poll_drm(attempt=0):
                if state["drm_done"] or not dialog.isVisible():
                    return
                if attempt >= 7:
                    state["drm_done"] = True
                    state["drm"] = "Keine abschließende Antwort (Timeout)"
                    render()
                    return
                def polled(raw):
                    if state["drm_done"] or not dialog.isVisible():
                        return
                    drm_result(raw)
                    if not state["drm_done"]:
                        QTimer.singleShot(550, lambda: poll_drm(attempt + 1))
                view.page().runJavaScript(
                    "window.__vaultieMediaDrm || "
                    "'{\\\"state\\\":\\\"Keine Antwort\\\"}'",
                    polled)

            def started(raw):
                drm_result(raw)
                if not state["drm_done"]:
                    QTimer.singleShot(550, poll_drm)
            view.page().runJavaScript(drm_script, started)

        def expired():
            if not state["codec_done"]:
                state["codec_done"] = True
                state["codecs"] = {"error": "Interne Browser-Engine antwortet nicht (Timeout)"}
            if not state["drm_done"]:
                state["drm_done"] = True
                state["drm"] = "DRM-Abfrage ohne Antwort (Timeout)"
            render()

        timer.timeout.connect(expired)
        timer.start()
        render()
        dialog.exec()
        timer.stop()

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
        if not self.open_native_video(dest):
            self.current().setUrl(QUrl(dest))

    def close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget:
            self.tabs.removeTab(index)
            widget.deleteLater()
        if self.tabs.count() == 0:
            self.add_tab(HOME)

    def schedule_login_fill(self, view):
        """Autofill immediately and react to dynamically inserted sign-in forms.

        Install one short-lived MutationObserver only when credentials for the
        exact HTTPS origin exist. No Python timer loop or additional process.
        """
        self.autofill_login(view)

    def autofill_login(self, view, manual=False):
        """Fill known HTTPS login fields, including late SPA/login-dialog fields."""
        if not self.vault:
            if manual:
                QMessageBox.warning(self, "Zugangsdaten",
                                    self.vault_error or "Passwortspeicher nicht verfügbar.")
            return
        origin = secure_origin(view.url().toString())
        if not origin:
            if manual:
                QMessageBox.information(self, "Login ausfüllen",
                                        "Bitte die sichere HTTPS-Anmeldeseite öffnen.")
            return
        saved = self.vault.get(origin)
        if not saved:
            if manual:
                QMessageBox.information(self, "Login ausfüllen",
                    "Für diese Webadresse ist kein Login gespeichert.\\n"
                    "Möglicherweise verwendet die Webseite eine andere Login-Domain.")
            return
        payload = json.dumps(saved, ensure_ascii=True)
        expected_origin = json.dumps(origin, ensure_ascii=True)
        script = """
        (() => {
          if (window.top !== window.self ||
              window.location.origin !== EXPECTED_ORIGIN) return "origin";
          const credentials = PAYLOAD;
          // Do not touch password reset or account-registration forms.
          const visible = el => el && !el.disabled && !el.readOnly &&
            el.getClientRects().length > 0;
          const fill = (field, value) => {
            if (!visible(field) || field.value) return false;
            const setter = Object.getOwnPropertyDescriptor(
              HTMLInputElement.prototype, "value").set;
            setter.call(field, value);
            field.dispatchEvent(new Event("input", {bubbles:true}));
            field.dispatchEvent(new Event("change", {bubbles:true}));
            return true;
          };
          let usernameFilled = false;
          let passwordFilled = false;
          const attempt = () => {
            if (window.location.origin !== EXPECTED_ORIGIN) return "origin";
            const fields = Array.from(document.querySelectorAll("input")).filter(visible);
            const pass = fields.find(el => el.type === "password" &&
              !/new-password|one-time-code/.test(el.autocomplete || ""));
            const container = pass ? (pass.form || document) : document;
            const users = Array.from(container.querySelectorAll("input")).filter(visible);
            const user = users.find(el => el.autocomplete === "username") ||
              users.find(el => el.type === "email") ||
              users.find(el => /^(text|email)$/.test(el.type) &&
                /user|login|email|identifier/i.test(
                  [el.name, el.id, el.autocomplete].join(" ")));
            if (user) usernameFilled = fill(user, credentials.username) || usernameFilled;
            if (pass) passwordFilled = fill(pass, credentials.password) || passwordFilled;
            if (passwordFilled) return "filled";
            if (usernameFilled) return "username";
            return pass || user ? "existing" : "missing";
          };
          let status = attempt();
          if (status === "filled") return status;
          // Login forms often appear after loadFinished or after clicking "Anmelden".
          // Observe DOM changes instead of running CPU-consuming periodic checks.
          if (window.__vaultieLoginObserver) window.__vaultieLoginObserver.disconnect();
          let pending = false;
          const observer = new MutationObserver(() => {
            if (pending) return;
            pending = true;
            setTimeout(() => {
              pending = false;
              status = attempt();
              if (status === "filled" || status === "origin") observer.disconnect();
            }, 150);
          });
          window.__vaultieLoginObserver = observer;
          observer.observe(document.documentElement, {childList:true, subtree:true});
          window.addEventListener("pagehide", () => observer.disconnect(), {once:true});
          setTimeout(() => observer.disconnect(), 120000);
          return status;
        })();
        """.replace("PAYLOAD", payload).replace("EXPECTED_ORIGIN", expected_origin)
        if manual:
            view.page().runJavaScript(script, lambda result: self.show_autofill_result(result))
        else:
            view.page().runJavaScript(script)

    def fill_current_login(self):
        view = self.current()
        if view:
            self.autofill_login(view, manual=True)

    def show_autofill_result(self, result):
        if result == "filled":
            self.statusBar().showMessage("Login-Felder ausgefüllt", 4000)
        elif result == "existing":
            QMessageBox.information(self, "Login ausfüllen",
                "Die vorhandenen Felder sind bereits ausgefüllt. "
                "Vaultie überschreibt eingegebene Daten nicht.")
        else:
            QMessageBox.information(self, "Login ausfüllen",
                "Auf dieser Seite wurden keine passenden Login-Felder gefunden. "
                "Öffne zuerst das Anmeldeformular der Webseite.")

    def show_login_actions(self):
        menu = QMenu(self)
        menu.addAction("Gespeichertes Login ausfüllen", self.fill_current_login)
        menu.addAction("Login speichern", self.save_login_from_page)
        menu.addAction("Gespeicherte Logins verwalten", self.show_saved_logins)
        button = self.sender()
        if isinstance(button, QToolButton):
            menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        else:
            menu.exec()

    def save_login_from_page(self):
        """Always offer a visible way to store a login, including after signing in.

        Values can be imported from the current form, or entered manually when
        the login page has already disappeared. Never stores without consent.
        """
        view = self.current()
        if not view or not self.vault:
            QMessageBox.warning(self, "Zugangsdaten", self.vault_error or
                                "Der lokale Passwortspeicher ist nicht verfügbar.")
            return
        origin = secure_origin(view.url().toString())
        if not origin:
            QMessageBox.information(
                self, "Zugangsdaten",
                "Bitte zuerst eine sichere HTTPS-Webseite öffnen.")
            return
        script = """
        (() => {
          if (window.top !== window.self) return null;
          const p = document.querySelector('input[type="password"]:not([disabled])');
          if (!p) return null;
          const form = p.form || document;
          const inputs = Array.from(form.querySelectorAll(
            'input[autocomplete="username"],input[type="email"],input[type="text"]'
          )).filter(x => !x.disabled);
          const u = inputs.find(x => x.autocomplete === "username") ||
                    inputs.find(x => x.type === "email") || inputs[0];
          return {username: u ? u.value : "", password: p.value};
        })();
        """
        view.page().runJavaScript(
            script, lambda values, source=view, site=origin:
                self.show_save_login_dialog(source, site, values))

    def show_save_login_dialog(self, source, origin, values):
        if not self.vault or secure_origin(source.url().toString()) != origin:
            return
        values = values if isinstance(values, dict) else {}
        existing = self.vault.get(origin) or {}
        dialog = QDialog(self)
        dialog.setWindowTitle("Login lokal speichern")
        dialog.resize(460, 210)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Benutzername und Passwort werden nur nach deiner Bestätigung "
            "verschlüsselt auf diesem Windows-PC gespeichert."))
        form = QFormLayout()
        username = QLineEdit(dialog)
        username.setPlaceholderText("E-Mail-Adresse oder Benutzername")
        username.setText(values.get("username") or existing.get("username", ""))
        password = QLineEdit(dialog)
        password.setPlaceholderText("Passwort eingeben, falls es nicht mehr im Formular steht")
        password.setEchoMode(QLineEdit.EchoMode.Password)
        # Do not display or silently reuse existing stored passwords.
        password.setText(values.get("password") or "")
        show_password = QCheckBox("Passwort kurz anzeigen", dialog)
        show_password.toggled.connect(lambda enabled: password.setEchoMode(
            QLineEdit.EchoMode.Normal if enabled else QLineEdit.EchoMode.Password))
        form.addRow("Webseite:", QLabel(origin, dialog))
        form.addRow("Benutzername:", username)
        form.addRow("Passwort:", password)
        layout.addLayout(form)
        layout.addWidget(show_password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Verschlüsselt speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        layout.addWidget(buttons)

        def save():
            if not username.text().strip() or not password.text():
                QMessageBox.warning(dialog, "Zugangsdaten",
                                    "Bitte Benutzername und Passwort eintragen.")
                return
            if secure_origin(source.url().toString()) != origin:
                QMessageBox.warning(dialog, "Zugangsdaten",
                                    "Die Webseite hat sich geändert. Bitte erneut öffnen.")
                return
            try:
                self.vault.save(origin, username.text().strip(), password.text())
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, "Zugangsdaten", str(exc))
                return
            dialog.accept()
            self.statusBar().showMessage("Login sicher und lokal gespeichert", 4000)

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def show_saved_logins(self):
        if not self.vault:
            QMessageBox.warning(self, "Zugangsdaten",
                                self.vault_error or "Passwortspeicher nicht verfügbar.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Lokal gespeicherte Anmeldungen")
        dialog.resize(650, 380)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Passwörter sind mit dem Windows-Benutzerkonto verschlüsselt."))
        items = QListWidget(dialog)
        layout.addWidget(items)
        def refresh():
            items.clear()
            for origin, username in self.vault.list_entries():
                items.addItem(origin + " — " + username)
        def remove_selected():
            index = items.currentRow()
            entries = self.vault.list_entries()
            if not 0 <= index < len(entries):
                return
            origin = entries[index][0]
            if QMessageBox.question(dialog, "Login löschen",
                                    f"Gespeichertes Login für {origin} löschen?"
                                    ) != QMessageBox.StandardButton.Yes:
                return
            try:
                self.vault.remove(origin)
                refresh()
            except OSError as exc:
                QMessageBox.warning(dialog, "Zugangsdaten", str(exc))
        row = QHBoxLayout()
        for label, callback in (("Ausgewähltes Login löschen", remove_selected),
                                ("Schließen", dialog.reject)):
            button = QPushButton(label, dialog)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        refresh()
        dialog.exec()

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

    def download_label(self, entry):
        item = entry["request"]
        path = entry["path"]
        try:
            state = item.state()
            if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                status = "Fertig"
            elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
                status = "Abgebrochen"
            elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
                status = "Fehler"
            else:
                received = item.receivedBytes()
                total = item.totalBytes()
                if total > 0:
                    status = f"{received * 100 // total}% ({received // 1048576} / {total // 1048576} MB)"
                else:
                    status = f"{received // 1048576} MB empfangen"
        except RuntimeError:
            status = "Status unbekannt"
        return f"{path.name} — {status}"

    def refresh_downloads(self):
        button = getattr(self, "download_button", None)
        active = 0
        for entry in self.download_items:
            try:
                if entry["request"].state() == QWebEngineDownloadRequest.DownloadState.DownloadInProgress:
                    active += 1
            except RuntimeError:
                pass
        if button is not None:
            button.setText(f"↓ Downloads ({active})" if active else "↓ Downloads")
        if self.downloads_dialog is not None and self.downloads_dialog.isVisible():
            widget = self.downloads_dialog.findChild(QListWidget, "downloadList")
            if widget:
                current = widget.currentRow()
                widget.clear()
                for entry in self.download_items:
                    widget.addItem(self.download_label(entry))
                if 0 <= current < widget.count():
                    widget.setCurrentRow(current)

    def show_downloads(self):
        if self.downloads_dialog is not None and self.downloads_dialog.isVisible():
            self.downloads_dialog.raise_()
            self.downloads_dialog.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Vaultie – Downloads")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.resize(700, 380)
        self.downloads_dialog = dialog
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Speicherort: {DOWNLOADS}"))
        items = QListWidget(dialog)
        items.setObjectName("downloadList")
        layout.addWidget(items)
        row = QHBoxLayout()

        def selected():
            index = items.currentRow()
            if 0 <= index < len(self.download_items):
                return self.download_items[index]
            return None

        def open_selected():
            entry = selected()
            if not entry:
                return
            path = entry["path"]
            if not path.is_file():
                QMessageBox.warning(dialog, "Download", "Datei ist noch nicht fertig oder nicht vorhanden.")
                return
            if sys.platform == "win32":
                os.startfile(str(path))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        def show_folder():
            entry = selected()
            folder = entry["path"].parent if entry else DOWNLOADS
            if sys.platform == "win32":
                os.startfile(str(folder))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

        def cancel_selected():
            entry = selected()
            if not entry:
                return
            req = entry["request"]
            if req.state() == QWebEngineDownloadRequest.DownloadState.DownloadInProgress:
                req.cancel()

        for label, callback in (
                ("Datei öffnen", open_selected),
                ("Ordner öffnen", show_folder),
                ("Download abbrechen", cancel_selected),
                ("Schließen", dialog.close)):
            button = QPushButton(label, dialog)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        timer = QTimer(dialog)
        timer.setInterval(400)
        timer.timeout.connect(self.refresh_downloads)
        timer.start()
        dialog.destroyed.connect(lambda: setattr(self, "downloads_dialog", None))
        self.refresh_downloads()
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

    def toggle_session_persistence(self):
        enabled = not self.config.get("remember_website_sessions", False)
        if enabled:
            if QMessageBox.question(
                    self, "Website-Sitzungen behalten",
                    "Anmeldungen sollen auch nach dem Schließen von Vaultie erhalten "
                    "bleiben. Dafür muss Vaultie Website-Cookies und technische "
                    "Sitzungsdaten lokal auf diesem Computer speichern.\\n\\n"
                    "Der verschlüsselte Passwortspeicher bleibt unabhängig davon. "
                    "Möchtest du die dauerhafte Speicherung einschalten?"
                    ) != QMessageBox.StandardButton.Yes:
                return
        self.config["remember_website_sessions"] = enabled
        write_json(SETTINGS, self.config)
        QMessageBox.information(
            self, "Website-Sitzungen",
            ("Website-Sitzungen bleiben nach dem Neustart gespeichert."
             if enabled else
             "Website-Sitzungen werden künftig beim Beenden verworfen.")
            + "\\nBitte Vaultie vollständig schließen und neu starten.")

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
        result = QMessageBox.question(
            self, "Website-Daten löschen",
            "Sitzungs-Cookies und HTTP-Cache löschen?\n"
            "Lokal verschlüsselte Logins, Lesezeichen und Verlauf bleiben erhalten.")
        if result != QMessageBox.StandardButton.Yes:
            return
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearHttpCache()
        self.profile.clearAllVisitedLinks()
        QMessageBox.information(self, "Website-Daten",
            "Cookies und Cache wurden zur Löschung angewiesen.\n"
            "Weitere Website-Daten werden beim Beenden der privaten Sitzung verworfen.")

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
            "Lesezeichen und Verlauf bleiben lokal. Nur ausdrücklich gespeicherte "
            "Logins werden mit Windows DPAPI verschlüsselt und nicht synchronisiert. "
            "Website-Sitzungen bleiben standardmäßig nur während des Betriebs bestehen. "
            "Optional können Cookies und Sitzungsdaten lokal dauerhaft gespeichert "
            "werden, damit Anmeldungen nach einem Neustart erhalten bleiben.\\n\\n"
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
        """Accept real Qt downloads into the normal Downloads folder."""
        suggested = Path(item.downloadFileName() or "download").name
        if not suggested or suggested in (".", ".."):
            suggested = "download"
        output = DOWNLOADS / suggested
        stem, suffix = output.stem, output.suffix
        counter = 1
        reserved = {entry["path"] for entry in self.download_items}
        while output.exists() or output in reserved:
            output = DOWNLOADS / f"{stem}-{counter}{suffix}"
            counter += 1
        item.setDownloadDirectory(str(DOWNLOADS))
        item.setDownloadFileName(output.name)
        self.download_items.append({"request": item, "path": output})
        self.session_downloads.append(str(output))
        item.receivedBytesChanged.connect(self.refresh_downloads)
        item.totalBytesChanged.connect(self.refresh_downloads)
        item.stateChanged.connect(self.refresh_downloads)
        item.accept()
        self.refresh_downloads()
        self.statusBar().showMessage(f"Download gestartet: {output.name}", 5000)


def main():
    config = configuration()
    try:
        local_proxy = (LocalBandwidthProxy(
            True, config.get("bandwidth_mbps", 10))
            if config.get("bandwidth_enabled", False) else None)
    except OSError as exc:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "Vaultie - Bandbreitenlimit",
            "Der lokale Netzwerkbegrenzer konnte nicht gestartet werden. "
            "Vaultie startet aus Sicherheitsgründen nicht mit einem "
            f"unbemerkten Netzwerkausnahmefall.\n\n{exc}")
        return 1
    preconfigure_chromium(local_proxy.port if local_proxy else None)
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
    if local_proxy is not None:
        local_proxy.stop()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
