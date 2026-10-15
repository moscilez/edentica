$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$siteUrl = 'http://localhost:3000'
try {
    $response = Invoke-RestMethod -Uri "$siteUrl/api/health" -TimeoutSec 3
    if ($response.service -eq 'edentica') {
        Write-Host "Edentica уже работает: $siteUrl"
        exit 0
    }
} catch {}
$listener = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw 'Порт 3000 уже занят. Проверьте процесс вручную; этот скрипт не останавливает существующие процессы.'
}
$nodePath = (Get-Command node.exe).Source
$dataPath = Join-Path $projectPath 'data'
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputPath = Join-Path $dataPath "server-$stamp.log"
$errorPath = Join-Path $dataPath "server-$stamp-error.log"
$serverProcess = Start-Process -FilePath $nodePath -ArgumentList 'server.mjs' -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput $outputPath -RedirectStandardError $errorPath -PassThru
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($serverProcess.HasExited) { throw "Сервер завершился. Проверьте $errorPath" }
    try {
        $response = Invoke-RestMethod -Uri "$siteUrl/api/health" -TimeoutSec 1
        if ($response.service -eq 'edentica') {
            Write-Host "Edentica запущена: $siteUrl (PID $($serverProcess.Id))"
            Write-Host "Журналы: $outputPath и $errorPath"
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 250
}
throw "Сервер не подтвердил готовность. Проверьте $errorPath"
