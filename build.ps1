$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    python -m venv .venv
}

& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$driver = Get-ChildItem -Path "$env:USERPROFILE\.cache\selenium\chromedriver" `
    -Filter chromedriver.exe -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$arguments = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "BookLibraryBuilder",
    "--version-file", "version_info.txt",
    "--add-data", "assets;assets",
    "--icon", "assets\app_icon.ico"
)
if ($driver) {
    $arguments += @("--add-binary", "$($driver.FullName);drivers")
}
$arguments += "main.py"

& $python -c "import sys; from pathlib import Path; from bookbuilder.gui import prepare_tk_runtime; prepare_tk_runtime(Path('build/tk-runtime')); import PyInstaller.__main__; PyInstaller.__main__.run(sys.argv[1:])" @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $PSScriptRoot "dist\BookLibraryBuilder.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build finished without producing $exe"
}
$previousSmokeMode = $env:BOOKBUILDER_SMOKE_TEST
$previousLocalData = $env:LOCALAPPDATA
try {
    $env:BOOKBUILDER_SMOKE_TEST = "1"
    $env:LOCALAPPDATA = Join-Path $PSScriptRoot "build\smoke-profile"
    $smokeData = Join-Path $env:LOCALAPPDATA "AuthorizedBookBuilder"
    New-Item -ItemType Directory -Path $smokeData -Force | Out-Null
    $fixture = @{base_url="https://example.invalid"; auto_update_source=$false; output_dir=(Join-Path $env:LOCALAPPDATA "downloads")}
    [IO.File]::WriteAllText((Join-Path $smokeData "settings.json"), ($fixture | ConvertTo-Json))
    $process = Start-Process -FilePath $exe -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Packaged smoke test failed with exit code $($process.ExitCode)"
    }
}
finally {
    $env:LOCALAPPDATA = $previousLocalData
    if ($null -eq $previousSmokeMode) {
        Remove-Item Env:\BOOKBUILDER_SMOKE_TEST -ErrorAction SilentlyContinue
    }
    else {
        $env:BOOKBUILDER_SMOKE_TEST = $previousSmokeMode
    }
}

Write-Host "Build and smoke test succeeded: $exe"
