#requires -Version 5.1

param(
    [string]$FastCliRoot = "",
    [string]$PythonVersion = "3.12",
    [string]$InnoCompiler = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $FastCliRoot) {
    $FastCliRoot = Join-Path (Split-Path $ProjectRoot -Parent) "fast-cli"
}
$FastCliRoot = [IO.Path]::GetFullPath($FastCliRoot)
$FastCliWorker = Join-Path $FastCliRoot "bin\fast-scrape-worker.js"
if (-not (Test-Path $FastCliWorker -PathType Leaf)) {
    throw "fast-cli worker was not found: $FastCliWorker. Use -FastCliRoot to specify the fast-cli source directory."
}

$PyLauncher = (Get-Command py.exe -ErrorAction Stop).Source
$NodeCommand = (Get-Command node.exe -ErrorAction Stop).Source
$NpmCommand = (Get-Command npm.cmd -ErrorAction Stop).Source
$NodeVersionText = [string](& $NodeCommand --version)
$NodeVersionText = $NodeVersionText.Trim()
if ($LASTEXITCODE -ne 0 -or $NodeVersionText -notmatch '^v(\d+)\.') {
    throw "Unable to read the Node.js version: $NodeVersionText"
}
if ([int]$Matches[1] -lt 20) {
    throw "Node.js 20 or newer is required. Current version: $NodeVersionText"
}
$NodeArchitecture = [string](& $NodeCommand -p "process.arch")
if ($NodeArchitecture.Trim() -ne "x64") {
    throw "Windows x64 Node.js is required."
}

if (-not $InnoCompiler) {
    $ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $ProgramFiles64 = [Environment]::GetEnvironmentVariable("ProgramFiles")
    $LocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
    $InnoRoots = @($ProgramFilesX86, $ProgramFiles64)
    if ($LocalAppData) {
        $InnoRoots += Join-Path $LocalAppData "Programs"
    }
    $InnoCandidates = $InnoRoots | Where-Object { $_ } | ForEach-Object {
        Join-Path $_ "Inno Setup 6\ISCC.exe"
    }
    $InnoCompiler = $InnoCandidates | Where-Object { $_ -and (Test-Path $_ -PathType Leaf) } |
        Select-Object -First 1
}
if (-not $InnoCompiler -or -not (Test-Path $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup 6 compiler ISCC.exe was not found. Install Inno Setup 6 or use -InnoCompiler."
}

$BuildRoot = Join-Path $ProjectRoot ".build"
$RuntimeRoot = Join-Path $BuildRoot "runtime"
$VenvRoot = Join-Path $BuildRoot "venv"
$Python = Join-Path $VenvRoot "Scripts\python.exe"
$CliStage = Join-Path $RuntimeRoot "fast-cli"
$NodeStage = Join-Path $RuntimeRoot "node"
$BrowserStage = Join-Path $RuntimeRoot "ms-playwright"
$DistRoot = Join-Path $ProjectRoot "dist"
$AppDist = Join-Path $DistRoot "Fast-P"
$InstallerRoot = Join-Path $DistRoot "installer"
$RuntimePackageRoot = Join-Path $DistRoot "runtime"

foreach ($Path in @($BuildRoot, $DistRoot)) {
    if (Test-Path $Path) {
        Remove-Item $Path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $RuntimeRoot, $NodeStage, $InstallerRoot, $RuntimePackageRoot -Force | Out-Null

Write-Host "[1/7] Creating an isolated Python build environment"
& $PyLauncher "-$PythonVersion" -m venv $VenvRoot
if ($LASTEXITCODE -ne 0) {
    throw "Unable to create a virtual environment with Python $PythonVersion."
}
$PythonBits = [string](& $Python -c "import struct; print(struct.calcsize('P') * 8)")
if ($PythonBits.Trim() -ne "64") {
    throw "Windows x64 Python is required."
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -e "${ProjectRoot}[build]"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Python build dependencies."
}

$Version = [string](& $Python -c "import tomllib; print(tomllib.load(open(r'$ProjectRoot\pyproject.toml','rb'))['project']['version'])")
$Version = $Version.Trim()
if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "The application version must use x.y.z format: $Version"
}
$VersionParts = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], 0)

Write-Host "[2/7] Staging bundled Node.js $NodeVersionText"
Copy-Item $NodeCommand (Join-Path $NodeStage "node.exe")
$NodeLicense = Join-Path (Split-Path $NodeCommand -Parent) "LICENSE"
if (Test-Path $NodeLicense -PathType Leaf) {
    Copy-Item $NodeLicense (Join-Path $NodeStage "LICENSE")
}

