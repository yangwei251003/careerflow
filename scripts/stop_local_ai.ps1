$ErrorActionPreference = 'Stop'
$localAiRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'LocalAI'
$localAiPidFile = Join-Path $localAiRoot 'server.pid'
if (!(Test-Path -LiteralPath $localAiPidFile)) { Write-Output 'No managed Local AI process.'; return }
$localAiPid = [int](Get-Content -LiteralPath $localAiPidFile)
$localAiConfig = Get-Content -Raw -LiteralPath (Join-Path $localAiRoot 'installation.json') | ConvertFrom-Json
$localAiProc = Get-CimInstance Win32_Process -Filter "ProcessId = $localAiPid"
if ($localAiProc) {
    if ($localAiProc.ExecutablePath -ne $localAiConfig.binary -or $localAiProc.CommandLine -notmatch '\bserve\b') { throw 'Process identity mismatch; nothing stopped.' }
    try {
        $localAiLoaded = Invoke-RestMethod 'http://127.0.0.1:11434/api/ps' -TimeoutSec 3
        foreach ($localAiModel in $localAiLoaded.models) {
            $localAiBody = @{model=$localAiModel.name; keep_alive=0} | ConvertTo-Json
            Invoke-RestMethod 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body $localAiBody -TimeoutSec 10 | Out-Null
        }
    } catch { }
    Stop-Process -Id $localAiPid
}
Remove-Item -LiteralPath $localAiPidFile
Write-Output 'Managed Local AI stopped.'
