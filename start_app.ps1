$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeNode = 'C:\Users\chris\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'
$runtimeTools = 'C:\Users\chris\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback'

$apiCommand = "Set-Location -LiteralPath '$projectRoot'; `$env:PYTHONPATH='src'; python -u -m spy_macro_data.web_api"
$webCommand = "Set-Location -LiteralPath '$projectRoot\web'; `$env:Path='$runtimeNode;$runtimeTools;' + `$env:Path; pnpm run dev"
$snapshotCommand = "Set-Location -LiteralPath '$projectRoot'; `$env:PYTHONPATH='src'; python -u -m spy_macro_data.cli snapshot --interval 60"

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $apiCommand
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $webCommand
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $snapshotCommand

Write-Output 'SPY Field Notes is starting at http://localhost:3000'
Write-Output 'Allow a few seconds for the page to become available.'
