$ErrorActionPreference = 'Stop'
$cfRoot = Split-Path -Parent $PSScriptRoot
$cfPython = Join-Path $cfRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $cfPython)) { throw '请先按README安装Python环境和依赖。' }
$cfLocalAiInfo = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'LocalAI/installation.json'
if (Test-Path -LiteralPath $cfLocalAiInfo) {
    try { & (Join-Path $PSScriptRoot 'start_local_ai.ps1') } catch { Write-Warning '本地AI未启动；职航其他功能仍可使用。请查看本地AI启动入口。' }
}
try { $cfHealth = Invoke-RestMethod 'http://127.0.0.1:8769/api/health' -TimeoutSec 2; if ($cfHealth.version) { Write-Output '职航已运行：http://127.0.0.1:8769'; exit 0 } } catch { }
$cfData = Join-Path $cfRoot 'data'
New-Item -ItemType Directory -Force -Path $cfData | Out-Null
$cfProcess = Start-Process -FilePath $cfPython -ArgumentList @('-m','uvicorn','careerflow.app:app','--host','127.0.0.1','--port','8769') -WorkingDirectory $cfRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cfData 'server.stdout.log') -RedirectStandardError (Join-Path $cfData 'server.stderr.log') -PassThru
$cfProcess.Id | Set-Content -LiteralPath (Join-Path $cfData 'server.pid')
for ($cfAttempt=0;$cfAttempt -lt 20;$cfAttempt++) { Start-Sleep -Seconds 1; try { $cfHealth = Invoke-RestMethod 'http://127.0.0.1:8769/api/health' -TimeoutSec 2; if ($cfHealth.ok) { Write-Output '职航已启动：http://127.0.0.1:8769'; exit 0 } } catch { } }
throw '启动未完成，请查看data/server.stderr.log。'
