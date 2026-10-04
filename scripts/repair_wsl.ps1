#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

# Install the official WSL MSI and enable its VM component. No distro removal/reset.
$taskWorkspace = Split-Path -Parent $PSScriptRoot
$taskInstaller = Join-Path $taskWorkspace 'data\setup\wsl.3.0.1.0.x64.msi'
$taskInstallLog = Join-Path $taskWorkspace 'data\setup\wsl-install.log'
$taskExpectedHash = '28B1A0D013640A2AC95898EA705FA186E5B4FF767A1C1B49257161BC106599C6'

if (-not (Test-Path -LiteralPath $taskInstaller)) {
    throw "Installer missing: $taskInstaller"
}
if ((Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash -ne $taskExpectedHash) {
    throw 'Installer checksum does not match the official Microsoft release.'
}
$taskSignature = Get-AuthenticodeSignature -LiteralPath $taskInstaller
if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'Microsoft installer signature verification failed. Installation stopped.'
}

Write-Host 'Installing official Microsoft WSL 3.0.1. Please wait.'
$taskInstallArgs = @('/i', ('"{0}"' -f $taskInstaller), '/passive', '/norestart', '/L*v', ('"{0}"' -f $taskInstallLog))
$taskInstall = Start-Process -FilePath 'msiexec.exe' -ArgumentList $taskInstallArgs -WindowStyle Hidden -Wait -PassThru
if ($taskInstall.ExitCode -notin @(0, 3010)) {
    throw "WSL installer failed with exit code $($taskInstall.ExitCode). Log: $taskInstallLog"
}

Write-Host 'Enabling Virtual Machine Platform.'
& dism.exe /Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart
$taskFeatureExitCode = $LASTEXITCODE
if ($taskFeatureExitCode -notin @(0, 3010)) {
    throw "Windows feature setup failed with exit code $taskFeatureExitCode. Review the DISM output above."
}

Write-Host ''
Write-Host 'Installer and feature setup succeeded. Restart Windows yourself now.'
Write-Host 'After restart: run wsl --version, open Docker Desktop, then run docker version.'
Write-Host "Installation log: $taskInstallLog"
