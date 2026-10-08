<#
  작업 인박스 워커 — inbox/jobs 의 대기 작업을 claude -p 로 실행한다.

  메일 게이트웨이(mail-gateway.py)가 지시 메일을 inbox/jobs 에 넣으면, 이 PC 가 그 지시를 대신 실행한다.
  폰에서 PC 로 직접 붙을 수 없는 사내망에서도 메일만 닿으면 일을 맡길 수 있다.

  설정은 저장소 맨 위 config.local.json 의 dispatch 갈래(견본 config.example.json):
    enabled      ... false 면 아무것도 실행하지 않고 끝낸다.
    read_tools   ... 읽기 지시(#c)에 줄 도구 — 기본은 읽기 전용 목록.
    extra_tools  ... 잡이 요청할 수 있는 도구 상한에 더할 이름(예: 이슈 조회용 MCP 도구). 기본 도구 밖은 여기 있어야 한다.
    timeout_sec · keep_jobs ... 작업 하나의 제한 시간 · 남겨 둘 끝난 작업 수.

  매크로 허브 워처 규약을 따른다(허브가 이 파일들만 보고 상태를 표시한다):
    state.json   ... 30초마다 갱신. 파일 수정 시각이 곧 "살아있음" 신호다.
    paused.flag  ... 있으면 실행을 멈춘다.
    notify.jsonl ... 완료 알림 큐. 허브가 읽고 지운다.

  주의:
   - 다른 프로그램이 읽는 JSON 은 BOM 없는 UTF-8 로 쓴다(BOM 이 붙으면 못 읽는 파서가 있다).
   - 프롬프트는 인자가 아니라 stdin(파일)으로 넘긴다. 따옴표·괄호·%가 섞여도 안전하다.
   - 이 파일 자체는 한글이 있으므로 UTF-8 BOM 으로 저장해야 PS 5.1 이 제대로 읽는다.
#>

[CmdletBinding()]
param(
    # 한 번만 돌고 끝낸다(진단용). 기본은 상주.
    [switch] $Once,
    # 하는 일 없는 표식 — 허브 서비스(svc_inbox_worker)가 붙여 띄워, 이 키트가 띄운 워커만 알아보고 끈다
    [switch] $KitService
)

$ErrorActionPreference = 'Stop'

# 대소문자만 다른 같은 이름의 환경변수(OneDrive/ONEDRIVE)가 둘이면 PS 5.1 Start-Process 가
# "항목이 이미 추가되었습니다" 로 죽어 claude 를 못 띄운다(2026-10-06 실측 — 허브가 넘긴 환경). 하나만 남긴다.
for ($i = 0; $i -lt 5; $i++) {
    $dups = @([Environment]::GetEnvironmentVariables('Process').Keys | ForEach-Object { [string]$_ } |
              Group-Object { $_.ToLowerInvariant() } | Where-Object { $_.Count -gt 1 })
    if (-not $dups) { break }
    foreach ($g in $dups) {
        $name = $g.Group[0]; $val = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        if ($null -eq [Environment]::GetEnvironmentVariable($name, 'Process')) { [Environment]::SetEnvironmentVariable($name, $val, 'Process') }
    }
}

$root       = Split-Path -Parent $MyInvocation.MyCommand.Path
$inbox      = Join-Path $root 'inbox'
$jobsDir    = Join-Path $inbox 'jobs'
$logsDir    = Join-Path $inbox 'logs'
$stateFile  = Join-Path $inbox 'state.json'
$pauseFile  = Join-Path $inbox 'paused.flag'
$notifyFile = Join-Path $inbox 'notify.jsonl'
$workerLog  = Join-Path $inbox 'worker.log'
$configFile = Join-Path $root 'config.local.json'     # 키트 공통 설정 — dispatch 갈래만 본다

foreach ($d in @($inbox, $jobsDir, $logsDir)) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Log([string] $msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    try {
        # 로그가 끝없이 자라지 않게 1MB 넘으면 뒤쪽 절반만 남긴다
        if ((Test-Path -LiteralPath $workerLog) -and ((Get-Item -LiteralPath $workerLog).Length -gt 1MB)) {
            $keep = @(Get-Content -LiteralPath $workerLog -Tail 2000)
            [System.IO.File]::WriteAllLines($workerLog, $keep, $Utf8NoBom)
        }
        Add-Content -LiteralPath $workerLog -Value $line -Encoding UTF8
    } catch { }
    Write-Verbose $line
}

function Read-JsonFile([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        $raw = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
        if (-not $raw.Trim()) { return $null }
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Write-JsonFile([string] $path, $obj) {
    $json = $obj | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($path, $json, $Utf8NoBom)
}

function Get-InboxConfig {
    $all = Read-JsonFile $configFile
    $cfg = if ($all) { $all.dispatch } else { $null }
    $allowed = @('Read', 'Glob', 'Grep', 'Bash(git log:*)', 'Bash(git status:*)', 'Bash(git diff:*)', 'Bash(git show:*)')
    $timeout = 900
    $keep = 200
    $extra = @()
    $enabled = $false
    if ($cfg) {
        if ($cfg.read_tools)  { $allowed = @($cfg.read_tools) }
        if ($cfg.timeout_sec) { $timeout = [int]$cfg.timeout_sec }
        if ($cfg.keep_jobs)   { $keep = [int]$cfg.keep_jobs }
        # 도구 상한에 더하는 것은 이름(괄호 없는 기본 이름)만 받는다
        if ($cfg.extra_tools) { $extra = @($cfg.extra_tools | ForEach-Object { [string]$_ } | Where-Object { $_ -match '^[A-Za-z0-9_]+$' }) }
        $enabled = [bool]$cfg.enabled
    }
    return [pscustomobject]@{ AllowedTools = $allowed; TimeoutSec = $timeout; KeepJobs = $keep; ExtraTools = $extra; Enabled = $enabled }
}

# 오래된 작업 정리(개수 제한) — 정리하지 않으면 작업이 계속 쌓이고, 게이트웨이가 20초마다 전부 훑어 점점 느려진다.
# 끝난 작업(done/error/canceled)만 지우고, 대기·실행 중인 것은 개수와 무관하게 남긴다.
function Remove-OldJobs {
    $keep = (Get-InboxConfig).KeepJobs
    $files = @(Get-ChildItem -LiteralPath $jobsDir -Filter '*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
    if ($files.Count -le $keep) { return }
    $removed = 0
    foreach ($f in ($files | Select-Object -Skip $keep)) {
        $j = Read-JsonFile $f.FullName
        if ($j -and $j.status -in @('done', 'error', 'canceled')) {
            Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
            $removed++
        }
    }
    if ($removed -gt 0) { Write-Log "오래된 작업 $removed건 정리 (최근 $keep건 유지)" }
}

function Set-WorkerState([string] $state, [string] $detail, [string] $current) {
    Write-JsonFile $stateFile ([pscustomobject]@{
        state   = $state
        detail  = $detail
        current = $current
        ts      = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    })
}

function Add-Notify([string] $title, [string] $text, [string] $level) {
    $o = [pscustomobject]@{
        ts    = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        level = $level
        title = $title
        text  = $text
    }
    try {
        $line = ($o | ConvertTo-Json -Compress -Depth 5)
        Add-Content -LiteralPath $notifyFile -Value $line -Encoding UTF8
    } catch { }
}

# 대기 중인 작업 하나(가장 오래된 것). 파일명이 시각순이라 이름 오름차순이 곧 접수순이다.
function Stop-ProcessTree($p) {
    # 프로세스 트리째 끝낸다(Kill() 은 claude 본체만 끝내고 node·도구 자식을 남긴다).
    # taskkill 은 이미 끝난 자식에 대해 stderr 로 경고를 내는데, 이 스크립트는 ErrorActionPreference=Stop 이라
    # PS 5.1 이 그 경고를 오류로 바꿔 catch 로 튄다 — 멈춤이 '오류' 로 끝난다. 여기서만 삼킨다.
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null } catch { }
    finally { $ErrorActionPreference = $old }
    try { if (-not $p.HasExited) { $p.Kill() } } catch { }
}

function Get-NextJob {
    $files = @(Get-ChildItem -LiteralPath $jobsDir -Filter '*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name)
    foreach ($f in $files) {
        $job = Read-JsonFile $f.FullName
        if ($job -and $job.status -eq 'queued') {
            return [pscustomobject]@{ Path = $f.FullName; Job = $job }
        }
    }
    return $null
}

function Count-Queued {
    $n = 0
    $files = @(Get-ChildItem -LiteralPath $jobsDir -Filter '*.json' -File -ErrorAction SilentlyContinue)
    foreach ($f in $files) {
        $job = Read-JsonFile $f.FullName
        if ($job -and $job.status -eq 'queued') { $n++ }
    }
    return $n
}

# 잡 파일이 들고 온 도구 목록·세션 ID 를 명령줄에 붙이기 전에 검증한다.
# 잡 JSON 은 inbox\jobs 에 쓸 수 있는 누구나 만들 수 있고, 값이 그대로 claude 인자가 되므로
# 따옴표가 든 값은 인자 주입이 되고, 목록에 없는 도구는 권한 확대가 된다.
# 자기 도구 목록을 실어 올 수 있는 것은 메일 게이트웨이(source=mail)뿐이다.
# 상한은 기본 도구 + 설정의 dispatch.extra_tools(예: 이슈 조회용 MCP 도구 이름)다.
$script:ToolCeiling = @('Read', 'Glob', 'Grep', 'Edit', 'Write', 'NotebookEdit', 'Bash')
$script:MailSources = @('mail')
$script:ToolPattern = '^[A-Za-z0-9_]+(\([^"''`\r\n]*\))?$'

# 통과하면 $null, 막으면 사유 문자열
function Test-JobInputs($job, $cfg) {
    if ($job.resume_id -and ([string]$job.resume_id) -notmatch '^[0-9a-fA-F-]{36}$') {
        return 'resume_id 형식이 올바르지 않습니다.'
    }
    if ($job.allowed_tools) {
        if ($job.source -notin $script:MailSources) {
            return "이 출처($($job.source))의 작업은 자기 도구 목록을 지정할 수 없습니다."
        }
        foreach ($t in @($job.allowed_tools)) {
            $t = [string]$t
            if ($t -notmatch $script:ToolPattern) { return "허용되지 않는 도구 표기입니다: $t" }
            $base = ($t -split '\(', 2)[0]
            if ($base -notin $script:ToolCeiling -and $base -notin @($cfg.ExtraTools)) { return "허용 범위를 벗어난 도구입니다: $base" }
        }
    }
    # 거부 목록은 권한을 넓히지 못하므로 상한은 필요 없지만, 값이 명령줄에 붙으니 표기는 같은 규칙으로 거른다
    foreach ($t in @($job.disallowed_tools)) {
        if ($null -eq $t) { continue }
        if ([string]$t -notmatch $script:ToolPattern) { return "허용되지 않는 거부 규칙 표기입니다: $t" }
    }
    # 사진 폴더(게이트웨이 attach_dir)도 --add-dir 로 명령줄에 붙는다 — 인박스 사진 폴더 아래만, 따옴표 없이
    if ($job.attach_dir) {
        $dir = [string]$job.attach_dir
        $att = Join-Path (Split-Path -Parent $jobsDir) 'attachments'
        try { $full = [System.IO.Path]::GetFullPath($dir); $att = [System.IO.Path]::GetFullPath($att) } catch { return 'attach_dir 형식이 올바르지 않습니다.' }
        if ($dir.Contains('"') -or -not $full.StartsWith($att + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            return 'attach_dir 는 인박스 사진 폴더(inbox\attachments) 아래여야 합니다.'
        }
    }
    return $null
}

function Invoke-Job($entry) {
    $path = $entry.Path
    $job  = $entry.Job
    $id   = [string]$job.id
    $cfg  = Get-InboxConfig

    # 집어가기 직전에 한 번 더 확인한다 — 그사이 화면에서 취소했을 수 있다
    $fresh = Read-JsonFile $path
    if (-not $fresh -or $fresh.status -ne 'queued') {
        Write-Log "건너뜀 $id (상태가 queued 가 아님)"
        return
    }

    # 시작 전에 이미 멈춤 요청이 왔으면(폰 대화방 '멈춤') 돌리지 않는다 — 게이트웨이가 'done' 회신으로 알린다
    $stopFile = Join-Path $jobsDir "$id.stop"
    if (Test-Path -LiteralPath $stopFile) {
        Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
        $job.status = 'done'
        $job.result = '멈췄습니다 — 시작하기 전에 멈춤 요청을 받아 실행하지 않았습니다.'
        $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        Write-JsonFile $path $job
        Write-Log "멈춤(시작 전) $id"
        return
    }

    $reject = Test-JobInputs $job $cfg
    if ($reject) {
        $job.status = 'error'
        $job.error = "작업을 거부했습니다: $reject"
        $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        Write-JsonFile $path $job
        Write-Log "거부 $id — $reject"
        return
    }

    if (-not (Test-Path -LiteralPath $job.workdir)) {
        $job.status = 'error'
        $job.error = "작업 폴더를 찾을 수 없습니다: $($job.workdir)"
        $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        Write-JsonFile $path $job
        Write-Log "실패 $id — 작업 폴더 없음"
        return
    }

    $job.status = 'running'
    $job.started_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Write-JsonFile $path $job
    Set-WorkerState 'busy' "실행 중: $id" $id
    if ($job.resume_id) {
        Write-Log "실행 시작 $id (폴더: $($job.workdir), 세션 $($job.resume_id) 이어받기)"
    } else {
        Write-Log "실행 시작 $id (폴더: $($job.workdir))"
    }

    $promptFile = Join-Path $logsDir "$id.prompt.txt"
    $outFile    = Join-Path $logsDir "$id.out.json"
    $errFile    = Join-Path $logsDir "$id.err.txt"

    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        [System.IO.File]::WriteAllText($promptFile, [string]$job.prompt, $Utf8NoBom)

        # 도구 화이트리스트. 값에 괄호·별표가 있어 각각 따옴표로 감싼다.
        # 작업이 자기 도구 목록을 들고 오면 그것을 쓴다(메일 게이트웨이의 쓰기 태그 'cw').
        # 없으면 config.local.json 의 dispatch.read_tools(읽기 전용 기본값).
        $tools = if ($job.allowed_tools) { @($job.allowed_tools) } else { $cfg.AllowedTools }
        $toolArgs = (($tools | ForEach-Object { '"' + $_ + '"' }) -join ' ')

        # 메일 게이트웨이가 이전 잡에 대한 답장임을 알아채면 resume_id 를 실어 보낸다.
        # 새 세션 대신 그 세션에 그대로 이어붙여, 폰에서 답장을 주고받으며 맥락을 유지할 수 있다.
        $resumeArg = ''
        if ($job.resume_id) { $resumeArg = "--resume $($job.resume_id) " }
        # 작업이 거부 규칙을 들고 오면(이슈 처리의 네트워크 명령 차단 등) 그대로 넘긴다
        $denyArgs = ''
        if ($job.disallowed_tools) {
            $denyArgs = ' --disallowedTools ' + ((@($job.disallowed_tools) | ForEach-Object { '"' + $_ + '"' }) -join ' ')
        }
        # 메일 대화 모드(chat): 사람에게 물을 자리에서 AskUserQuestion 대신 ```choices 블록을 쓰게 하는 규칙을 덧붙인다.
        # 게이트웨이가 그 블록을 체크박스 질문 메일로 바꾸고, 번호 답을 풀어 --resume 으로 이어 준다(chat-protocol.md).
        $chatArg = ''
        if ($job.chat) {
            $proto = Join-Path $root 'chat-protocol.md'
            if (Test-Path -LiteralPath $proto) { $chatArg = ' --append-system-prompt-file "' + $proto + '"' }
        }
        # 폰이 지시와 함께 보낸 사진 폴더(게이트웨이 attach_dir) — 작업 폴더 밖이라 --add-dir 로 읽기를 열어 준다
        $addDirArg = ''
        if ($job.attach_dir -and (Test-Path -LiteralPath $job.attach_dir)) { $addDirArg = '--add-dir "' + $job.attach_dir + '" ' }
        $argLine  = "-p ${resumeArg}${addDirArg}--output-format json --allowedTools $toolArgs$denyArgs$chatArg"

        $p = Start-Process -FilePath 'claude' -ArgumentList $argLine `
                -WorkingDirectory $job.workdir `
                -RedirectStandardInput $promptFile `
                -RedirectStandardOutput $outFile `
                -RedirectStandardError $errFile `
                -NoNewWindow -PassThru

        # 한 번에 TimeoutSec 를 통째로 기다리면 그동안 state.json 이 갱신되지 않아
        # 150초만 넘어도 허브 트레이가 워커를 "멈춤"으로 표시한다. 30초씩 끊어 기다리며 상태를 갱신한다.
        # 2초마다 멈춤 요청(jobs\<id>.stop — 메일 게이트웨이가 폰 대화방 '멈춤' 을 받으면 만든다)도 본다.
        $deadline = (Get-Date).AddSeconds($cfg.TimeoutSec)
        $finished = $false
        $stopped = $false
        $beat = Get-Date
        while ($true) {
            if ($p.WaitForExit(2000)) { $finished = $true; break }
            if (Test-Path -LiteralPath $stopFile) { $stopped = $true; break }
            if ((Get-Date) -ge $deadline) { break }
            if (((Get-Date) - $beat).TotalSeconds -ge 30) { Set-WorkerState 'busy' "실행 중: $id" $id; $beat = Get-Date }
        }
        $sw.Stop()

        if ($stopped) {
            Stop-ProcessTree $p
            Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
            $job.status = 'done'
            $job.result = '멈췄습니다 — 폰에서 멈춤을 받아 하던 일을 중간에 끊었습니다. 이어서 하려면 다시 말해 주세요.'
            $job.duration_ms = $sw.Elapsed.TotalMilliseconds
            $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            Write-JsonFile $path $job
            Write-Log "멈춤 $id ($([int]$sw.Elapsed.TotalSeconds)초에 끊음)"
            return
        }

        if (-not $finished) {
            # Kill() 은 claude 본체만 끝내고 node·도구 자식 프로세스는 남긴다 — 프로세스 트리째 종료한다
            Stop-ProcessTree $p
            $job.status = 'error'
            $job.error = "제한 시간($($cfg.TimeoutSec)초)을 넘겨 중단했습니다."
            $job.duration_ms = $sw.Elapsed.TotalMilliseconds
            $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            Write-JsonFile $path $job
            Write-Log "타임아웃 $id"
            Add-Notify '작업 인박스' "지시가 제한 시간을 넘겨 중단됐습니다." 'Warning'
            return
        }

        $res = Read-JsonFile $outFile
        if (-not $res) {
            $stderr = ''
            if (Test-Path -LiteralPath $errFile) {
                $stderr = ([System.IO.File]::ReadAllText($errFile, [System.Text.Encoding]::UTF8)).Trim()
            }
            $job.status = 'error'
            $job.error = if ($stderr) { $stderr } else { '실행 결과를 읽지 못했습니다.' }
            $job.duration_ms = $sw.Elapsed.TotalMilliseconds
            $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            Write-JsonFile $path $job
            Write-Log "실패 $id — 출력 파싱 불가"
            Add-Notify '작업 인박스' '지시 실행에 실패했습니다.' 'Warning'
            return
        }

        $job.result      = [string]$res.result
        $job.cost_usd    = $res.total_cost_usd
        $job.duration_ms = $res.duration_ms
        $job.denials     = @($res.permission_denials)
        $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

        # 이 실행의 세션 ID. 나중에 `claude --resume <id>` 로 그 대화를 이어받을 수 있다
        # (폰에서 던져 놓고 PC 앞에서 맥락 그대로 이어서 작업하는 용도).
        # 작업 JSON 을 만든 쪽에 없는 속성이라 Add-Member 로 붙인다.
        $job | Add-Member -NotePropertyName 'session_id' -NotePropertyValue ([string]$res.session_id) -Force

        if ($res.is_error) {
            $job.status = 'error'
            $job.error = '실행 중 오류가 발생했습니다.'
            Write-Log "오류 응답 $id"
            Add-Notify '작업 인박스' '지시 실행 중 오류가 발생했습니다.' 'Warning'
        } else {
            $job.status = 'done'
            Write-Log ("완료 {0} ({1}초)" -f $id, [int]$sw.Elapsed.TotalSeconds)
            $head = [string]$job.result
            if ($head.Length -gt 90) { $head = $head.Substring(0, 90) + '…' }
            Add-Notify '작업 인박스 · 완료' $head 'Info'
        }
        Write-JsonFile $path $job

    } catch {
        $sw.Stop()
        $job.status = 'error'
        $job.error = $_.Exception.Message
        $job.duration_ms = $sw.Elapsed.TotalMilliseconds
        $job.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        try { Write-JsonFile $path $job } catch { }
        Write-Log "예외 $id — $($_.Exception.Message)"
        Add-Notify '작업 인박스' '지시 실행 중 예외가 발생했습니다.' 'Error'
    } finally {
        # 프롬프트 원문은 job JSON 에도 있으므로 임시 파일은 지운다
        foreach ($f in @($promptFile, $outFile, $errFile)) {
            if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
        }
    }
}

# ------------------------------------------------------------------ 진입

# 메일로 일 맡기기가 꺼져 있으면 아무것도 실행하지 않는다(남아 있는 대기 작업도 그대로 둔다).
if (-not (Get-InboxConfig).Enabled) {
    Write-Log '메일로 일 맡기기(dispatch.enabled)가 꺼져 있어 아무것도 하지 않고 끝냅니다.'
    Set-WorkerState 'disabled' '꺼짐 (config.local.json 의 dispatch.enabled)' $null
    return
}

# 허브가 죽은 워커를 다시 띄우므로 중복 방지가 필수다.
# AbandonedMutexException 은 "앞 프로세스가 죽으면서 남긴 것"이라 획득 성공으로 처리해야 한다
# (안 그러면 이 블록이 통째로 건너뛰어져 중복방지가 무력화된다 — 트레이에서 겪은 함정).
$mutex = New-Object System.Threading.Mutex($false, 'Local\WorkKitInboxWorker')
$acquired = $false
try {
    $acquired = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $acquired = $true
}
if (-not $acquired) {
    Write-Log '이미 실행 중이라 종료합니다.'
    return
}

Write-Log '워커 시작'
$lastState = [datetime]::MinValue

# 앞 워커가 작업 도중 죽었으면(PC 재부팅·강제 종료) 그 작업이 영원히 running 으로 남고 메일 회신도 오지 않는다.
# 작업은 이 워커만 실행하고 위 뮤텍스가 워커를 하나로 묶으므로, 지금 시점의 running 은 전부 고아다.
# error 로 돌려 두면 화면에 실패로 보이고 게이트웨이가 그 결과(실패 사유)를 회신한다.
foreach ($f in @(Get-ChildItem -LiteralPath $jobsDir -Filter '*.json' -File -ErrorAction SilentlyContinue)) {
    $orphan = Read-JsonFile $f.FullName
    if ($orphan -and $orphan.status -eq 'running') {
        $orphan.status = 'error'
        $orphan.error = '워커가 다시 시작되어 실행 중이던 작업이 중단됐습니다. 필요하면 다시 보내세요.'
        $orphan.finished_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        Write-JsonFile $f.FullName $orphan
        Write-Log "고아 작업 정리 $($orphan.id) (running → error)"
        Add-Notify '작업 인박스' '중단된 지시를 실패로 정리했습니다.' 'Warning'
    }
}

try {
    while ($true) {
        $paused = Test-Path -LiteralPath $pauseFile
        # 도는 중에 dispatch.enabled 를 끄면 끝내지 않고 쉰다(끝내면 허브가 다시 띄우기를 되풀이한다)
        $disabled = -not (Get-InboxConfig).Enabled
        if ($disabled) { $paused = $true }

        if (-not $paused) {
            $entry = Get-NextJob
            if ($entry) {
                Invoke-Job $entry
                Remove-OldJobs
                $lastState = [datetime]::MinValue   # 처리 직후 상태를 즉시 갱신
            }
        }

        # 30초마다 살아있음을 알린다(허브는 이 파일의 수정 시각을 본다)
        if (((Get-Date) - $lastState).TotalSeconds -ge 30) {
            if ($disabled) {
                Set-WorkerState 'disabled' '꺼짐 (config.local.json 의 dispatch.enabled)' $null
            } elseif ($paused) {
                Set-WorkerState 'paused' '일시정지 중' $null
            } else {
                $n = Count-Queued
                if ($n -gt 0) {
                    Set-WorkerState 'idle' "대기 중인 지시 $n건" $null
                } else {
                    Set-WorkerState 'idle' '대기 중' $null
                }
            }
            $lastState = Get-Date
        }

        if ($Once) { break }
        Start-Sleep -Seconds 3
    }
} finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
    Write-Log '워커 종료'
}
