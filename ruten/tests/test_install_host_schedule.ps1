$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $PSScriptRoot
$installerPath = Join-Path $projectPath "scripts\install_host_schedule.ps1"
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$permanentName = "RutenFeeHostWorker-DefinitionTest"
$oneTimeName = "RutenFeeHostWorker-OneTimeDefinitionTest"
$immediateName = "RutenFeeHostWorker-ImmediateDefinitionTest"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "Assertion failed: $Message"
    }
}

function Remove-TestTask {
    param([string]$TaskName)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}

function Invoke-Installer {
    param([string[]]$Arguments)
    $output = & powershell.exe `
        -NoProfile `
        -NonInteractive `
        -ExecutionPolicy Bypass `
        -File $installerPath `
        @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "Installer exited with $exitCode."
    }
}

try {
    Remove-TestTask $permanentName
    Remove-TestTask $oneTimeName
    Remove-TestTask $immediateName

    Invoke-Installer @(
        "-TaskName", $permanentName,
        "-ProjectPath", $projectPath,
        "-PythonPath", $pythonPath
    )
    $permanent = Get-ScheduledTask -TaskName $permanentName
    Assert-True ($permanent.Triggers.Count -eq 5) "permanent task has five triggers"
    $times = @($permanent.Triggers | ForEach-Object {
        ([datetime]$_.StartBoundary).ToString("HH:mm")
    })
    Assert-True (($times -join ",") -eq "01:35,02:00,02:14,02:31,02:40") `
        "permanent trigger times match the approved UTC+8 slots"
    Assert-True ($permanent.Settings.StartWhenAvailable) "StartWhenAvailable is enabled"
    Assert-True ($permanent.Settings.MultipleInstances -eq "IgnoreNew") "overlap is ignored"
    Assert-True ($permanent.Settings.ExecutionTimeLimit -eq "PT20M") "task limit is 20 minutes"
    Assert-True ($permanent.Settings.RunOnlyIfNetworkAvailable) "network is required"
    Assert-True (-not $permanent.Settings.DisallowStartIfOnBatteries) `
        "task can start while the laptop uses battery power"
    Assert-True (-not $permanent.Settings.StopIfGoingOnBatteries) `
        "running worker is not stopped when AC power is disconnected"
    Assert-True ($permanent.Principal.LogonType -eq "Interactive") "interactive user owns task"
    Assert-True ($permanent.Principal.RunLevel -eq "Limited") "task is not elevated"
    Assert-True ($permanent.Actions.Count -eq 1) "task has one action"
    Assert-True ($permanent.Actions[0].Arguments -match "run_fee_host\.ps1") `
        "production action uses the host supervisor"
    Assert-True ($permanent.Actions[0].Arguments -match [regex]::Escape($pythonPath)) `
        "production action pins the approved Python executable"
    Assert-True ($permanent.Actions[0].Arguments -notmatch "(?i)Docker|DryRun|BrowserSmoke") `
        "production action is a host payment run"

    $oneTimeAt = (Get-Date).AddDays(1)
    Invoke-Installer @(
        "-TaskName", $oneTimeName,
        "-ProjectPath", $projectPath,
        "-PythonPath", $pythonPath,
        "-OneTimeAt", $oneTimeAt.ToString("o"),
        "-BrowserSmoke",
        "-BrowserSmokeSeconds", "1"
    )
    $oneTime = Get-ScheduledTask -TaskName $oneTimeName
    Assert-True ($oneTime.Triggers.Count -eq 1) "test task has one trigger"
    Assert-True ($oneTime.Actions[0].Arguments -match "-BrowserSmoke") `
        "test action opens only the harmless browser smoke"
    Assert-True ($oneTime.Actions[0].Arguments -notmatch "(?i)OTP|token|cookie|card_safe|card_n") `
        "task action contains no secret-bearing argument"

    Invoke-Installer @(
        "-TaskName", $immediateName,
        "-ProjectPath", $projectPath,
        "-PythonPath", $pythonPath,
        "-OneTimeAt", $oneTimeAt.AddMinutes(1).ToString("o"),
        "-ImmediatePayment"
    )
    $immediate = Get-ScheduledTask -TaskName $immediateName
    Assert-True ($immediate.Triggers.Count -eq 1) "immediate payment task has one trigger"
    Assert-True ($immediate.Actions[0].Arguments -match "-ImmediatePayment") `
        "immediate payment task bypasses only the schedule slot gate"
    Assert-True ($immediate.Actions[0].Arguments -notmatch "(?i)DryRun|BrowserSmoke") `
        "immediate payment action is not a test mode"
    Assert-True ($immediate.Actions[0].Arguments -notmatch "(?i)OTP|token|cookie|card_safe|card_n") `
        "immediate payment action contains no secret-bearing argument"

    Write-Host "HOST_INSTALLER_TESTS_OK"
} finally {
    Remove-TestTask $permanentName
    Remove-TestTask $oneTimeName
    Remove-TestTask $immediateName
}
