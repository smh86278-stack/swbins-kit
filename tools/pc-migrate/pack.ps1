<#
  PC 이전 묶음 만들기 (지금 PC → 새 PC)
  -------------------------------------
  새 PC 로 옮길 때 clone·설치로는 다시 오지 않는 것만 골라 암호 걸린 .7z 하나로 묶는다. 원본은 건드리지 않는다.

      powershell -ExecutionPolicy Bypass -File pack.ps1 -DryRun      무엇이 담기는지·크기만 본다 (먼저 이것부터)
      powershell -ExecutionPolicy Bypass -File pack.ps1              바탕화면\pc-migration.7z 를 만든다 (암호를 두 번 묻는다)

  Claude Code 를 모두 닫고, 따로 연 PowerShell 창에서 실행한다.
    - 열린 Claude Code 는 대화 기록(.jsonl)을 쓰는 중이라 끝이 잘린다.
    - 암호를 입력받아야 해서 Claude Code 안(명령 도구·! 접두어)에서는 돌지 않는다.

  담는 것 (설정은 config.local.json 의 "migrate" 갈래 — 비우면 아래 기본값)
    claude\             ~\.claude 의 대화 기록(projects\)·메모리·CLAUDE.md·skills\·hooks\·plans\·history.jsonl
                        projects 는 migrate.claude_projects, 비면 임시 폴더(…AppData-Local-Temp…)를 뺀 전부
    mcpServers.json     ~\.claude.json 의 mcpServers 부분만 (env 에 토큰이 들어 있을 수 있다)
    kit-local\          이 키트의 git·설치 파일에 없는 것 — config.local.json · 내 자동화(macros.local) · 켜 둔 상태 등
    repos\<이름>\       migrate.repos 저장소마다 clone 으로 안 오는 작업물
                          files\        커밋 안 한 새 파일 + 제외 규칙(.gitignore)에 걸린 파일(.env·로컬 설정 등)
                          changes\      커밋 안 한 수정분(git diff) — 상위·서브모듈 각각
                          bundles\      원격 어디에도 없는 로컬 브랜치 커밋(git bundle)
                        로그·크래시 덤프·node_modules·.venv·target·build·dist 같은 다시 만들 수 있는 것은 뺀다.
                        안에 든 다른 저장소(clone 본)는 담지 않고 "다시 clone" 이라고 알려 준다.
    extra\              migrate.extra_paths 의 파일·폴더 (그 밖에 따로 챙길 것)
    env-vars.txt        migrate.env_vars 이름의 사용자 환경변수 값 — 암호 묶음일 때만 담는다

  일부러 안 담는 것
    ~\.claude\.credentials.json(로그인 — 새 PC 에서 다시 로그인) · plugins\ · settings.json(이 PC 경로·훅)
    Windows 가 이 PC·이 사용자에게 묶어 암호화한 값(password_enc 등) — 옮겨도 못 풀어서 새 PC 에서 다시 넣는다

  옵션
    -OutDir <폴더>          기본 바탕화면\pc-migration (.7z 는 그 옆에 같은 이름으로)
    -NoClaude -NoKit -NoRepos      그 갈래를 뺀다
    -IncludeFileHistory     ~\.claude\file-history(되돌리기 스냅숏, 클 수 있다)도 담는다
    -Bandizip / -SevenZip   압축 도구를 고른다. 안 주면 반디집(bz.exe) → 7-Zip 순으로 찾는다
    -KeepFolder             압축 뒤 평문 폴더를 지우지 않는다 (기본은 압축을 시험해 보고 지운다)
    -NoEncrypt              암호 없이 폴더로만 만든다. 환경변수 값은 이때 담지 않는다
    -ClaudeDir -KitDir      시험용 — 다른 위치를 가리킨다
#>
[CmdletBinding()]
param(
    [string]   $OutDir = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'pc-migration'),
    [string]   $ClaudeDir = (Join-Path $env:USERPROFILE '.claude'),
    [string]   $ClaudeJson = (Join-Path $env:USERPROFILE '.claude.json'),
    [string]   $KitDir = '',
    [switch]   $NoClaude,
    [switch]   $NoKit,
    [switch]   $NoRepos,
    [switch]   $IncludeFileHistory,
    [switch]   $Bandizip,
    [switch]   $SevenZip,
    [string]   $BandizipPath = '',
    [string]   $SevenZipPath = '',
    [switch]   $KeepFolder,
    [switch]   $NoEncrypt,
    [switch]   $DryRun
)

