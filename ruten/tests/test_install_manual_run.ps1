$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $project "scripts\install_manual_run.ps1"
$name = "RutenFeeHostManual-DefinitionTest"
$python = (Get-Command python -ErrorAction Stop).Source
function Assert-True { param([bool]$c, [string]$m) if (-not $c) { throw "Assertion failed: $m" } }
function Remove-Test { if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $name -Confirm:$false } }
try {
    Remove-Test
    foreach ($i in 1..2) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -TaskName $name -PythonPath $python | Out-Null
        Assert-True ($LASTEXITCODE -eq 0) "installer run $i succeeds"
    }
    $tasks = @(Get-ScheduledTask -TaskName $name)
    Assert-True ($tasks.Count -eq 1) "repeat install leaves exactly one task"
    $t = $tasks[0]
    Assert-True (@($t.Triggers | Where-Object { $_ }).Count -eq 0) "manual task has no triggers"
    Assert-True ($t.Actions[0].Arguments -match "run_fee_host\.ps1" -and $t.Actions[0].Arguments -match "-Manual") "task runs run_fee_host.ps1 -Manual"
    Assert-True ($t.Settings.MultipleInstances -eq "IgnoreNew") "overlapping manual starts are ignored"
    Write-Host "INSTALL_MANUAL_TESTS_OK"
} finally { Remove-Test }
