<#
  PC 이전 묶음 풀어 넣기 (새 PC 에서)
  ----------------------------------
  pack.ps1 이 만든 .7z 를 반디집·7-Zip 으로 푼 뒤, 풀린 폴더 안에서 실행한다.
  이미 있는 것은 덮어쓰지 않는다 — 파일이 겹치면 <이름>.imported 로 옆에 둔다.

      powershell -ExecutionPolicy Bypass -File restore.ps1 -DryRun      무엇을 어디에 넣을지만 본다 (먼저 이것부터)
      powershell -ExecutionPolicy Bypass -File restore.ps1              Claude Code 기록 · 키트 설정을 넣는다
      powershell -ExecutionPolicy Bypass -File restore.ps1 -SetEnv      + 환경변수 값을 사용자 환경변수로 넣는다
      powershell -ExecutionPolicy Bypass -File restore.ps1 -MergeMcp    + MCP 서버를 ~\.claude.json 에 "없는 것만" 더한다

  먼저 할 것
    - Claude Code 를 설치하고 한 번 실행해 로그인한다(~\.claude 가 생긴다).
    - 키트를 설치한다(설치 파일 또는 소스). 키트 위치가 기본(%LOCALAPPDATA%\WorkKit)이 아니면 -KitDir 로 알려 준다.
    - 작업 저장소를 clone 한다(서브모듈이 있으면 --recurse-submodules). 저장소 작업물은 자동으로 넣지 않고 명령만 알려 준다.

  Claude Code 기록은 "작업 폴더 경로"로 찾는다(C:\work\app → C--work-app). 새 PC 에서 경로가 다르면
  -ProjectMap "C--work-app=D--src-app" 로 폴더 이름을 바꿔 넣는다. 규칙: 영숫자가 아닌 글자를 '-' 로.

  끝난 뒤
    - 묶음 폴더를 지운다(대화 기록·토큰이 평문으로 들어 있다).
    - 키트의 메일 비밀번호 등 Windows 가 PC 에 묶어 암호화한 값은 옮겨 와도 풀리지 않는다 — 「메일·계정 설정」(setup_gui.py) 에서 다시 넣는다.
    - Claude Code 의 settings.json(훅)·plugins 는 새 PC 에서 직접 설정·설치한다.
#>
[CmdletBinding()]
param(
    [string] $Source = '',
    [string] $ProjectMap = '',
    [string] $KitDir = (Join-Path $env:LOCALAPPDATA 'WorkKit'),
    [string] $ClaudeDir = (Join-Path $env:USERPROFILE '.claude'),
    [string] $ClaudeJson = (Join-Path $env:USERPROFILE '.claude.json'),
    [switch] $SetEnv,
    [switch] $MergeMcp,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'
if (-not $Source) { $Source = $PSScriptRoot }   # 매개변수 기본값 안의 $PSScriptRoot 는 비어 있을 수 있다
$map = @{}
foreach ($pair in ($ProjectMap -split '[,;]' | Where-Object { $_ })) {
    $kv = $pair -split '=', 2
    if ($kv.Count -ne 2 -or -not $kv[0].Trim() -or -not $kv[1].Trim()) { throw "-ProjectMap 형식 오류: '$pair' (이전=새이름)" }
    $map[$kv[0].Trim()] = $kv[1].Trim()
}

function Copy-Tree([string] $src, [string] $dst) {
    # 없는 파일·더 새로운 파일만 (/XO) — 새 PC 에서 이미 쓰던 것을 옛것으로 덮지 않는다
    if ($DryRun) { Write-Host "  [DryRun] $src → $dst"; return }
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    robocopy $src $dst /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Write-Warning "robocopy 실패(코드 $LASTEXITCODE): $src" }
}
function Copy-KeepExisting([string] $src, [string] $dst) {
    # 파일 하나 — 이미 있으면 덮지 않고 .imported 로 옆에 둔다
    if (Test-Path -LiteralPath $dst) {
        Write-Host "  이미 있음 → $(Split-Path $dst -Leaf).imported 로 둠 (직접 합치세요)"
        $dst = "$dst.imported"
    } else { Write-Host "  넣음 → $dst" }
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}

