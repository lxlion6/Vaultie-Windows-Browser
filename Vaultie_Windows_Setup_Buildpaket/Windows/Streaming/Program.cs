using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Vaultie.Streaming;

internal static class Program
{
    internal static readonly string BaseDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Vaultie");
    internal static readonly string Home = "https://www.startpage.com/";
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Directory.CreateDirectory(BaseDir);
        var initial = args.Length > 0 && SafeUrl(args[0]) ? args[0] : Home;
        Application.Run(new VaultieWindow(initial));
    }
    internal static bool SafeUrl(string? text) =>
        Uri.TryCreate(text, UriKind.Absolute, out var u)
        && (u.Scheme == Uri.UriSchemeHttps || u.Scheme == Uri.UriSchemeHttp);
}

internal sealed class VaultieWindow : Form
{
    private readonly TabControl tabs = new() { Dock = DockStyle.Fill };
    private readonly TextBox address = new() { Dock = DockStyle.Fill, Font = new Font("Segoe UI", 11f) };
    private readonly Label status = new() {
        Dock = DockStyle.Bottom, Height = 26, ForeColor = Color.White,
        BackColor = Color.FromArgb(12, 48, 57), Padding = new Padding(10, 5, 0, 0),
        Text = "Vaultie · WebView2" };
    private readonly FlowLayoutPanel buttons = new() {
        Dock = DockStyle.Top, Height = 42, FlowDirection = FlowDirection.LeftToRight,
        WrapContents = false, AutoScroll = false,
        BackColor = Color.FromArgb(12, 48, 57) };
    private readonly Panel top = new() {
        Dock = DockStyle.Top, Height = 84, BackColor = Color.FromArgb(12, 48, 57) };
    private readonly Dictionary<TabPage, WebView2> views = new();
    private readonly List<string> bookmarks = new();
    private readonly List<(string Name, string Path, CoreWebView2DownloadOperation Operation)> downloads = new();
    private readonly string bookmarkPath = Path.Combine(Program.BaseDir, "bookmarks.json");
    private readonly string initialUrl;
    private CoreWebView2Environment? environment;
    private bool fullscreen;
    private Rectangle previousBounds;
    private FormWindowState previousState;
    private readonly Color dark = Color.FromArgb(12, 48, 57);

