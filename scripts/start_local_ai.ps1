$ErrorActionPreference = 'Stop'
$localAiRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'LocalAI'
$localAiInfo = Join-Path $localAiRoot 'installation.json'
try {
    $localAiHealth = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
    if ($localAiHealth.version) { Write-Output ('Local AI is running: Ollama ' + $localAiHealth.version); return }
} catch { }
if (!(Test-Path -LiteralPath $localAiInfo)) { throw 'Install Ollama first. See docs/LOCAL_AI.md.' }
$localAiConfig = Get-Content -Raw -LiteralPath $localAiInfo | ConvertFrom-Json
if (!(Test-Path -LiteralPath $localAiConfig.binary)) { throw 'Ollama executable is missing.' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = $localAiConfig.models
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_KEEP_ALIVE = '2m'
$env:OLLAMA_VULKAN = '0'
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:GGML_VK_VISIBLE_DEVICES = '-1'
$localAiProc = Start-Process -FilePath $localAiConfig.binary -ArgumentList 'serve' -WorkingDirectory $localAiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $localAiRoot 'server.stdout.log') -RedirectStandardError (Join-Path $localAiRoot 'server.stderr.log') -PassThru
$localAiProc.Id | Set-Content -LiteralPath (Join-Path $localAiRoot 'server.pid')
try { $localAiProc.PriorityClass = 'BelowNormal' } catch { }
for ($localAiAttempt=0; $localAiAttempt -lt 15; $localAiAttempt++) {
    Start-Sleep -Seconds 1
    try { $localAiHealth = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2; if ($localAiHealth.version) { Write-Output ('Local AI started: Ollama ' + $localAiHealth.version); return } } catch { }
}
throw 'Local AI did not start. Check Documents/LocalAI/server.stderr.log.'