$ErrorActionPreference = 'Stop'
if (-not $KitDir) { $KitDir = Split-Path (Split-Path $PSScriptRoot) }   # tools\pc-migrate → 키트 루트

# ── 설정 (config.local.json 의 migrate 갈래) ─────────────────────────────
$cfg = $null
$cfgPath = Join-Path $KitDir 'config.local.json'
if (Test-Path -LiteralPath $cfgPath) {
    $all = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($all.PSObject.Properties.Name -contains 'migrate') { $cfg = $all.migrate }
}
function Get-Cfg([string] $name) {
    if ($cfg -and ($cfg.PSObject.Properties.Name -contains $name)) { return @($cfg.$name | Where-Object { $_ }) }
    return @()
}
function Expand([string] $p) { [Environment]::ExpandEnvironmentVariables($p) }

# 다시 만들 수 있거나 쓸모없는 것 — 경로 조각 하나라도 걸리면 뺀다
$junk = '(^|/)(node_modules|\.venv|venv|__pycache__|\.pytest_cache|\.mypy_cache|target|build|dist|out|bin|obj|\.gradle|\.idea|\.vs|\.next|\.nuxt|coverage|logs|\.cache|\.playwright-mcp)(/|$)|\.(log|stackdump|pyc|tmp)$'

function Get-SizeMB([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { return 0 }
    $item = Get-Item -LiteralPath $path -Force
    if (-not $item.PSIsContainer) { return [math]::Round($item.Length / 1MB, 1) }
    $sum = (Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    return [math]::Round(([double]$sum) / 1MB, 1)
}

function Invoke-GitLines([string] $dir, [string[]] $gitArgs) {
    # 한글 경로가 깨지지 않게 git 출력을 UTF-8 로 읽고, stderr 경고(LF→CRLF 등)로 멈추지 않게 Continue
    $ErrorActionPreference = 'Continue'
    $old = [Console]::OutputEncoding
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    try { @(& git -C $dir -c core.quotepath=false @gitArgs 2>$null | Where-Object { $_ }) } finally { [Console]::OutputEncoding = $old }
}

# ── 담을 목록 (DryRun 이든 아니든 같은 목록) ─────────────────────────────
$plan = New-Object System.Collections.ArrayList     # @{ Src; Rel; Label }  — 파일이든 폴더든
$gitJobs = New-Object System.Collections.ArrayList  # @{ Dir; Args; Out; Label }
function Add-Plan([string] $src, [string] $rel, [string] $label = '') {
    if (Test-Path -LiteralPath $src) { [void]$plan.Add(@{ Src = $src; Rel = $rel; Label = $label }) }
}

if (-not $NoClaude) {
    if (-not (Test-Path -LiteralPath $ClaudeDir)) { Write-Warning "Claude Code 폴더가 없습니다 — 건너뜀: $ClaudeDir" }
    else {
        $projects = Get-Cfg 'claude_projects'
        if (-not $projects.Count) {
            $projects = @(Get-ChildItem -LiteralPath (Join-Path $ClaudeDir 'projects') -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -notmatch 'AppData-Local-Temp' } | ForEach-Object { $_.Name })
        }
        foreach ($p in $projects) {
            $src = Join-Path $ClaudeDir "projects\$p"
            if (Test-Path -LiteralPath $src) { Add-Plan $src "claude\projects\$p" }
            else { Write-Warning "projects\$p 없음 — 건너뜀" }
        }
        foreach ($f in 'CLAUDE.md', 'statusline-command.sh', 'history.jsonl') { Add-Plan (Join-Path $ClaudeDir $f) "claude\$f" }
        Get-ChildItem -LiteralPath $ClaudeDir -Filter *.md -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne 'CLAUDE.md' } | ForEach-Object { Add-Plan $_.FullName "claude\$($_.Name)" }
        foreach ($d in 'skills', 'hooks', 'plans', 'agents', 'commands') { Add-Plan (Join-Path $ClaudeDir $d) "claude\$d" }
        if ($IncludeFileHistory) { Add-Plan (Join-Path $ClaudeDir 'file-history') 'claude\file-history' }
    }
}

if (-not $NoKit) {
    foreach ($rel in 'config.local.json', 'tools\dispatch-chat\company.json', 'tools\macro-hub\state.local.json',
                     'tools\macro-hub\pet\settings.local.json', 'tools\macro-hub\macros.local') {
        Add-Plan (Join-Path $KitDir $rel) "kit-local\$rel"
    }
    # 허브 화면에서 가져온 스킨(모습) — 견본 README 말고 폴더만
    Get-ChildItem -LiteralPath (Join-Path $KitDir 'tools\macro-hub\web\skins') -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Plan $_.FullName "kit-local\tools\macro-hub\web\skins\$($_.Name)" }
}

