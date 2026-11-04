using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Vaultie.Streaming;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var url = args.Length > 0 && IsSafeUrl(args[0])
            ? args[0] : "https://www.primevideo.com/";
        Application.Run(new StreamingWindow(url));
    }

    internal static bool IsSafeUrl(string? value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri)
        && (uri.Scheme == Uri.UriSchemeHttps || uri.Scheme == Uri.UriSchemeHttp);
}

internal sealed class StreamingWindow : Form
{
    private readonly WebView2 browser = new() { Dock = DockStyle.Fill };
    private readonly TextBox address = new() { Dock = DockStyle.Fill };
    private readonly Label status = new() {
        Dock = DockStyle.Bottom, AutoSize = false, Height = 25,
        Text = "Streaming-Modus: Microsoft WebView2", ForeColor = Color.White,
        BackColor = Color.FromArgb(4, 39, 47), Padding = new Padding(8, 4, 0, 0)
    };
    private readonly Panel controls = new() {
        Dock = DockStyle.Top, Height = 48, BackColor = Color.FromArgb(5, 45, 53),
        Padding = new Padding(7)
    };
    private readonly string initialUrl;

    public StreamingWindow(string initialUrl)
    {
        this.initialUrl = initialUrl;
        Text = "Vaultie – Streaming";
        Width = 1240;
        Height = 800;
        MinimumSize = new Size(680, 420);
        BackColor = Color.Black;

        var row = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 5,
            RowCount = 1, BackColor = controls.BackColor };
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 43));
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 43));
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 43));
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 55));
        var back = NavButton("←");
        var forward = NavButton("→");
        var refresh = NavButton("↻");
        var go = NavButton("Los");
        back.Click += (_, _) => { if (browser.CanGoBack) browser.GoBack(); };
        forward.Click += (_, _) => { if (browser.CanGoForward) browser.GoForward(); };
        refresh.Click += (_, _) => browser.Reload();
        go.Click += (_, _) => Navigate();
        address.Font = new Font("Segoe UI", 10f);
        address.BorderStyle = BorderStyle.FixedSingle;
        address.KeyDown += (_, e) => {
            if (e.KeyCode == Keys.Enter) { Navigate(); e.SuppressKeyPress = true; }
        };
        row.Controls.Add(back, 0, 0);
        row.Controls.Add(forward, 1, 0);
        row.Controls.Add(refresh, 2, 0);
        row.Controls.Add(address, 3, 0);
        row.Controls.Add(go, 4, 0);
        controls.Controls.Add(row);
        Controls.Add(browser);
        Controls.Add(controls);
        Controls.Add(status);
        Shown += async (_, _) => {
            try {
                var data = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Vaultie", "webview2-streaming");
                Directory.CreateDirectory(data);
                var environment = await CoreWebView2Environment.CreateAsync(
                    browserExecutableFolder: null, userDataFolder: data);
                await browser.EnsureCoreWebView2Async(environment);
                browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
                browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
                browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
                browser.CoreWebView2.NavigationStarting += (_, e) => {
                    if (!Program.IsSafeUrl(e.Uri)) e.Cancel = true;
                    status.Text = "Seite lädt …";
                };
                browser.CoreWebView2.NavigationCompleted += (_, e) =>
                    status.Text = e.IsSuccess ? "Bereit" :
                        "Laden fehlgeschlagen: " + e.WebErrorStatus;
                browser.CoreWebView2.SourceChanged += (_, _) =>
                    address.Text = browser.CoreWebView2.Source;
                browser.CoreWebView2.DocumentTitleChanged += (_, _) =>
                    Text = browser.CoreWebView2.DocumentTitle + " – Vaultie Streaming";
                browser.CoreWebView2.NewWindowRequested += (_, e) => {
                    // Prevent uncontrolled popup windows. Open HTTP(S) in this view.
                    e.Handled = true;
                    if (Program.IsSafeUrl(e.Uri)) browser.CoreWebView2.Navigate(e.Uri);
                };
                browser.CoreWebView2.ContainsFullScreenElementChanged += (_, _) => {
                    bool fullscreen = browser.CoreWebView2.ContainsFullScreenElement;
                    controls.Visible = !fullscreen;
                    status.Visible = !fullscreen;
                    if (fullscreen) WindowState = FormWindowState.Maximized;
                };
                browser.CoreWebView2.Profile.DefaultDownloadFolderPath =
                    Path.Combine(Environment.GetFolderPath(
                        Environment.SpecialFolder.UserProfile), "Downloads");
                browser.CoreWebView2.DownloadStarting += (_, _) =>
                    status.Text = "Download gestartet (Windows-Downloadordner)";
                browser.CoreWebView2.Navigate(initialUrl);
            }
            catch (Exception error) {
                MessageBox.Show(this, "Streaming-Modus konnte nicht starten. " +
                    "Prüfe, ob die Microsoft WebView2-Runtime installiert ist.\n\n" +
                    error.Message, "Vaultie Streaming", MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                Close();
            }
        };
    }

    private static Button NavButton(string label) => new() {
        Text = label, Dock = DockStyle.Fill, Margin = new Padding(2),
        FlatStyle = FlatStyle.Flat, ForeColor = Color.White,
        BackColor = Color.FromArgb(6, 66, 76)
    };

    private void Navigate()
    {
        var value = address.Text.Trim();
        if (!value.Contains("://", StringComparison.Ordinal))
            value = "https://" + value;
        if (Program.IsSafeUrl(value) && browser.CoreWebView2 is not null)
            browser.CoreWebView2.Navigate(value);
        else
            status.Text = "Bitte eine gültige HTTP(S)-Adresse eingeben.";
    }
}