    public VaultieWindow(string initial)
    {
        initialUrl = initial;
        Text = "Vaultie";
        Icon = SystemIcons.Application;
        BackColor = Color.FromArgb(14, 29, 33);
        ForeColor = Color.White;
        Width = 1280;
        Height = 820;
        MinimumSize = new Size(720, 480);
        LoadBookmarks();

        AddButton("←", () => { if (ActiveView?.CanGoBack == true) ActiveView.GoBack(); });
        AddButton("→", () => { if (ActiveView?.CanGoForward == true) ActiveView.GoForward(); });
        AddButton("↻", () => ActiveView?.Reload());
        AddButton("⌂", () => Navigate(Program.Home));
        AddButton("+", () => _ = AddTab(Program.Home));
        AddButton("★", BookmarkCurrent);
        AddButton("Lesezeichen", ShowBookmarks);
        AddButton("↓ Downloads", ShowDownloads);
        AddButton("⋯", ShowMenu);
        top.Controls.Add(address);
        address.Location = new Point(12, 49);
        address.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
        address.Width = 1150;
        address.KeyDown += (_, e) => {
            if (e.KeyCode == Keys.Enter) { NavigateInput(); e.SuppressKeyPress = true; }
        };
        top.Controls.Add(buttons);
        Controls.Add(tabs);
        Controls.Add(top);
        Controls.Add(status);
        tabs.SelectedIndexChanged += (_, _) => UpdateAddress();
        tabs.MouseDown += (_, e) => {
            if (e.Button != MouseButtons.Middle) return;
            for (int n = 0; n < tabs.TabCount; n++)
                if (tabs.GetTabRect(n).Contains(e.Location)) { CloseTab(tabs.TabPages[n]); break; }
        };
        KeyPreview = true;
        KeyDown += (_, e) => {
            if (e.Control && e.KeyCode == Keys.L) { address.Focus(); address.SelectAll(); e.SuppressKeyPress = true; }
            else if (e.Control && e.KeyCode == Keys.T) { _ = AddTab(Program.Home); e.SuppressKeyPress = true; }
            else if (e.Control && e.KeyCode == Keys.W) { if (tabs.SelectedTab != null) CloseTab(tabs.SelectedTab); e.SuppressKeyPress = true; }
            else if (e.Control && e.KeyCode == Keys.D) { BookmarkCurrent(); e.SuppressKeyPress = true; }
            else if (e.KeyCode == Keys.F5) { ActiveView?.Reload(); e.SuppressKeyPress = true; }
            else if (e.KeyCode == Keys.Escape && fullscreen) LeaveFullscreen();
        };
        Shown += async (_, _) => {
            try {
                var profile = Path.Combine(Program.BaseDir, "webview2-profile");
                Directory.CreateDirectory(profile);
                environment = await CoreWebView2Environment.CreateAsync(null, profile);
                await AddTab(initialUrl);
            }
            catch (Exception ex) {
                MessageBox.Show(this, "Microsoft WebView2 konnte nicht gestartet werden. "
                    + "Prüfe die WebView2-Runtime.\n\n" + ex.Message,
                    "Vaultie – Browser-Engine", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        };
        Resize += (_, _) => address.Width = Math.Max(200, top.ClientSize.Width - 24);
    }

    private WebView2? ActiveView =>
        tabs.SelectedTab != null && views.TryGetValue(tabs.SelectedTab, out var v) ? v : null;

    private void AddButton(string text, Action action)
    {
        var b = new Button {
            Text = text, Width = text.Length > 3 ? 105 : 48, Height = 32,
            ForeColor = Color.White, BackColor = Color.FromArgb(18, 76, 86),
            FlatStyle = FlatStyle.Flat, Margin = new Padding(4, 4, 0, 2)
        };
        b.FlatAppearance.BorderSize = 0;
        b.Click += (_, _) => action();
        buttons.Controls.Add(b);
    }

    private async Task AddTab(string url)
    {
        if (environment == null) return;
        var tab = new TabPage("Neuer Tab") { BackColor = Color.Black };
        var view = new WebView2 { Dock = DockStyle.Fill };
        tab.Controls.Add(view);
        tabs.TabPages.Add(tab);
        views[tab] = view;
        tabs.SelectedTab = tab;
        try {
            await view.EnsureCoreWebView2Async(environment);
            var core = view.CoreWebView2;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = true;
            core.Settings.IsPasswordAutosaveEnabled = true;
            core.Settings.IsGeneralAutofillEnabled = true;
            core.NavigationStarting += (_, e) => {
                if (!Program.SafeUrl(e.Uri)) { e.Cancel = true; return; }
                status.Text = "Lade Webseite …";
            };
            core.NavigationCompleted += (_, e) => {
                status.Text = e.IsSuccess ? "Bereit" : "Seitenfehler: " + e.WebErrorStatus;
            };
            core.SourceChanged += (_, _) => { if (tabs.SelectedTab == tab) UpdateAddress(); };
            core.DocumentTitleChanged += (_, _) => {
                string title = core.DocumentTitle;
                tab.Text = title.Length > 24 ? title[..24] + "…" : title;
                if (tabs.SelectedTab == tab) Text = title + " – Vaultie";
            };
            core.NewWindowRequested += (_, e) => {
                e.Handled = true;
                if (Program.SafeUrl(e.Uri)) _ = AddTab(e.Uri);
            };
            core.ContainsFullScreenElementChanged += (_, _) => {
                if (tabs.SelectedTab != tab) return;
                if (core.ContainsFullScreenElement) EnterFullscreen();
                else LeaveFullscreen();
            };
            var downloadsFolder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
            Directory.CreateDirectory(downloadsFolder);
            core.Profile.DefaultDownloadFolderPath = downloadsFolder;
            core.DownloadStarting += (_, e) => {
                var op = e.DownloadOperation;
                var filename = Path.GetFileName(op.ResultFilePath);
                downloads.Add((filename, op.ResultFilePath, op));
                status.Text = "Download: " + filename;
                op.StateChanged += (_, _) => {
                    if (op.State == CoreWebView2DownloadState.Completed)
                        status.Text = "Download abgeschlossen: " + filename;
                    else if (op.State == CoreWebView2DownloadState.Interrupted)
                        status.Text = "Download unterbrochen: " + filename;
                };
            };
            if (Program.SafeUrl(url)) core.Navigate(url);
        }
        catch (Exception error) {
            status.Text = "Tab konnte nicht geladen werden: " + error.Message;
        }
    }

    private void UpdateAddress()
    {
        address.Text = ActiveView?.CoreWebView2?.Source ?? "";
        var title = ActiveView?.CoreWebView2?.DocumentTitle;
        Text = string.IsNullOrWhiteSpace(title) ? "Vaultie" : title + " – Vaultie";
    }

    private void NavigateInput()
    {
        var text = address.Text.Trim();
        if (string.IsNullOrWhiteSpace(text)) return;
        string destination;
        if (Program.SafeUrl(text)) destination = text;
        else if (!text.Contains(' ') && text.Contains('.') && !text.Contains(':'))
            destination = "https://" + text;
        else destination = "https://www.startpage.com/sp/search?query=" +
            Uri.EscapeDataString(text);
        Navigate(destination);
    }

    private void Navigate(string url)
    {
        if (!Program.SafeUrl(url)) { status.Text = "Ungültige Internetadresse"; return; }
        if (ActiveView?.CoreWebView2 != null) ActiveView.CoreWebView2.Navigate(url);
        else _ = AddTab(url);
    }

    private void CloseTab(TabPage page)
    {
        if (views.Remove(page, out var view)) view.Dispose();
        tabs.TabPages.Remove(page);
        page.Dispose();
        if (tabs.TabCount == 0) _ = AddTab(Program.Home);
    }

    private void LoadBookmarks()
    {
        if (!File.Exists(bookmarkPath)) return;
        try {
            using var doc = JsonDocument.Parse(File.ReadAllText(bookmarkPath));
            if (doc.RootElement.ValueKind != JsonValueKind.Array) return;
            foreach (var item in doc.RootElement.EnumerateArray()) {
                if (item.ValueKind == JsonValueKind.Object &&
                    item.TryGetProperty("url", out var v) &&
                    Program.SafeUrl(v.GetString()))
                    bookmarks.Add(v.GetString()!);
                else if (item.ValueKind == JsonValueKind.String &&
                         Program.SafeUrl(item.GetString()))
                    bookmarks.Add(item.GetString()!);
            }
        } catch (Exception) { }
    }

    private void BookmarkCurrent()
    {
        var url = ActiveView?.CoreWebView2?.Source;
        if (!Program.SafeUrl(url) || bookmarks.Contains(url!)) return;
        bookmarks.Add(url!);
        try {
            var records = bookmarks.Select(v => new {
                title = new Uri(v).Host, url = v
            }).ToArray();
            File.WriteAllText(bookmarkPath, JsonSerializer.Serialize(records,
                new JsonSerializerOptions { WriteIndented = true }));
            status.Text = "Lesezeichen gespeichert";
        } catch (Exception e) { status.Text = "Lesezeichen: " + e.Message; }
    }

    private void ShowBookmarks()
    {
        var menu = new ContextMenuStrip();
        foreach (var url in bookmarks) {
            var title = new Uri(url).Host + " – " + url;
            menu.Items.Add(title.Length > 95 ? title[..95] : title,
                null, (sender, evt) => { _ = AddTab(url); });
        }
        if (bookmarks.Count == 0) menu.Items.Add("Noch keine Lesezeichen");
        menu.Show(this, new Point(165, 44));
    }

    private void ShowDownloads()
    {
        var dialog = new Form {
            Text = "Vaultie – Downloads", Width = 680, Height = 390,
            StartPosition = FormStartPosition.CenterParent
        };
        var list = new ListBox { Dock = DockStyle.Fill };
        void Reload() {
            list.Items.Clear();
            foreach (var d in downloads) {
                var statusText = d.Operation.State.ToString();
                var bytes = d.Operation.BytesReceived;
                list.Items.Add(d.Name + " – " + statusText + " – " +
                    Math.Round(bytes / 1048576d, 1) + " MB");
            }
        }
        var bottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 46 };
        void Button(string title, Action act) {
            var b = new Button { Text = title, AutoSize = true };
            b.Click += (_, _) => act();
            bottom.Controls.Add(b);
        }
        Button("Ordner öffnen", () => System.Diagnostics.Process.Start(
            new System.Diagnostics.ProcessStartInfo {
                FileName = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                    "Downloads"), UseShellExecute = true }));
        Button("Datei öffnen", () => {
            int n = list.SelectedIndex;
            if (n >= 0 && n < downloads.Count && File.Exists(downloads[n].Path))
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo {
                    FileName = downloads[n].Path, UseShellExecute = true });
        });
        Button("Abbrechen", () => {
            int n = list.SelectedIndex;
            if (n >= 0 && n < downloads.Count) downloads[n].Operation.Cancel();
        });
        dialog.Controls.Add(list);
        dialog.Controls.Add(bottom);
        var timer = new System.Windows.Forms.Timer { Interval = 600 };
        timer.Tick += (_, _) => { int selected = list.SelectedIndex; Reload();
            if (selected >= 0 && selected < list.Items.Count) list.SelectedIndex = selected; };
        timer.Start();
        dialog.FormClosed += (_, _) => timer.Dispose();
        Reload();
        dialog.Show(this);
    }

    private void ShowMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Neuer Tab", null, (sender, evt) => { _ = AddTab(Program.Home); });
        menu.Items.Add("Tab schließen", null, (_, _) => {
            if (tabs.SelectedTab != null) CloseTab(tabs.SelectedTab);
        });
        menu.Items.Add("Lesezeichen", null, (_, _) => ShowBookmarks());
        menu.Items.Add("Downloads", null, (_, _) => ShowDownloads());
        menu.Items.Add("WebView2-Version", null, (_, _) => MessageBox.Show(this,
            environment?.BrowserVersionString ?? "nicht initialisiert",
            "Vaultie – Browser-Engine"));
        menu.Items.Add("Auf Updates prüfen", null, (sender, evt) => {
            _ = AddTab("https://github.com/lxlion6/Vaultie-Windows-Browser/releases/tag/windows-latest");
        });
        menu.Items.Add("Datenschutz", null, (_, _) => MessageBox.Show(this,
            "WebView2 verwendet ein lokales Browserprofil unter %LOCALAPPDATA%\\Vaultie. " +
            "Cookies und Anmeldungen werden auf dem Computer gespeichert. " +
            "Die Sicherheitsupdates der Engine erfolgen über die Microsoft WebView2 Runtime. " +
            "Streamingdienste können DRM-geschützte Videos dennoch ablehnen.",
            "Vaultie – Datenschutz"));
        menu.Show(this, new Point(500, 44));
    }

    private void EnterFullscreen()
    {
        if (fullscreen) return;
        fullscreen = true;
        previousBounds = Bounds;
        previousState = WindowState;
        top.Visible = false;
        status.Visible = false;
        tabs.Appearance = TabAppearance.FlatButtons;
        tabs.ItemSize = new Size(0, 1);
        tabs.SizeMode = TabSizeMode.Fixed;
        FormBorderStyle = FormBorderStyle.None;
        WindowState = FormWindowState.Maximized;
    }

    private void LeaveFullscreen()
    {
        if (!fullscreen) return;
        fullscreen = false;
        FormBorderStyle = FormBorderStyle.Sizable;
        WindowState = previousState;
        if (previousState == FormWindowState.Normal) Bounds = previousBounds;
        top.Visible = true;
        status.Visible = true;
        tabs.Appearance = TabAppearance.Normal;
        tabs.SizeMode = TabSizeMode.Normal;
    }
}