$i = 0
foreach ($raw in (Get-Cfg 'extra_paths')) {
    $i++
    $src = Expand $raw
    if (-not (Test-Path -LiteralPath $src)) { Write-Warning "extra_paths 없음 — 건너뜀: $src"; continue }
    $rel = "extra\$i-$(Split-Path $src -Leaf)"
    Add-Plan $src $rel
    [void]$plan[$plan.Count - 1].Add('Origin', $src)
}

if (-not $NoRepos) {
    foreach ($raw in (Get-Cfg 'repos')) {
        $repo = Expand $raw
        if (-not (Test-Path -LiteralPath (Join-Path $repo '.git'))) { Write-Warning "git 저장소가 아님 — 건너뜀: $repo"; continue }
        $leaf = Split-Path $repo -Leaf
        $base = "repos\$leaf"
        [void]$plan.Add(@{ Src = $null; Rel = "$base\_origin.txt"; Text = $repo; Label = '원래 위치' })
        $subs = @(Invoke-GitLines $repo @('submodule', 'foreach', '--recursive', '--quiet', 'echo $displaypath'))
        foreach ($sub in @('') + $subs) {
            $dir = if ($sub) { Join-Path $repo ($sub -replace '/', '\') } else { $repo }
            $tag = if ($sub) { $sub -replace '/', '__' } else { '_root' }
            # --directory: 통째로 새 폴더는 "폴더/" 한 줄로 나온다 → 그 폴더를 통째로 담는다
            $entries = @(Invoke-GitLines $dir @('ls-files', '--others', '--exclude-standard', '--directory')) +
                       @(Invoke-GitLines $dir @('ls-files', '--others', '--ignored', '--exclude-standard', '--directory'))
            foreach ($en in ($entries | Sort-Object -Unique)) {
                if ($en -match $junk) { continue }
                $src = Join-Path $dir ($en.TrimEnd('/') -replace '/', '\')
                if ($en.EndsWith('/') -and (Test-Path -LiteralPath (Join-Path $src '.git'))) {
                    Write-Warning "안에 든 저장소라 안 담음 — 새 PC 에서 다시 clone: $src"; continue
                }
                $prefix = if ($sub) { "$($sub -replace '/', '\')\" } else { '' }
                Add-Plan $src "$base\files\$prefix$($en.TrimEnd('/') -replace '/', '\')"
            }
            $changed = @(Invoke-GitLines $dir @('diff', '--name-only', '--ignore-submodules=all') | Where-Object { $_ -notmatch $junk })
            if ($changed.Count) {
                [void]$gitJobs.Add(@{ Dir = $dir; Out = "$base\changes\$tag.patch"; Label = "수정 $($changed.Count)개 파일"
                    Args = @('diff', '--binary', '--ignore-submodules=all', '--output=<OUT>', '--') + $changed })
            }
            $brs = @(Invoke-GitLines $dir @('for-each-ref', '--format=%(refname:short)', 'refs/heads') |
                Where-Object { Invoke-GitLines $dir @('log', '--oneline', '-1', $_, '--not', '--remotes') })
            if ($brs.Count) {
                $n = @(Invoke-GitLines $dir @('log', '--oneline', '--branches', '--not', '--remotes')).Count
                [void]$gitJobs.Add(@{ Dir = $dir; Out = "$base\bundles\$tag.bundle"; Label = "원격에 없는 브랜치 $($brs -join ', ') · 커밋 $n개"
                    Args = @('bundle', 'create', '<OUT>') + $brs + @('--not', '--remotes') })
            }
        }
    }
}

$envNames = Get-Cfg 'env_vars'

# ── 미리 보기 ───────────────────────────────────────────────────────────
Write-Host ''
Write-Host "출력: $OutDir" -ForegroundColor Cyan
$total = 0
foreach ($it in $plan) {
    $mb = if ($it.Src) { Get-SizeMB $it.Src } else { 0 }
    $total += $mb
    Write-Host ('  {0,8:N1} MB  {1}{2}' -f $mb, $it.Rel, $(if ($it.Label) { "  ($($it.Label))" } else { '' }))
    if ($mb -ge 200) { Write-Warning "  큰 항목입니다 — 정말 옮길 것인지 보세요: $($it.Src)" }
}
foreach ($j in $gitJobs) { Write-Host ('  {0,8}     {1}  ({2})' -f 'git', $j.Out, $j.Label) }
foreach ($n in $envNames) {
    $has = [bool][Environment]::GetEnvironmentVariable($n, 'User')
    Write-Host ('  {0,8}     env-vars.txt  {1} {2}' -f 'env', $n, $(if ($has) { '' } else { '(이 PC 에 없음 — 건너뜀)' }))
}
Write-Host ('  {0,8:N1} MB  합계' -f $total) -ForegroundColor Cyan
if ($envNames.Count -and $NoEncrypt) { Write-Warning '-NoEncrypt 라 환경변수 값은 담지 않습니다.' }
if ($DryRun) { Write-Host "`n-DryRun: 아무것도 만들지 않았습니다." -ForegroundColor Yellow; return }

# ── 압축 도구·암호 (복사 전에 정해 실수를 일찍 잡는다) ──────────────────
function Find-Tool([string[]] $candidates) {
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    return $null
}
$bz = Find-Tool @($BandizipPath, 'C:\Program Files\Bandizip\bz.exe', 'C:\Program Files (x86)\Bandizip\bz.exe', (Get-Command bz.exe -ErrorAction SilentlyContinue).Source)
$sz = Find-Tool @($SevenZipPath, 'C:\Program Files\7-Zip\7z.exe', 'C:\Program Files (x86)\7-Zip\7z.exe', (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source)
$tool = $null
$password = $null
if (-not $NoEncrypt) {
    if ($Bandizip -and -not $bz) { throw '반디집 콘솔 도구(bz.exe)를 찾지 못했습니다. -BandizipPath 로 지정하세요.' }
    if ($SevenZip -and -not $sz) { throw '7z.exe 를 찾지 못했습니다. -SevenZipPath 로 지정하세요.' }
    $tool = if ($Bandizip) { 'bz' } elseif ($SevenZip) { '7z' } elseif ($bz) { 'bz' } elseif ($sz) { '7z' } else { $null }
    if (-not $tool) { throw '암호 압축에 쓸 반디집이나 7-Zip 이 없습니다. 하나를 설치하세요. (암호 없이 폴더로만 만들려면 -NoEncrypt)' }
    $archive = "$OutDir.7z"
    if (Test-Path -LiteralPath $archive) { throw "이미 있습니다: $archive  (옮기거나 지운 뒤 다시 하세요. 덮어쓰지 않습니다)" }
    function ConvertTo-Plain([securestring] $s) {
        $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
    }
    $p1 = ConvertTo-Plain (Read-Host '압축 암호' -AsSecureString)
    $p2 = ConvertTo-Plain (Read-Host '압축 암호 확인' -AsSecureString)
    if (-not $p1) { throw '암호가 비어 있습니다.' }
    if ($p1 -ne $p2) { throw '암호가 서로 다릅니다.' }
    $password = $p1
}

if (Test-Path -LiteralPath $OutDir) {
    if (@(Get-ChildItem -LiteralPath $OutDir -Force).Count) { throw "출력 폴더가 비어 있지 않습니다: $OutDir  (지우거나 -OutDir 로 다른 곳을 주세요)" }
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ── 복사 ────────────────────────────────────────────────────────────────
foreach ($it in $plan) {
    $dst = Join-Path $OutDir $it.Rel
    if ($it.Text) {
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Set-Content -LiteralPath $dst -Value $it.Text -Encoding UTF8
        continue
    }
    if ((Get-Item -LiteralPath $it.Src -Force).PSIsContainer) {
        # robocopy 는 260자를 넘는 경로도 다룬다. 다시 만들 수 있는 폴더·로그는 여기서도 뺀다
        robocopy $it.Src $dst /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP `
            /XD node_modules .venv venv __pycache__ .pytest_cache .mypy_cache .gradle .cache `
            /XF *.log *.stackdump *.pyc | Out-Null
        if ($LASTEXITCODE -ge 8) { Write-Warning "robocopy 실패(코드 $LASTEXITCODE): $($it.Src)" }
    } else {
        $to = '\\?\' + $dst
        [void][IO.Directory]::CreateDirectory((Split-Path $to))
        [IO.File]::Copy('\\?\' + $it.Src, $to, $true)
    }
    if ($it.Origin) { Set-Content -LiteralPath "$dst._origin.txt" -Value $it.Origin -Encoding UTF8 }
}

$ErrorActionPreference = 'Continue'   # git 의 stderr 경고로 멈추지 않게 — 실패는 종료 코드로 본다
foreach ($j in $gitJobs) {
    $out = Join-Path $OutDir $j.Out
    New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
    # patch·bundle 은 git 이 파일로 직접 쓴다 — PowerShell 파이프를 거치면 바이트가 바뀐다
    & git -C $j.Dir -c core.quotepath=false @($j.Args | ForEach-Object { $_.Replace('<OUT>', $out) }) 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warning "git 실패(코드 $LASTEXITCODE): $($j.Dir) $($j.Args[0])" }
}
$ErrorActionPreference = 'Stop'

# ~\.claude.json 은 통째로 옮기지 않고 mcpServers 만
$mcpNote = 'mcpServers.json 없음'
if (-not $NoClaude -and (Test-Path -LiteralPath $ClaudeJson)) {
    $j = Get-Content -LiteralPath $ClaudeJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($j.PSObject.Properties.Name -contains 'mcpServers' -and $j.mcpServers) {
        $j.mcpServers | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath (Join-Path $OutDir 'mcpServers.json') -Encoding UTF8
        $mcpNote = 'mcpServers.json 담음 — env 에 토큰이 들어 있을 수 있다'
    }
}

# 환경변수 값 — 암호 묶음일 때만
$envNote = '환경변수 없음'
if ($envNames.Count -and -not $NoEncrypt) {
    $lines = foreach ($n in $envNames) {
        $v = [Environment]::GetEnvironmentVariable($n, 'User')
        if ($v) { "$n=$v" }
    }
    Set-Content -LiteralPath (Join-Path $OutDir 'env-vars.txt') -Value @($lines) -Encoding UTF8
    $envNote = "env-vars.txt 담음 — $(@($lines).Count)개"
}

Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'restore.ps1') -Destination $OutDir -Force
Set-Content -LiteralPath (Join-Path $OutDir 'MANIFEST.txt') -Encoding UTF8 -Value (@(
    "PC 이전 묶음 — $(Get-Date -Format 'yyyy-MM-dd HH:mm') — $env:COMPUTERNAME",
    '', '담은 것:') + ($plan | ForEach-Object { '  ' + $_.Rel }) + ($gitJobs | ForEach-Object { '  ' + $_.Out }) + @(
    '', $mcpNote, $envNote, '',
    '새 PC 에서: 이 폴더 안의 restore.ps1 -DryRun 부터 (사용법은 그 파일 머리말).'))

# ── 압축 → 시험 → 평문 폴더 지우기 ─────────────────────────────────────
if ($tool) {
    if ($tool -eq 'bz') {
        Push-Location -LiteralPath $OutDir
        try { & $bz c -fmt:7z -l:3 -r -y "-p:$password" $archive * | Out-Null } finally { Pop-Location }
        $made = $LASTEXITCODE
        & $bz t "-p:$password" $archive | Out-Null
    } else {
        & $sz a -t7z -mx=3 -mhe=on "-p$password" $archive (Join-Path $OutDir '*') | Out-Null
        $made = $LASTEXITCODE
        & $sz t "-p$password" $archive | Out-Null
    }
    $tested = $LASTEXITCODE
    $password = $null; $p1 = $null; $p2 = $null
    if ($made -ne 0) { throw "압축 실패(종료 코드 $made) — 평문 폴더는 남아 있습니다: $OutDir" }
    if ($tested -ne 0) { throw "압축은 만들었지만 시험 풀기에 실패했습니다(종료 코드 $tested). 평문 폴더를 남겨 둡니다: $OutDir" }
    Write-Host "만듦: $archive ($(Get-SizeMB $archive) MB) — 시험 풀기 통과" -ForegroundColor Green
    if ($KeepFolder) { Write-Warning "평문 폴더를 남겼습니다(-KeepFolder). 옮긴 뒤 꼭 지우세요: $OutDir" }
    else {
        cmd /c rd /s /q "\\?\$OutDir"
        Write-Host '평문 폴더는 지웠습니다.' -ForegroundColor Green
    }
    Write-Host '암호를 잃으면 풀 수 없습니다(파일 이름까지 암호화). .7z 는 회사가 허용하는 방법으로만 옮기세요.' -ForegroundColor Yellow
} else {
    Write-Warning "암호 없이 만들었습니다(-NoEncrypt): $OutDir — 대화 기록·설정에 비밀이 들어 있을 수 있으니 옮긴 뒤 지우세요."
}
Write-Host '완료' -ForegroundColor Green