Write-Host "[3/7] Staging the fast-cli runtime"
New-Item -ItemType Directory -Path $CliStage -Force | Out-Null
foreach ($Name in @("bin", "src", "config", "strategies", "test")) {
    Copy-Item (Join-Path $FastCliRoot $Name) (Join-Path $CliStage $Name) -Recurse
}
foreach ($Name in @("package.json", "package-lock.json", "README.md")) {
    Copy-Item (Join-Path $FastCliRoot $Name) (Join-Path $CliStage $Name)
}
$OldSkipBrowserDownload = $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
try {
    $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
    Push-Location $CliStage
    try {
        & $NpmCommand ci --omit=dev --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "fast-cli npm ci failed." }
        if (-not $SkipTests) {
            & $NpmCommand test
            if ($LASTEXITCODE -ne 0) { throw "fast-cli tests failed." }
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = $OldSkipBrowserDownload
}
Remove-Item (Join-Path $CliStage "test") -Recurse -Force
$FastCliPackage = Get-Content (Join-Path $CliStage "package.json") -Raw | ConvertFrom-Json
$FastCliVersion = [string]$FastCliPackage.version
if ($FastCliVersion -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid fast-cli version: $FastCliVersion"
}
$UpdateStage = Join-Path $BuildRoot "fast-cli-update"
New-Item -ItemType Directory -Path $UpdateStage -Force | Out-Null
Copy-Item $CliStage (Join-Path $UpdateStage "fast-cli") -Recurse
$Manifest = [ordered]@{
    schemaVersion = 1
    name = "@ickey/fast-cli"
    version = $FastCliVersion
    apiVersion = 1
    platform = "win32-x64"
    node = ">=20"
    entry = "fast-cli/bin/fast-scrape-worker.js"
} | ConvertTo-Json
[IO.File]::WriteAllText(
    (Join-Path $UpdateStage "manifest.json"),
    $Manifest,
    [Text.UTF8Encoding]::new($false)
)
$RuntimePackage = Join-Path $RuntimePackageRoot "fast-cli-runtime-win-x64-$FastCliVersion.zip"
Compress-Archive -Path (Join-Path $UpdateStage "*") -DestinationPath $RuntimePackage -CompressionLevel Optimal

Write-Host "[4/7] Downloading the pinned Playwright Chromium"
$OldBrowsersPath = $env:PLAYWRIGHT_BROWSERS_PATH
try {
    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserStage
    & $Python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download Playwright Chromium."
    }
}
finally {
    $env:PLAYWRIGHT_BROWSERS_PATH = $OldBrowsersPath
}

if (-not $SkipTests) {
    Write-Host "[5/7] Running Fast-P tests"
    & $Python -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
    if ($LASTEXITCODE -ne 0) {
        throw "Fast-P tests failed."
    }
}
else {
    Write-Host "[5/7] Skipping tests"
}

$VersionFile = Join-Path $BuildRoot "version-info.txt"
$VersionText = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($VersionParts -join ',')),
    prodvers=($($VersionParts -join ',')),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [
          StringStruct('CompanyName', 'Fast-P'),
          StringStruct('FileDescription', 'Fast-P Price Comparison Screenshot Tool'),
          StringStruct('FileVersion', '$Version'),
          StringStruct('InternalName', 'Fast-P'),
          StringStruct('OriginalFilename', 'Fast-P.exe'),
          StringStruct('ProductName', 'Fast-P Price Comparison Screenshot Tool'),
          StringStruct('ProductVersion', '$Version')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"@
[IO.File]::WriteAllText($VersionFile, $VersionText, [Text.UTF8Encoding]::new($false))

Write-Host "[6/7] Building the Fast-P Windows application"
$OldRuntime = $env:FAST_P_BUILD_RUNTIME
$OldVersionFile = $env:FAST_P_VERSION_FILE
try {
    $env:FAST_P_BUILD_RUNTIME = $RuntimeRoot
    $env:FAST_P_VERSION_FILE = $VersionFile
    Push-Location $ProjectRoot
    try {
        & $Python -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot "fast-p.spec")
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:FAST_P_BUILD_RUNTIME = $OldRuntime
    $env:FAST_P_VERSION_FILE = $OldVersionFile
}

$BundledNode = Join-Path $AppDist "_internal\runtime\node\node.exe"
$BundledCli = Join-Path $AppDist "_internal\runtime\fast-cli\bin\fast-scrape.js"
$BundledWorker = Join-Path $AppDist "_internal\runtime\fast-cli\bin\fast-scrape-worker.js"
$BundledChromium = Get-ChildItem (
    Join-Path $AppDist "_internal\runtime\ms-playwright\chromium-*"
) -Recurse -Filter chrome.exe | Where-Object {
    $_.FullName -match 'chrome-win(64)?\\chrome\.exe$'
} | Select-Object -First 1
foreach ($Path in @((Join-Path $AppDist "Fast-P.exe"), $BundledNode, $BundledCli, $BundledWorker)) {
    if (-not (Test-Path $Path -PathType Leaf)) {
        throw "A required runtime file is missing from the application bundle: $Path"
    }
}
if (-not $BundledChromium) {
    throw "Playwright Chromium is missing from the application bundle."
}
& $BundledNode $BundledCli platforms | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Bundled fast-cli platforms smoke check failed." }
& $BundledNode $BundledWorker --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Bundled fast-cli worker smoke check failed." }

Write-Host "[7/7] Building the Windows installer"
$OldAppVersion = $env:FAST_P_VERSION
$OldDistDir = $env:FAST_P_DIST_DIR
$OldInstallerDir = $env:FAST_P_INSTALLER_DIR
try {
    $env:FAST_P_VERSION = $Version
    $env:FAST_P_DIST_DIR = $AppDist
    $env:FAST_P_INSTALLER_DIR = $InstallerRoot
    & $InnoCompiler (Join-Path $ProjectRoot "installer\Fast-P.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
}
finally {
    $env:FAST_P_VERSION = $OldAppVersion
    $env:FAST_P_DIST_DIR = $OldDistDir
    $env:FAST_P_INSTALLER_DIR = $OldInstallerDir
}

$Installer = Join-Path $InstallerRoot "Fast-P-Setup-$Version.exe"
if (-not (Test-Path $Installer -PathType Leaf)) {
    throw "The installer was not created: $Installer"
}
Write-Host ""
Write-Host "Build completed: $Installer" -ForegroundColor Green
Write-Host "Runtime update package: $RuntimePackage" -ForegroundColor Green
