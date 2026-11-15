$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $PSScriptRoot
$installerPath = Join-Path $projectPath "scripts\install_docker_schedule.ps1"
$permanentName = "RutenFeeDockerWorker-DefinitionTest"
$oneTimeName = "RutenFeeDockerWorker-OneTimeDefinitionTest"

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

    Invoke-Installer @("-TaskName", $permanentName, "-ProjectPath", $projectPath)
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
    Assert-True ($permanent.Actions[0].Arguments -notmatch "-DryRun") "production action is not dry-run"

    $oneTimeAt = (Get-Date).AddDays(1)
    Invoke-Installer @(
        "-TaskName", $oneTimeName,
        "-ProjectPath", $projectPath,
        "-OneTimeAt", $oneTimeAt.ToString("o"),
        "-DryRun"
    )
    $oneTime = Get-ScheduledTask -TaskName $oneTimeName
    Assert-True ($oneTime.Triggers.Count -eq 1) "test task has one trigger"
    Assert-True ($oneTime.Actions[0].Arguments -match "-DryRun") "test action is harmless dry-run"
    Assert-True ($oneTime.Actions[0].Arguments -notmatch "(?i)OTP|token|cookie|card_safe|card_n") `
        "task action contains no secret-bearing argument"

    Write-Host "INSTALLER_TESTS_OK"
} finally {
    Remove-TestTask $permanentName
    Remove-TestTask $oneTimeName
}
