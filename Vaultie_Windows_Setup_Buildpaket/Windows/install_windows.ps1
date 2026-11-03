param([string]$BuildSource)
$ErrorActionPreference = 'Stop'
$source = $BuildSource
if (-not $source) { throw 'BuildSource fehlt.' }
$exe = Join-Path $source 'Vaultie.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Build fehlt: $exe" }

# Install for current user only; no admin rights or Program Files required.
$target = Join-Path $env:LOCALAPPDATA 'Programs\Vaultie'
$parent = Split-Path -Parent $target
New-Item -ItemType Directory -Path $parent -Force | Out-Null

# Updating an existing installation while it is running can fail. Abort safely.
if (Get-Process -Name 'Vaultie','PrivatBrowser' -ErrorAction SilentlyContinue) {
    throw 'Vaultie oder PrivatBrowser vor der Installation schliessen.'
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
# Copy all built executable and dependency folders.
Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
}
$installedExe = Join-Path $target 'Vaultie.exe'
if (-not (Test-Path -LiteralPath $installedExe)) { throw 'Installierte EXE fehlt.' }

# The PyInstaller onedir default stores --add-data files in _internal/assets.
# Copy the actual icon into a stable location outside the PyInstaller runtime tree.
$iconCandidates = @(
    (Join-Path $target '_internal\assets\vaultie-1.5.ico'),
    (Join-Path $target '_internal\assets\vaultie.ico'),
    (Join-Path $target 'assets\vaultie-1.5.ico'),
    (Join-Path $target 'assets\vaultie.ico')
)
$sourceIcon = $iconCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$iconLocation = "$installedExe,0"
if ($sourceIcon) {
    $iconFolder = Join-Path $env:LOCALAPPDATA 'Vaultie\Icons'
    New-Item -ItemType Directory -Path $iconFolder -Force | Out-Null
    $fixedIcon = Join-Path $iconFolder 'Vaultie_1_6.ico'
    Copy-Item -LiteralPath $sourceIcon -Destination $fixedIcon -Force
    $iconLocation = "$fixedIcon,0"
} else {
    Write-Host 'WARNUNG: Keine ICO-Datei im Build gefunden. Das EXE-Icon wird verwendet.'
}

$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktop) { throw 'Windows-Desktopordner konnte nicht ermittelt werden.' }
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut((Join-Path $desktop 'Vaultie.lnk'))
$shortcut.TargetPath = $installedExe
$shortcut.WorkingDirectory = $target
$shortcut.IconLocation = $iconLocation
$shortcut.Description = 'Vaultie - privater Browser'
$shortcut.Save()

$start = [Environment]::GetFolderPath('Programs')
if ($start) {
    $startShortcut = $wsh.CreateShortcut((Join-Path $start 'Vaultie.lnk'))
    $startShortcut.TargetPath = $installedExe
    $startShortcut.WorkingDirectory = $target
    $startShortcut.IconLocation = $iconLocation
    $startShortcut.Save()
}
# Ask Windows Explorer to refresh icons and shortcuts.
try {
    Add-Type -Namespace Native -Name Shell -MemberDefinition '[System.Runtime.InteropServices.DllImport("shell32.dll")] public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);'
    [Native.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
} catch { Write-Host 'Icon-Cache-Aktualisierung konnte nicht angefordert werden.' }
Write-Host "Installiert unter: $target"
Write-Host "Desktop-Verknuepfung: $desktop\Vaultie.lnk"
Write-Host 'Bisherige Browserdaten bleiben im bestehenden lokalen PrivatBrowser-AppData-Profil.'

# Legacy shortcut entfernen, sofern von unserer alten Installation erzeugt.
foreach ($folder in @($desktop, $start)) {
    if (-not $folder) { continue }
    $oldShortcut = Join-Path $folder 'PrivatBrowser.lnk'
    if (Test-Path -LiteralPath $oldShortcut) {
        $old = $wsh.CreateShortcut($oldShortcut)
        if ($old.TargetPath -like '*\Programs\PrivatBrowser\PrivatBrowser.exe') {
            Remove-Item -LiteralPath $oldShortcut -Force
        }
    }
}
