$ErrorActionPreference = 'Stop'
$cfRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$cfPidFile = Join-Path $cfRoot 'data/server.pid'
if (!(Test-Path -LiteralPath $cfPidFile)) { Write-Output '没有本项目启动记录。'; exit 0 }
$cfParentId = [int](Get-Content -LiteralPath $cfPidFile)
$cfParent = Get-CimInstance Win32_Process -Filter "ProcessId=$cfParentId"
if (!$cfParent -or !$cfParent.CommandLine.Contains($cfRoot) -or $cfParent.CommandLine -notmatch 'careerflow\.app:app') { throw '启动记录对应进程已变化，未停止任何其他程序。' }
$cfChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$cfParentId" | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'careerflow\.app:app' }
foreach ($cfChild in $cfChildren) { Stop-Process -Id $cfChild.ProcessId }
Stop-Process -Id $cfParentId -ErrorAction SilentlyContinue
Write-Output '职航本机服务已停止。定时采集和邮件监听随之停止，数据已保留。'
