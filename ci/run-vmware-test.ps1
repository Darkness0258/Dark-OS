#Requires -Version 7.2
<#
.SYNOPSIS
Build-independent VMware Workstation live-ISO and Phase 3 verification.

.DESCRIPTION
Creates a fresh EFI VM, forces CD/ISO boot, captures fresh boot evidence,
waits for VMware Tools and the DarkOS desktop, copies the committed guest
verifier into the live session, runs fail-closed Phase 3 assertions, captures
two real context-highlight scenarios, collects guest journals, and powers the
test VM off in a finally block.

This script deliberately does not build the ISO and does not automate a
Calamares installation. Pass only an ISO already produced and verified by
build-iso.sh. The VM directory and all evidence are preserved after shutdown.

.EXAMPLE
pwsh -File ci/run-vmware-test.ps1 -IsoPath .\out\darkos.iso
#>

[CmdletBinding()]
param(
    [string]$IsoPath = "",
    [string]$VmDir = "",
    [string]$VmrunPath = "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    [string]$VDiskManagerPath = "C:\Program Files (x86)\VMware\VMware Workstation\vmware-vdiskmanager.exe",
    [string]$GuestVerifierPath = "",
    [string]$GuestUser = "darkos",
    [string]$GuestPassword = "",
    [string]$GroqApiKey = "",
    [string]$OpenRouterApiKey = "",
    [ValidateRange(30, 900)]
    [int]$ToolsTimeoutSeconds = 300,
    [ValidateRange(15, 300)]
    [int]$GuestAuthTimeoutSeconds = 60,
    [ValidateSet("gui", "nogui")]
    [string]$StartMode = "gui"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($IsoPath)) {
    $IsoPath = Join-Path $repoRoot "out\darkos.iso"
}
if ([string]::IsNullOrWhiteSpace($GuestVerifierPath)) {
    $GuestVerifierPath = Join-Path $PSScriptRoot "vmware-phase3-guest.sh"
}
if ([string]::IsNullOrWhiteSpace($VmDir)) {
    $vmBase = if (Test-Path -LiteralPath "D:\Virtual Machines" -PathType Container) {
        "D:\Virtual Machines"
    } else {
        Join-Path ([IO.Path]::GetTempPath()) "DarkOS-VMware"
    }
    $suffix = "{0}-{1}-{2}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID, ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $VmDir = Join-Path $vmBase "DarkOS-Test-$suffix"
}

$script:VmStarted = $false
$script:GuestOperationsReady = $false
$script:GuestVerifierCopied = $false
$script:RunResult = "FAIL"
$script:FailureMessage = "run did not reach its PASS marker"
$script:ScreenshotRecords = [System.Collections.Generic.List[object]]::new()
$script:VmrunPath = $VmrunPath
$script:GuestUser = $GuestUser
$script:GuestPassword = $GuestPassword
$script:VmxPath = ""
$script:EvidenceDir = ""
$script:ScreenshotDir = ""
$script:GuestVerifierGuestPath = "/tmp/darkos-vmware-phase3-guest.sh"