# 1) Claude Code 기록·설정
$pack = Join-Path $Source 'claude'
if (Test-Path -LiteralPath $pack) {
    if (-not (Test-Path -LiteralPath $ClaudeDir)) {
        Write-Warning "Claude Code 폴더가 없습니다: $ClaudeDir — Claude Code 를 설치하고 한 번 로그인한 뒤 하는 편이 안전합니다."
        if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null }
    }
    Write-Host '[Claude Code 대화 기록]' -ForegroundColor Cyan
    foreach ($d in Get-ChildItem -LiteralPath (Join-Path $pack 'projects') -Directory -ErrorAction SilentlyContinue) {
        $name = if ($map.ContainsKey($d.Name)) { $map[$d.Name] } else { $d.Name }
        $n = @(Get-ChildItem -LiteralPath $d.FullName -Filter *.jsonl -File -ErrorAction SilentlyContinue).Count
        Write-Host ("  {0} → {1}  (대화 {2}개)" -f $d.Name, $name, $n)
        Copy-Tree $d.FullName (Join-Path $ClaudeDir "projects\$name")
    }
    foreach ($n in 'skills', 'hooks', 'plans', 'agents', 'commands', 'file-history') {
        $src = Join-Path $pack $n
        if (Test-Path -LiteralPath $src) { Write-Host "[$n]" -ForegroundColor Cyan; Copy-Tree $src (Join-Path $ClaudeDir $n) }
    }
    Write-Host '[Claude Code 지침 파일]' -ForegroundColor Cyan
    foreach ($f in Get-ChildItem -LiteralPath $pack -File) { Copy-KeepExisting $f.FullName (Join-Path $ClaudeDir $f.Name) }
}

# 2) MCP 서버 — -MergeMcp 일 때만, 없는 서버만
$mcp = Join-Path $Source 'mcpServers.json'
if (Test-Path -LiteralPath $mcp) {
    Write-Host '[MCP 서버]' -ForegroundColor Cyan
    $incoming = Get-Content -LiteralPath $mcp -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $MergeMcp) { Write-Host "  $(@($incoming.PSObject.Properties).Count)개 있음 — 넣으려면 -MergeMcp (경로가 옛 PC 기준이면 넣은 뒤 고치세요)" }
    elseif (-not (Test-Path -LiteralPath $ClaudeJson)) { Write-Warning "$ClaudeJson 이 없습니다. Claude Code 를 한 번 실행해 로그인한 뒤 다시 하세요." }
    else {
        $j = Get-Content -LiteralPath $ClaudeJson -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not ($j.PSObject.Properties.Name -contains 'mcpServers') -or -not $j.mcpServers) {
            $j | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) -Force
        }
        $added = @()
        foreach ($s in $incoming.PSObject.Properties) {
            if ($j.mcpServers.PSObject.Properties.Name -contains $s.Name) { Write-Host "  이미 있음(건너뜀): $($s.Name)" }
            else { $j.mcpServers | Add-Member -NotePropertyName $s.Name -NotePropertyValue $s.Value; $added += $s.Name }
        }
        if ($added.Count -and -not $DryRun) {
            $bak = "$ClaudeJson.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            Copy-Item -LiteralPath $ClaudeJson -Destination $bak
            $j | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $ClaudeJson -Encoding UTF8
            Write-Host "  더함: $($added -join ', ')   (백업: $bak)"
        } elseif ($added.Count) { Write-Host "  [DryRun] 더할 것: $($added -join ', ')" }
    }
}

# 3) 키트 설정·내 자동화
$kl = Join-Path $Source 'kit-local'
if (Test-Path -LiteralPath $kl) {
    Write-Host "[키트 설정 → $KitDir]" -ForegroundColor Cyan
    if (-not (Test-Path -LiteralPath $KitDir)) { Write-Warning "키트 폴더가 없습니다 — 키트를 먼저 설치하거나 -KitDir 로 위치를 주세요: $KitDir" }
    else {
        foreach ($f in Get-ChildItem -LiteralPath $kl -Recurse -File) {
            Copy-KeepExisting $f.FullName (Join-Path $KitDir $f.FullName.Substring($kl.Length + 1))
        }
        Write-Host '  허브를 다시 켜면 켜 둔 자동화가 돌아온다. 메일 비밀번호는 「메일·계정 설정」에서 다시 넣는다.' -ForegroundColor Yellow
    }
}

