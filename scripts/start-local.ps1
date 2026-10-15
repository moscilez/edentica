$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$siteUrl = 'http://localhost:3000'
$nodePath = (Get-Command node.exe).Source
function Test-EdenticaHealth {
    & $nodePath (Join-Path $PSScriptRoot 'health.mjs') $siteUrl
    return $LASTEXITCODE -eq 0
}
try {
    if (Test-EdenticaHealth) {
        Write-Host "Edentica уже работает: $siteUrl"
        exit 0
    }
} catch {}
$listener = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw 'Порт 3000 уже занят. Проверьте процесс вручную; этот скрипт не останавливает существующие процессы.'
}
$dataPath = Join-Path $projectPath 'data'
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputPath = Join-Path $dataPath "server-$stamp.log"
$errorPath = Join-Path $dataPath "server-$stamp-error.log"
$serverProcess = Start-Process -FilePath $nodePath -ArgumentList 'server.mjs' -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput $outputPath -RedirectStandardError $errorPath -PassThru
Write-Host "Edentica: процесс $($serverProcess.Id) запускается"
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($serverProcess.HasExited) { throw "Сервер завершился. Проверьте $errorPath" }
    try {
        if (Test-EdenticaHealth) {
            Write-Host "Edentica запущена: $siteUrl (PID $($serverProcess.Id))"
            Write-Host "Журналы: $outputPath и $errorPath"
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 250
}
throw "Сервер не подтвердил готовность. Проверьте $errorPath"