function Convert-NativeOutput {
    param([object[]]$Lines)
    return (($Lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$Description = "native command",
        [switch]$AllowFailure,
        [switch]$EchoOutput
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $captured = @(& $FilePath @ArgumentList 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $output = Convert-NativeOutput -Lines $captured
    if ($EchoOutput -and -not [string]::IsNullOrWhiteSpace($output)) {
        Write-Host $output
    }
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode.`n$output"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

function Invoke-Vmrun {
    param(
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$Description = "vmrun command",
        [switch]$AllowFailure,
        [switch]$EchoOutput
    )
    return Invoke-NativeCommand -FilePath $script:VmrunPath `
        -ArgumentList (@("-T", "ws") + $ArgumentList) -Description $Description `
        -AllowFailure:$AllowFailure -EchoOutput:$EchoOutput
}

function Invoke-GuestVmrun {
    param(
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$Description = "authenticated vmrun guest command",
        [switch]$AllowFailure,
        [switch]$EchoOutput
    )
    $auth = @("-gu", $script:GuestUser, "-gp", $script:GuestPassword)
    return Invoke-Vmrun -ArgumentList ($auth + $ArgumentList) -Description $Description `
        -AllowFailure:$AllowFailure -EchoOutput:$EchoOutput
}

function Assert-ExistingFile {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Description)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description does not exist: $Path"
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -le 0) {
        throw "$Description is empty: $Path"
    }
    return $item
}

function Assert-SafeVmxValue {
    param([Parameter(Mandatory)][string]$Value, [Parameter(Mandatory)][string]$Description)
    if ($Value.IndexOf('"') -ge 0 -or $Value.Contains("`r") -or $Value.Contains("`n")) {
        throw "$Description contains a character that cannot be safely encoded in a VMX file."
    }
}

function Initialize-FreshVmDirectory {
    param([Parameter(Mandatory)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    $rootPath = [IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.TrimEnd('\', '/') -eq $rootPath.TrimEnd('\', '/')) {
        throw "Refusing to use a filesystem root as the VMware test directory: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) {
            throw "VM target exists but is not a directory: $fullPath"
        }
        $existing = @(Get-ChildItem -LiteralPath $fullPath -Force)
        if ($existing.Count -ne 0) {
            $sample = ($existing | Select-Object -First 5 -ExpandProperty Name) -join ", "
            throw "Refusing non-empty VMware target (stale disk/NVRAM/locks are unsafe): $fullPath [$sample]"
        }
    } else {
        New-Item -ItemType Directory -Path $fullPath | Out-Null
    }
    return $fullPath
}

function Get-RunningVmPaths {
    $result = Invoke-Vmrun -ArgumentList @("list") -Description "list running VMware VMs"
    $lines = @($result.Output -split "`r?`n")
    if ($lines.Count -le 1) { return @() }
    return @($lines | Select-Object -Skip 1 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Test-TestVmRunning {
    if ([string]::IsNullOrWhiteSpace($script:VmxPath)) { return $false }
    $expected = [IO.Path]::GetFullPath($script:VmxPath)
    foreach ($running in @(Get-RunningVmPaths)) {
        try {
            if ([IO.Path]::GetFullPath($running).Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        } catch { }
    }
    return $false
}

function Assert-PathWithinDirectory {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Directory)
    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullDirectory = [IO.Path]::GetFullPath($Directory).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($fullDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes its intended evidence directory: $fullPath"
    }
    return $fullPath
}

function Capture-FreshScreenshot {
    param([Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9._-]+$')][string]$Name)

    if (-not (Test-TestVmRunning)) {
        throw "Cannot capture '$Name': the test VM is not running."
    }
    $fullPath = Assert-PathWithinDirectory -Path (Join-Path $script:ScreenshotDir "$Name.png") `
        -Directory $script:ScreenshotDir
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Force
    }
    $startedUtc = [DateTime]::UtcNow
    Write-Host "==> Capturing fresh screenshot: $Name"
    $capture = if ($script:GuestOperationsReady) {
        Invoke-GuestVmrun -ArgumentList @("captureScreen", $script:VmxPath, $fullPath) `
            -Description "capture screenshot '$Name'" -AllowFailure
    } else {
        Invoke-Vmrun -ArgumentList @("captureScreen", $script:VmxPath, $fullPath) `
            -Description "capture screenshot '$Name'" -AllowFailure
    }
    if ($capture.ExitCode -ne 0) {
        Write-Warning "vmrun returned nonzero capture status for '$Name': $($capture.Output)"
        return $null
    }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "vmrun reported success but did not create screenshot '$fullPath'."
    }
    $file = Get-Item -LiteralPath $fullPath
    if ($file.Length -lt 1024) {
        throw "Screenshot '$fullPath' is implausibly small ($($file.Length) bytes)."
    }
    if ($file.LastWriteTimeUtc -lt $startedUtc.AddSeconds(-1)) {
        throw "Screenshot '$fullPath' was not freshly written by this capture call."
    }
    $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
    $record = [pscustomobject]@{
        Name = $Name
        Path = $fullPath
        Bytes = $file.Length
        CapturedUtc = $file.LastWriteTimeUtc.ToString("o")
        Sha256 = $hash
    }
    $script:ScreenshotRecords.Add($record)
    Write-Host "    $($file.Length) bytes, SHA256 $hash"
    return $record
}

function Wait-ForVmwareTools {
    param([int]$TimeoutSeconds)

    Write-Host "==> Waiting up to ${TimeoutSeconds}s for VMware Tools..."
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $nextProgressCapture = [DateTime]::UtcNow.AddSeconds(20)
    $progressIndex = 1
    $lastState = ""
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Test-TestVmRunning)) {
            throw "The VM powered off before VMware Tools became ready."
        }
        $probe = Invoke-Vmrun -ArgumentList @("checkToolsState", $script:VmxPath) `
            -Description "check VMware Tools state" -AllowFailure
        $lastState = $probe.Output
        if ($probe.ExitCode -eq 0 -and $probe.Output -match '(?im)^running\s*$') {
            Write-Host "    VMware Tools state: running"
            return
        }
        if ([DateTime]::UtcNow -ge $nextProgressCapture) {
            try {
                Capture-FreshScreenshot -Name ("05-readiness-{0:D2}" -f $progressIndex) | Out-Null
            } catch {
                Write-Warning "Readiness screenshot failed: $($_.Exception.Message)"
            }
            $progressIndex++
            $nextProgressCapture = [DateTime]::UtcNow.AddSeconds(20)
        }
        Start-Sleep -Seconds 5
    }
    throw "VMware Tools did not reach 'running' within ${TimeoutSeconds}s. Last state: $lastState. Ensure vmtoolsd.service is enabled in the ISO."
}

function Wait-ForGuestAuthentication {
    param([int]$TimeoutSeconds)

    Write-Host "==> Waiting up to ${TimeoutSeconds}s for authenticated guest operations..."
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastOutput = ""
    while ([DateTime]::UtcNow -lt $deadline) {
        $probe = Invoke-GuestVmrun -ArgumentList @(
            "runProgramInGuest", $script:VmxPath, "/usr/bin/true"
        ) -Description "probe authenticated guest command" -AllowFailure
        $lastOutput = $probe.Output
        if ($probe.ExitCode -eq 0) {
            $script:GuestOperationsReady = $true
            Write-Host "    Authenticated VIX guest operations are ready."
            return
        }
        Start-Sleep -Seconds 3
    }
    throw "VMware Tools is running, but guest authentication for '$($script:GuestUser)' failed for ${TimeoutSeconds}s. Last vmrun output: $lastOutput"
}

function Copy-GuestFileToHost {
    param(
        [Parameter(Mandatory)][string]$GuestPath,
        [Parameter(Mandatory)][string]$HostPath,
        [Parameter(Mandatory)][string]$Description,
        [switch]$AllowFailure
    )

    $fullHostPath = Assert-PathWithinDirectory -Path $HostPath -Directory $script:EvidenceDir
    if (Test-Path -LiteralPath $fullHostPath) {
        Remove-Item -LiteralPath $fullHostPath -Force
    }
    $copy = Invoke-GuestVmrun -ArgumentList @(
        "CopyFileFromGuestToHost", $script:VmxPath, $GuestPath, $fullHostPath
    ) -Description $Description -AllowFailure:$AllowFailure
    return [pscustomobject]@{
        Result = $copy
        HostPath = $fullHostPath
        Exists = (Test-Path -LiteralPath $fullHostPath -PathType Leaf)
    }
}

function Invoke-GuestMode {
    param(
        [Parameter(Mandatory)][ValidatePattern('^[a-z-]+$')][string]$Mode,
        [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9._-]+$')][string]$EvidenceName,
        [string[]]$ModeArguments = @()
    )

    if (-not $script:GuestVerifierCopied) {
        throw "Guest verifier has not been copied into the VM."
    }
    $guestLog = "/tmp/darkos-vmware-${EvidenceName}.log"
    $guestStatus = "${guestLog}.status"
    $hostLog = Join-Path $script:EvidenceDir "guest-${EvidenceName}.log"
    $hostStatus = Join-Path $script:EvidenceDir "guest-${EvidenceName}.status"
    $arguments = @(
        "runProgramInGuest", $script:VmxPath,
        "/bin/bash", $script:GuestVerifierGuestPath,
        $Mode, $guestLog
    ) + $ModeArguments

    Write-Host "==> Running guest verification mode: $Mode $($ModeArguments -join ' ')"
    $run = Invoke-GuestVmrun -ArgumentList $arguments `
        -Description "run guest verifier mode '$Mode'" -AllowFailure
    $logCopy = Copy-GuestFileToHost -GuestPath $guestLog -HostPath $hostLog `
        -Description "collect guest '$Mode' log" -AllowFailure
    $statusCopy = Copy-GuestFileToHost -GuestPath $guestStatus -HostPath $hostStatus `
        -Description "collect guest '$Mode' status" -AllowFailure

    $logText = if ($logCopy.Exists) { Get-Content -Raw -LiteralPath $logCopy.HostPath } else { "" }
    $statusText = if ($statusCopy.Exists) { Get-Content -Raw -LiteralPath $statusCopy.HostPath } else { "" }
    if (-not [string]::IsNullOrWhiteSpace($logText)) {
        Write-Host $logText.TrimEnd()
    }
    if ($run.ExitCode -ne 0) {
        throw "Guest verifier mode '$Mode' failed through vmrun (exit $($run.ExitCode)).`n$($run.Output)`n$statusText"
    }
    if (-not $logCopy.Exists -or -not $statusCopy.Exists) {
        throw "Guest verifier mode '$Mode' did not produce both its log and status evidence."
    }
    if ($statusText -notmatch '(?m)^RESULT=PASS\s*$' -or $statusText -notmatch '(?m)^EXIT_CODE=0\s*$') {
        throw "Guest verifier mode '$Mode' did not report a fail-closed PASS.`n$statusText"
    }
    return [pscustomobject]@{
        Mode = $Mode
        EvidenceName = $EvidenceName
        LogPath = $logCopy.HostPath
        StatusPath = $statusCopy.HostPath
        Status = $statusText.Trim()
    }
}

function Write-EvidenceManifests {
    param(
        [Parameter(Mandatory)][hashtable]$Metadata,
        [Parameter(Mandatory)][string]$Result,
        [string]$Failure = ""
    )

    if ([string]::IsNullOrWhiteSpace($script:EvidenceDir) -or -not (Test-Path -LiteralPath $script:EvidenceDir)) {
        return
    }
    $Metadata["Result"] = $Result
    $Metadata["Failure"] = $Failure
    $Metadata["FinishedUtc"] = [DateTime]::UtcNow.ToString("o")
    $Metadata["ScreenshotCount"] = $script:ScreenshotRecords.Count
    $Metadata | ConvertTo-Json -Depth 6 | Set-Content `
        -LiteralPath (Join-Path $script:EvidenceDir "run-metadata.json") -Encoding utf8NoBOM
    $screenshotJson = if ($script:ScreenshotRecords.Count -eq 0) {
        "[]"
    } else {
        @($script:ScreenshotRecords) | ConvertTo-Json -Depth 5 -AsArray
    }
    Set-Content -LiteralPath (Join-Path $script:EvidenceDir "screenshots.json") `
        -Value $screenshotJson -Encoding utf8NoBOM
}

function Stop-TestVm {
    if (-not (Test-TestVmRunning)) {
        $script:VmStarted = $false
        return
    }

    Write-Host "==> Powering off the test VM..."
    if ($script:GuestOperationsReady) {
        Invoke-GuestVmrun -ArgumentList @(
            "runProgramInGuest", $script:VmxPath, "-noWait",
            "/usr/bin/sudo", "-n", "/usr/bin/systemctl", "poweroff"
        ) -Description "request guest poweroff" -AllowFailure | Out-Null
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline -and (Test-TestVmRunning)) {
        Start-Sleep -Seconds 3
    }
    if (Test-TestVmRunning) {
        Invoke-Vmrun -ArgumentList @("stop", $script:VmxPath, "soft") `
            -Description "soft-stop VMware test VM" -AllowFailure | Out-Null
        $deadline = [DateTime]::UtcNow.AddSeconds(20)
        while ([DateTime]::UtcNow -lt $deadline -and (Test-TestVmRunning)) {
            Start-Sleep -Seconds 2
        }
    }
    if (Test-TestVmRunning) {
        Write-Warning "Guest and ACPI shutdown timed out; forcing off the disposable test VM."
        Invoke-Vmrun -ArgumentList @("stop", $script:VmxPath, "hard") `
            -Description "hard-stop VMware test VM" | Out-Null
    }
    if (Test-TestVmRunning) {
        throw "VMware test VM is still running after shutdown attempts."
    }
    $script:VmStarted = $false
    Write-Host "    Test VM is powered off."
}

$metadata = @{}

try {
    Write-Host "==> Validating host prerequisites..."
    $isoItem = Assert-ExistingFile -Path $IsoPath -Description "verified DarkOS ISO"
    $verifierItem = Assert-ExistingFile -Path $GuestVerifierPath -Description "VMware guest verifier"
    Assert-ExistingFile -Path $VmrunPath -Description "vmrun executable" | Out-Null
    Assert-ExistingFile -Path $VDiskManagerPath -Description "vmware-vdiskmanager executable" | Out-Null

    $resolvedIso = $isoItem.FullName
    $resolvedVerifier = $verifierItem.FullName
    Assert-SafeVmxValue -Value $resolvedIso -Description "ISO path"
    Assert-SafeVmxValue -Value $VmDir -Description "VM directory"

    $vmrunVersion = (Get-Item -LiteralPath $VmrunPath).VersionInfo.FileVersion
    $vdiskVersion = (Get-Item -LiteralPath $VDiskManagerPath).VersionInfo.FileVersion
    if ([string]::IsNullOrWhiteSpace($vmrunVersion) -or [string]::IsNullOrWhiteSpace($vdiskVersion)) {
        throw "Could not determine VMware command versions."
    }
    Invoke-Vmrun -ArgumentList @("list") -Description "validate vmrun Workstation command" | Out-Null

    $VmDir = Initialize-FreshVmDirectory -Path $VmDir
    $script:VmxPath = Join-Path $VmDir "DarkOS.vmx"
    $script:EvidenceDir = Join-Path $VmDir "evidence"
    $script:ScreenshotDir = Join-Path $script:EvidenceDir "screenshots"
    New-Item -ItemType Directory -Path $script:EvidenceDir | Out-Null
    New-Item -ItemType Directory -Path $script:ScreenshotDir | Out-Null

    $isoHash = (Get-FileHash -LiteralPath $resolvedIso -Algorithm SHA256).Hash
    $verifierHash = (Get-FileHash -LiteralPath $resolvedVerifier -Algorithm SHA256).Hash
    $metadata = @{
        StartedUtc = [DateTime]::UtcNow.ToString("o")
        Host = [Environment]::MachineName
        PowerShell = $PSVersionTable.PSVersion.ToString()
        VmrunVersion = $vmrunVersion
        VDiskManagerVersion = $vdiskVersion
        IsoPath = $resolvedIso
        IsoBytes = $isoItem.Length
        IsoSha256 = $isoHash
        GuestVerifierPath = $resolvedVerifier
        GuestVerifierSha256 = $verifierHash
        VmDirectory = $VmDir
        VmxPath = $script:VmxPath
        StartMode = $StartMode
        GuestUser = $GuestUser
    }
    Write-EvidenceManifests -Metadata $metadata -Result "RUNNING"
    Write-Host "    ISO SHA256: $isoHash"
    Write-Host "    Fresh VM directory: $VmDir"

    $vmdkPath = Join-Path $VmDir "DarkOS-disk.vmdk"
    Write-Host "==> Creating a fresh 40GB split sparse virtual disk..."
    Invoke-NativeCommand -FilePath $VDiskManagerPath -ArgumentList @(
        "-c", "-s", "40GB", "-a", "lsilogic", "-t", "1", $vmdkPath
    ) -Description "create fresh VMware virtual disk" -EchoOutput | Out-Null
    Assert-ExistingFile -Path $vmdkPath -Description "fresh VMDK descriptor" | Out-Null

    $vmxLines = @(
        '.encoding = "windows-1252"',
        'config.version = "8"',
        'virtualHW.version = "21"',
        'virtualHW.productCompatibility = "hosted"',
        'displayName = "DarkOS Phase 3 Fresh ISO Test"',
        'guestOS = "other6xlinux-64"',
        'firmware = "efi"',
        'bios.bootOrder = "cdrom,hdd"',
        'bios.bootDelay = "2000"',
        'msg.autoAnswer = "TRUE"',
        'uuid.action = "create"',
        'memsize = "4096"',
        'numvcpus = "4"',
        'mks.enable3d = "TRUE"',
        'svga.vramSize = "268435456"',
        'pciBridge0.present = "TRUE"',
        'pciBridge4.present = "TRUE"',
        'pciBridge4.virtualDev = "pcieRootPort"',
        'pciBridge4.functions = "8"',
        'pciBridge5.present = "TRUE"',
        'pciBridge5.virtualDev = "pcieRootPort"',
        'pciBridge5.functions = "8"',
        'pciBridge6.present = "TRUE"',
        'pciBridge6.virtualDev = "pcieRootPort"',
        'pciBridge6.functions = "8"',
        'pciBridge7.present = "TRUE"',
        'pciBridge7.virtualDev = "pcieRootPort"',
        'pciBridge7.functions = "8"',
        'vmci0.present = "TRUE"',
        'hpet0.present = "TRUE"',
        'nvram = "DarkOS.nvram"',
        'sata0.present = "TRUE"',
        'sata0:0.present = "TRUE"',
        'sata0:0.fileName = "DarkOS-disk.vmdk"',
        'sata0:0.deviceType = "disk"',
        'sata0:1.present = "TRUE"',
        "sata0:1.fileName = `"$resolvedIso`"",
        'sata0:1.deviceType = "cdrom-image"',
        'sata0:1.startConnected = "TRUE"',
        'sata0:1.autodetect = "FALSE"',
        'ethernet0.present = "TRUE"',
        'ethernet0.connectionType = "nat"',
        'ethernet0.virtualDev = "e1000e"',
        'ethernet0.addressType = "generated"',
        'sound.present = "TRUE"',
        'sound.fileName = "-1"',
        'sound.autodetect = "TRUE"',
        'usb.present = "TRUE"',
        'ehci.present = "TRUE"',
        'floppy0.present = "FALSE"',
        'tools.syncTime = "FALSE"',
        'tools.upgrade.policy = "manual"',
        'powerType.powerOff = "soft"',
        'powerType.powerOn = "soft"',
        'powerType.suspend = "soft"',
        'powerType.reset = "soft"',
        'logging = "TRUE"',
        'log.fileName = "vmware.log"',
        'log.keepOld = "3"'
    )
    Set-Content -LiteralPath $script:VmxPath -Value $vmxLines -Encoding ascii
    Assert-ExistingFile -Path $script:VmxPath -Description "generated VMX configuration" | Out-Null

    if (Test-TestVmRunning) {
        throw "Fresh VM unexpectedly appears in vmrun's running list before start."
    }
    Write-Host "==> Starting fresh EFI VM in $StartMode mode..."
    Invoke-Vmrun -ArgumentList @("start", $script:VmxPath, $StartMode) `
        -Description "start fresh DarkOS test VM" -EchoOutput | Out-Null
    $script:VmStarted = $true

    foreach ($capture in @(
        @{ Delay = 3; Name = "01-boot-03s" },
        @{ Delay = 4; Name = "02-boot-07s" },
        @{ Delay = 4; Name = "03-boot-11s" },
        @{ Delay = 4; Name = "04-boot-15s" }
    )) {
        Start-Sleep -Seconds $capture.Delay
        try {
            Capture-FreshScreenshot -Name $capture.Name | Out-Null
        } catch {
            Write-Warning "Boot screenshot '$($capture.Name)' skipped: $($_.Exception.Message)"
        }
    }

    Wait-ForVmwareTools -TimeoutSeconds $ToolsTimeoutSeconds
    Wait-ForGuestAuthentication -TimeoutSeconds $GuestAuthTimeoutSeconds

    Write-Host "==> Copying committed Phase 3 verifier into the live guest..."
    Invoke-GuestVmrun -ArgumentList @(
        "CopyFileFromHostToGuest", $script:VmxPath,
        $resolvedVerifier, $script:GuestVerifierGuestPath
    ) -Description "copy Phase 3 guest verifier" | Out-Null
    $script:GuestVerifierCopied = $true

    # Inject API keys into the guest environment so the AI shell and verifier can use them.
    if (-not [string]::IsNullOrWhiteSpace($GroqApiKey) -or -not [string]::IsNullOrWhiteSpace($OpenRouterApiKey)) {
        Write-Host "==> Injecting API keys into guest /etc/environment..."
        $envLines = @()
        if (-not [string]::IsNullOrWhiteSpace($GroqApiKey)) {
            $envLines += "DARKOS_GROQ_API_KEY=$GroqApiKey"
            $envLines += "GROQ_API_KEY=$GroqApiKey"
        }
        if (-not [string]::IsNullOrWhiteSpace($OpenRouterApiKey)) {
            $envLines += "DARKOS_OPENROUTER_API_KEY=$OpenRouterApiKey"
            $envLines += "OPENROUTER_API_KEY=$OpenRouterApiKey"
        }
        $envContent = $envLines -join "`n"
        $hostEnvFile = Join-Path $script:EvidenceDir "guest-api-keys.env"
        Set-Content -LiteralPath $hostEnvFile -Value $envContent -Encoding utf8NoBOM
        Invoke-GuestVmrun -ArgumentList @(
            "CopyFileFromHostToGuest", $script:VmxPath,
            $hostEnvFile, "/tmp/darkos-vmware-api-keys.env"
        ) -Description "copy API keys env file to guest" | Out-Null
        # Append to /etc/environment so all subsequent VIX-launched processes inherit the keys
        Invoke-GuestVmrun -ArgumentList @(
            "runProgramInGuest", $script:VmxPath,
            "/bin/bash", "-c",
            "cat /tmp/darkos-vmware-api-keys.env >> /etc/environment && rm -f /tmp/darkos-vmware-api-keys.env"
        ) -Description "persist API keys to guest /etc/environment" | Out-Null
        Write-Host "    API keys written to guest /etc/environment."
    }

    Invoke-GuestMode -Mode "wait-ready" -EvidenceName "wait-ready" | Out-Null
    Capture-FreshScreenshot -Name "10-desktop-ready" | Out-Null
    Invoke-GuestMode -Mode "verify" -EvidenceName "phase3-verify" | Out-Null

    Invoke-GuestMode -Mode "context" -EvidenceName "context-coding" -ModeArguments @("coding") | Out-Null
    $codingShot = Capture-FreshScreenshot -Name "20-context-coding-terminal-highlight"
    Invoke-GuestMode -Mode "context" -EvidenceName "context-media" -ModeArguments @("media") | Out-Null
    $mediaShot = Capture-FreshScreenshot -Name "21-context-media-browser-highlight"
    if ($codingShot.Sha256 -eq $mediaShot.Sha256) {
        throw "Context screenshots are byte-identical; the screen did not visibly change between real app scenarios."
    }

    Invoke-GuestMode -Mode "collect" -EvidenceName "journals-and-runtime" | Out-Null
    $script:RunResult = "PASS"
    $script:FailureMessage = ""
    Write-Host "==> VMware live-ISO and automated Phase 3 verification PASSED."
    Write-Host "    Evidence: $($script:EvidenceDir)"
} catch {
    $script:RunResult = "FAIL"
    $script:FailureMessage = $_.Exception.Message
    Write-Error "VMware verification failed: $($script:FailureMessage)" -ErrorAction Continue

    if ($script:VmStarted -and (Test-TestVmRunning)) {
        try {
            Capture-FreshScreenshot -Name "99-failure" | Out-Null
        } catch {
            Write-Warning "Could not capture failure screenshot: $($_.Exception.Message)"
        }
        if ($script:GuestVerifierCopied -and $script:GuestOperationsReady) {
            try {
                Invoke-GuestMode -Mode "collect" -EvidenceName "failure-journals" | Out-Null
            } catch {
                Write-Warning "Could not collect failure journals: $($_.Exception.Message)"
            }
        }
    }
    throw
} finally {
    if ($script:GuestVerifierCopied -and $script:GuestOperationsReady -and (Test-TestVmRunning)) {
        try {
            Invoke-GuestMode -Mode "cleanup" -EvidenceName "cleanup" | Out-Null
        } catch {
            Write-Warning "Guest fixture cleanup failed: $($_.Exception.Message)"
        }
    }
    if ($script:VmStarted -or (-not [string]::IsNullOrWhiteSpace($script:VmxPath) -and (Test-TestVmRunning))) {
        try {
            Stop-TestVm
        } catch {
            $script:RunResult = "FAIL"
            if ([string]::IsNullOrWhiteSpace($script:FailureMessage)) {
                $script:FailureMessage = $_.Exception.Message
            } else {
                $script:FailureMessage += "; shutdown failure: $($_.Exception.Message)"
            }
            Write-Error "VM shutdown cleanup failed: $($_.Exception.Message)" -ErrorAction Continue
        }
    }
    Write-EvidenceManifests -Metadata $metadata -Result $script:RunResult -Failure $script:FailureMessage
}
