# One-shot check before committing:  powershell -ExecutionPolicy Bypass -File tests\verify.ps1
# (Saved as UTF-8 WITH BOM - PS 5.1 reads a BOM-less file as CP949.)
#   1) py_compile on every Python file in the repo (tracked + new, .gitignore respected)
#   2) python unittest discover (tests\test_*.py) - no network, no real mail, hub is not started
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$fail = 0

Write-Host '== 1. python compile'
$py = @(git ls-files --cached --others --exclude-standard '*.py')
foreach ($f in $py) {
    $out = & python -c "import sys,py_compile; py_compile.compile(sys.argv[1], doraise=True, cfile=None)" $f 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Host "  FAIL $f : $out"; $fail++ }
}
Get-ChildItem -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch 'node_modules|\.venv' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ("  checked {0} files" -f $py.Count)

Write-Host '== 2. python unittest'
# Keep the summary readable: drop interpreter ResourceWarning noise; on failure print the full report (CI needs it).
$ut = @(& python -X utf8 -m unittest discover -s tests 2>&1 | ForEach-Object { "$_" -replace '^System\.Management\.Automation\.RemoteException$', '' } | Where-Object { $_ -notmatch '^sys:1: ResourceWarning' })
$utExit = $LASTEXITCODE
if ($utExit -ne 0) {
    $ut | ForEach-Object { Write-Host $_ }; $fail++
    if ($env:GITHUB_ACTIONS) {
        # GitHub Actions: each failing test becomes an error annotation (readable on the run page without log access)
        $blocks = @(); $cur = $null
        foreach ($line in $ut) {
            if ($line -match '^(FAIL|ERROR): ') { if ($cur) { $blocks += ,$cur }; $cur = @($line) }
            elseif ($line -match '^(=+|-+)$' -or $line -match '^Ran ') { if ($cur -and $line -notmatch '^-+$') { $blocks += ,$cur; $cur = $null } }
            elseif ($cur) { $cur += $line }
        }
        if ($cur) { $blocks += ,$cur }
        for ($i = 0; $i -lt [Math]::Min($blocks.Count, 10); $i++) {
            $b = $blocks[$i]
            $msg = ($b | Select-Object -Last 40) -join "`n"
            if ($msg.Length -gt 4000) { $msg = $msg.Substring($msg.Length - 4000) }
            $msg = $msg.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
            Write-Host ("::error title={0}::{1}" -f ($b[0] -replace '[:,]', ' '), $msg)
        }
    }
}
else { $ut | Where-Object { $_ -match '^(Ran |OK)' } | ForEach-Object { Write-Host "  $_" } }
Get-ChildItem -Path tests -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if ($fail -eq 0) { Write-Host "`nALL PASSED" -ForegroundColor Green; exit 0 }
Write-Host "`nFAILED: $fail" -ForegroundColor Red
exit 1
