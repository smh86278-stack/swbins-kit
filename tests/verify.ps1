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
& python -X utf8 -m unittest discover -s tests 2>&1 | Select-Object -Last 4
if ($LASTEXITCODE -ne 0) { $fail++ }
Get-ChildItem -Path tests -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if ($fail -eq 0) { Write-Host "`nALL PASSED" -ForegroundColor Green; exit 0 }
Write-Host "`nFAILED: $fail" -ForegroundColor Red
exit 1
