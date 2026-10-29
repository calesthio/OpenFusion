# OpenFusion installer for Windows PowerShell (same behavior as install.sh on macOS/Linux).
# A thin wrapper around `openfusion install` that runs straight from this checkout.
# Prefer the package when you can:  uvx openfusion install <harness> <repo>
#
#   .\install.ps1 <harness> [path-to-your-repo] [--no-instructions] [--codex-profiles] [--available MODELS]
#   harness: claude-code | codex | cursor | github-copilot | gemini-cli | antigravity | opencode | generic
#
# Needs only Python 3.9+ (no packages). Uses .\.venv if one exists (e.g. with PyYAML, to read an edited
# core\openfusion.yaml). Nothing is uploaded; files are only written into the repo you name.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($args.Count -lt 1 -or ([string]$args[0]).StartsWith('-')) {
    [Console]::Error.WriteLine("usage: .\install.ps1 <harness> [path-to-your-repo] [--no-instructions] [--codex-profiles] [--available MODELS]")
    [Console]::Error.WriteLine("harnesses: claude-code codex cursor github-copilot gemini-cli antigravity opencode generic")
    exit 2
}

function Test-Python([string[]]$cmd) {
    try {
        $exe = $cmd[0]
        $pre = @()
        if ($cmd.Count -gt 1) { $pre = $cmd[1..($cmd.Count - 1)] }
        & $exe @pre -c "import sys; sys.exit(sys.version_info < (3, 9))" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# Windows venvs use Scripts\python.exe; PowerShell 7 on macOS/Linux uses bin/python.
if ($IsLinux -or $IsMacOS) { $venvPy = Join-Path $here '.venv/bin/python' }
else { $venvPy = Join-Path $here '.venv\Scripts\python.exe' }

$py = $null
if ($env:OPENFUSION_PYTHON) { $py = @($env:OPENFUSION_PYTHON) }
elseif (Test-Path $venvPy) { $py = @($venvPy) }
else {
    foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
        if ((Get-Command $cand[0] -ErrorAction SilentlyContinue) -and (Test-Python $cand)) { $py = $cand; break }
    }
}
if (-not $py) { [Console]::Error.WriteLine("error: Python 3.9+ not found (install it from python.org or set OPENFUSION_PYTHON)"); exit 1 }

$exe = $py[0]; $pre = @(); if ($py.Count -gt 1) { $pre = $py[1..($py.Count - 1)] }
& $exe @pre (Join-Path $here 'run_openfusion.py') install @args
exit $LASTEXITCODE