# 4) 환경변수
$envFile = Join-Path $Source 'env-vars.txt'
if (Test-Path -LiteralPath $envFile) {
    Write-Host '[환경변수]' -ForegroundColor Cyan
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        $k, $v = $line -split '=', 2
        if (-not $k -or -not $v) { continue }
        $cur = [Environment]::GetEnvironmentVariable($k, 'User')
        if ($cur) { Write-Host "  이미 있음(건너뜀): $k" }
        elseif (-not $SetEnv) { Write-Host "  $k — 넣으려면 -SetEnv" }
        elseif ($DryRun) { Write-Host "  [DryRun] 넣을 것: $k" }
        else { [Environment]::SetEnvironmentVariable($k, $v, 'User'); Write-Host "  넣음: $k" }
    }
}

# 5) 따로 챙긴 파일(extra) — 원래 위치만 알려 준다
$ex = Join-Path $Source 'extra'
if (Test-Path -LiteralPath $ex) {
    Write-Host '[따로 챙긴 것] 자동으로 넣지 않습니다. 원래 위치:' -ForegroundColor Cyan
    foreach ($o in Get-ChildItem -LiteralPath $ex -Filter '*._origin.txt' -File) {
        $item = $o.FullName.Substring(0, $o.FullName.Length - '._origin.txt'.Length)
        Write-Host "  $item  →  $(Get-Content -LiteralPath $o.FullName -Encoding UTF8 | Select-Object -First 1)"
    }
}

# 6) 저장소 작업물 — clone 한 뒤에 넣을 명령만 알려 준다(저장소 위치가 다를 수 있어서)
$rp = Join-Path $Source 'repos'
if (Test-Path -LiteralPath $rp) {
    Write-Host '[저장소 작업물] 자동으로 넣지 않습니다. clone(--recurse-submodules) 한 뒤 아래를 실행하세요 (위치가 다르면 경로만 바꿔서):' -ForegroundColor Cyan
    foreach ($d in Get-ChildItem -LiteralPath $rp -Directory) {
        $originFile = Join-Path $d.FullName '_origin.txt'
        $repo = if (Test-Path -LiteralPath $originFile) { Get-Content -LiteralPath $originFile -Encoding UTF8 | Select-Object -First 1 } else { "<$($d.Name) 위치>" }
        Write-Host "  $repo"
        if (Test-Path -LiteralPath (Join-Path $d.FullName 'files')) {
            Write-Host "    새 파일·로컬 설정:  robocopy `"$($d.FullName)\files`" `"$repo`" /E /XC /XN /XO"
        }
        foreach ($p in @(Get-ChildItem -LiteralPath (Join-Path $d.FullName 'changes') -Filter *.patch -ErrorAction SilentlyContinue)) {
            $sub = if ($p.BaseName -eq '_root') { '' } else { '\' + ($p.BaseName -replace '__', '\') }
            Write-Host "    수정분:            git -C `"$repo$sub`" apply `"$($p.FullName)`""
        }
        foreach ($b in @(Get-ChildItem -LiteralPath (Join-Path $d.FullName 'bundles') -Filter *.bundle -ErrorAction SilentlyContinue)) {
            $sub = if ($b.BaseName -eq '_root') { '' } else { '\' + ($b.BaseName -replace '__', '\') }
            Write-Host "    로컬 브랜치:        git -C `"$repo$sub`" fetch `"$($b.FullName)`" 'refs/heads/*:refs/heads/*'"
        }
    }
}

Write-Host ''
if ($DryRun) { Write-Host '-DryRun: 아무것도 바꾸지 않았습니다.' -ForegroundColor Yellow }
else {
    Write-Host '완료. claude --resume 으로 대화가 보이는지 확인하세요.' -ForegroundColor Green
    Write-Host "다 넣었으면 이 묶음 폴더를 지우세요(평문): $Source" -ForegroundColor Yellow
}
