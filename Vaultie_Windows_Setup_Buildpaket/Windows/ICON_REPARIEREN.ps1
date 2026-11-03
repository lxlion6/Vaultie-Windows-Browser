$ErrorActionPreference = 'Stop'
$target = Join-Path $env:LOCALAPPDATA 'Programs\Vaultie'
$exe = Join-Path $target 'Vaultie.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Vaultie.exe nicht gefunden unter: $exe. Erst Vaultie installieren."
}
$possible = @(
    (Join-Path $target '_internal\assets\vaultie-1.5.ico'),
    (Join-Path $target '_internal\assets\vaultie.ico'),
    (Join-Path $target 'assets\vaultie-1.5.ico'),
    (Join-Path $target 'assets\vaultie.ico')
)
$icon = $possible | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $icon) { throw 'Die Vaultie-Symboldatei fehlt. Fuehre INSTALLIEREN.bat aus der Version 1.6 aus.' }
$iconDir = Join-Path $env:LOCALAPPDATA 'Vaultie\Icons'
New-Item -ItemType Directory -Force -Path $iconDir | Out-Null
$iconFile = Join-Path $iconDir 'Vaultie_1_6.ico'
Copy-Item -LiteralPath $icon -Destination $iconFile -Force
$wsh = New-Object -ComObject WScript.Shell
$folders = @([Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('Programs'))
foreach ($folder in $folders) {
    if (-not $folder) { continue }
    $link = Join-Path $folder 'Vaultie.lnk'
    $shortcut = $wsh.CreateShortcut($link)
    $shortcut.TargetPath = $exe
    $shortcut.WorkingDirectory = $target
    $shortcut.IconLocation = "$iconFile,0"
    $shortcut.Description = 'Vaultie - privater Browser'
    $shortcut.Save()
    Write-Host "Verknuepfung aktualisiert: $link"
}
try {
    Add-Type -Namespace VaultieNative -Name Shell -MemberDefinition '[System.Runtime.InteropServices.DllImport("shell32.dll")] public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);'
    [VaultieNative.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
} catch { Write-Host 'Windows konnte die Icon-Anzeige nicht sofort aktualisieren.' }
Write-Host 'Fertig: Vaultie-Symbol repariert.'
