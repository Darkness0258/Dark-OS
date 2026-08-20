# PowerShell script to boot DarkOS ISO in VMware Workstation and run Phase 3 verification
param(
    [string]$IsoPath = "D:\Projects\Dark OS\out\darkos.iso",
    [string]$VmDir  = "D:\Virtual Machines\DarkOS-Test"
)

$ErrorActionPreference = "Stop"
$Vmrun      = "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
$VDiskMgr   = "C:\Program Files (x86)\VMware\VMware Workstation\vmware-vdiskmanager.exe"

if (-not (Test-Path $IsoPath)) {
    Write-Error "ISO not found at $IsoPath - build it first with ci/docker-build-iso.sh"
    exit 1
}

$ResolvedIso = (Resolve-Path $IsoPath).Path
Write-Host "==> Setting up VMware test VM in $VmDir using ISO $ResolvedIso"

# Create VM directory and virtual disk
New-Item -ItemType Directory -Path $VmDir -Force | Out-Null

$VmdkPath = Join-Path $VmDir "DarkOS-disk.vmdk"
if (-not (Test-Path $VmdkPath)) {
    Write-Host "==> Creating 40GB virtual disk..."
    & $VDiskMgr -c -s 40GB -a lsilogic -t 1 $VmdkPath
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create VMDK"; exit 1 }
} else {
    Write-Host "==> Virtual disk already exists, reusing."
}

# Write VMX configuration
$VmxPath = Join-Path $VmDir "DarkOS.vmx"
$vmxLines = @(
    '.encoding = "windows-1252"',
    'config.version = "8"',
    'virtualHW.version = "21"',
    'mks.enable3d = "TRUE"',
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
    'virtualHW.productCompatibility = "hosted"',
    'powerType.powerOff = "soft"',
    'powerType.powerOn = "soft"',
    'powerType.suspend = "soft"',
    'powerType.reset = "soft"',
    'displayName = "DarkOS Phase 3 Test"',
    'guestOS = "other6xlinux-64"',
    'tools.syncTime = "FALSE"',
    'sound.present = "TRUE"',
    'sound.fileName = "-1"',
    'sound.autodetect = "TRUE"',
    'memsize = "4096"',
    'numvcpus = "4"',
    'firmware = "efi"',
    'svga.vramSize = "268435456"',
    'sata0.present = "TRUE"',
    'sata0:0.present = "TRUE"',
    'sata0:0.fileName = "DarkOS-disk.vmdk"',
    'sata0:0.deviceType = "disk"',
    'sata0:1.present = "TRUE"',
    "sata0:1.fileName = `"$ResolvedIso`"",
    'sata0:1.deviceType = "cdrom-image"',
    'ethernet0.present = "TRUE"',
    'ethernet0.connectionType = "nat"',
    'ethernet0.virtualDev = "e1000e"',
    'ethernet0.wakeOnPciOui = "TRUE"',
    'ethernet0.addressType = "generated"',
    'usb.present = "TRUE"',
    'ehci.present = "TRUE"',
    'cleanShutdown = "TRUE"',
    'softPowerOff = "FALSE"'
)

Set-Content -Path $VmxPath -Value $vmxLines -Encoding Ascii
Write-Host "==> VMX written to $VmxPath"

# Boot the VM
Write-Host "==> Starting VM..."
& $Vmrun -T ws start $VmxPath gui
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to start VM"; exit 1 }

# Capture screenshots at intervals
$screenshotDir = Join-Path $VmDir "screenshots"
New-Item -ItemType Directory -Path $screenshotDir -Force | Out-Null

function Capture-Screenshot {
    param([string]$Name)
    $path = Join-Path $screenshotDir "$Name.png"
    Write-Host "  Capturing: $Name..."
    & $Vmrun -T ws captureScreen $VmxPath $path 2>&1
    if (Test-Path $path) {
        Write-Host "  => Saved $path ($(([IO.FileInfo]$path).Length) bytes)"
    } else {
        Write-Host "  => FAILED to capture $Name"
    }
    return $path
}

Write-Host "==> Waiting 10s for early boot (Plymouth)..."
Start-Sleep -Seconds 10
Capture-Screenshot "01-plymouth-boot"

Write-Host "==> Waiting 20s for TTY login..."
Start-Sleep -Seconds 20
Capture-Screenshot "02-tty-login"

Write-Host "==> Waiting 40s for Hyprland desktop..."
Start-Sleep -Seconds 40
Capture-Screenshot "03-hyprland-desktop"

Write-Host ""
Write-Host "==> VM is running. Screenshots in: $screenshotDir"
Write-Host "==> Use vmrun commands to interact with the guest:"
Write-Host "    & '$Vmrun' -T ws captureScreen '$VmxPath' <output.png>"
