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
& $python -m unittest discover -s tests -v

$driver = Get-ChildItem -Path "$env:USERPROFILE\.cache\selenium\chromedriver" `
    -Filter chromedriver.exe -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$arguments = @(
    "-m", "PyInstaller",
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

& $python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $PSScriptRoot "dist\BookLibraryBuilder.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build finished without producing $exe"
}
$previousSmokeMode = $env:BOOKBUILDER_SMOKE_TEST
try {
    $env:BOOKBUILDER_SMOKE_TEST = "1"
    $process = Start-Process -FilePath $exe -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Packaged smoke test failed with exit code $($process.ExitCode)"
    }
}
finally {
    if ($null -eq $previousSmokeMode) {
        Remove-Item Env:\BOOKBUILDER_SMOKE_TEST -ErrorAction SilentlyContinue
    }
    else {
        $env:BOOKBUILDER_SMOKE_TEST = $previousSmokeMode
    }
}

Write-Host "Build and smoke test succeeded: $exe"
