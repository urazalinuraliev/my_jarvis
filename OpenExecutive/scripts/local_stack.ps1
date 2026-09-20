<#
.SYNOPSIS
    Start, inspect and stop the local Open Executive stack on Windows.

.DESCRIPTION
    Runs the API, the Next.js UI and an ngrok tunnel, and points the Telegram
    webhook at that tunnel. The processes are started detached, so they keep
    running after the terminal (or the Claude Code session) that launched them
    goes away - `-Action stop` is what ends them.

    An ngrok free tunnel gets a new hostname every restart, which silently
    breaks the Telegram webhook. `-Action start` and `-Action webhook` both
    re-point it, so the fix is one command instead of a manual setWebhook.
    (With a reserved ngrok domain, add --url=<domain> to $NgrokArgs below and
    the hostname stops moving at all.)

    Secrets are read from OpenExecutive/.env into the process only; nothing is
    written to disk or printed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\local_stack.ps1 -Action start
    powershell -ExecutionPolicy Bypass -File scripts\local_stack.ps1 -Action status
    powershell -ExecutionPolicy Bypass -File scripts\local_stack.ps1 -Action stop
#>
[CmdletBinding()]
param(
    [ValidateSet('start', 'status', 'stop', 'webhook')]
    [string]$Action = 'status',
    [int]$ApiPort = 8000,
    [int]$UiPort = 3000,
    # Skip the Next.js UI (Telegram only needs the API and the tunnel).
    [switch]$NoUi
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 still negotiates TLS 1.0 by default; api.telegram.org
# only speaks 1.2+, so every Bot API call fails without this.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path -Parent $PSScriptRoot           # ...\OpenExecutive
$logDir = Join-Path $root '.local-stack'
$pidFile = Join-Path $logDir 'pids.json'
$ngrokApi = 'http://127.0.0.1:4040/api/tunnels'

function Read-DotEnv {
    $envPath = Join-Path $root '.env'
    $map = @{}
    if (-not (Test-Path $envPath)) { return $map }
    foreach ($line in Get-Content $envPath) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $i = $trimmed.IndexOf('=')
        if ($i -lt 1) { continue }
        $key = $trimmed.Substring(0, $i).Trim()
        $value = $trimmed.Substring($i + 1).Trim()
        # Same as `set -a; . ./.env`: an unquoted value ends at a trailing
        # comment. Several keys here are written as `KEY=value # why`.
        $comment = $value.IndexOf(' #')
        if ($comment -ge 0) { $value = $value.Substring(0, $comment).Trim() }
        $map[$key] = $value.Trim('"').Trim("'")
    }
    return $map
}

function Get-TunnelUrl {
    try {
        $tunnels = (Invoke-RestMethod -Uri $ngrokApi -TimeoutSec 5).tunnels
    } catch {
        return $null
    }
    $https = $tunnels | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1
    if ($https) { return $https.public_url }
    return $null
}

function Save-Pid([string]$name, [int]$processId) {
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    $pids = @{}
    if (Test-Path $pidFile) {
        (Get-Content $pidFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $pids[$_.Name] = $_.Value }
    }
    $pids[$name] = $processId
    $pids | ConvertTo-Json | Set-Content $pidFile -Encoding utf8
}

function Start-Detached([string]$name, [string]$file, [string[]]$argList, [string]$workDir) {
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    $out = Join-Path $logDir "$name.log"
    $err = Join-Path $logDir "$name.err.log"
    $proc = Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $workDir `
        -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Save-Pid $name $proc.Id
    Write-Host ("  {0,-8} started (pid {1}), log: {2}" -f $name, $proc.Id, $out)
    return $proc
}

function Wait-For([scriptblock]$probe, [int]$seconds, [string]$what) {
    for ($i = 0; $i -lt $seconds; $i++) {
        $result = & $probe
        if ($result) { return $result }
        Start-Sleep -Seconds 1
    }
    Write-Warning "$what did not come up within ${seconds}s - check the logs in $logDir"
    return $null
}

function Set-TelegramWebhook {
    $envMap = Read-DotEnv
    $token = $envMap['TELEGRAM_BOT_TOKEN']
    if (-not $token) { Write-Warning 'TELEGRAM_BOT_TOKEN is not in .env - skipping the webhook'; return }
    $url = Get-TunnelUrl
    if (-not $url) { Write-Warning 'No ngrok tunnel is running - skipping the webhook'; return }

    $body = @{ url = "$url/webhook/telegram"; allowed_updates = '["message"]' }
    if ($envMap['TELEGRAM_WEBHOOK_SECRET']) { $body['secret_token'] = $envMap['TELEGRAM_WEBHOOK_SECRET'] }
    $resp = Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/setWebhook" -Body $body -TimeoutSec 20
    if ($resp.ok) {
        Write-Host "  webhook -> $url/webhook/telegram"
    } else {
        Write-Warning "setWebhook failed: $($resp.description)"
    }
}

function Show-Status {
    $envMap = Read-DotEnv

    Write-Host ''
    Write-Host 'Open Executive - local stack' -ForegroundColor Cyan

    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 8
        Write-Host ("  api      : up on {0} - store {1}, {2} knowledge chunks, {3} skills" -f `
                $ApiPort, $health.vector_store, $health.builtin_knowledge_chunks, $health.builtin_skills)
    } catch {
        Write-Host "  api      : DOWN on $ApiPort" -ForegroundColor Red
    }

    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:$UiPort/signin" -TimeoutSec 8 -UseBasicParsing
        Write-Host "  ui       : up on http://localhost:$UiPort"
    } catch {
        Write-Host "  ui       : down on $UiPort (fine if you only use Telegram)"
    }

    $url = Get-TunnelUrl
    if ($url) { Write-Host "  tunnel   : $url" } else { Write-Host '  tunnel   : DOWN' -ForegroundColor Red }

    $token = $envMap['TELEGRAM_BOT_TOKEN']
    if ($token) {
        try {
            $info = (Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo" -TimeoutSec 15).result
            $isCurrent = $url -and $info.url -eq "$url/webhook/telegram"
            $state = if ($isCurrent) { 'matches the tunnel' } else { 'STALE - run -Action webhook' }
            Write-Host "  telegram : $($info.url) [$state]"
            if ($info.last_error_message) {
                Write-Host "             last error: $($info.last_error_message)" -ForegroundColor Yellow
            }
            Write-Host "             pending updates: $($info.pending_update_count)"
        } catch {
            Write-Host '  telegram : could not reach the Bot API' -ForegroundColor Yellow
        }
    }

    # Who the bot will answer: the roster gate gives a per-chat allowlist.
    if ($envMap['BACKEND_SHARED_SECRET']) {
        try {
            $people = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/people" `
                -Headers @{ 'x-api-key' = $envMap['BACKEND_SHARED_SECRET'] } -TimeoutSec 8
            # /people returns a bare array. Testing $people.people first would
            # silently member-enumerate the array instead of finding a wrapper.
            $rows = if ($people -is [System.Array]) { $people } elseif ($people.people) { $people.people } else { @($people) }
            $linked = @($rows | Where-Object { $_.telegram_chat_id })
            if ($linked.Count -gt 0) {
                Write-Host "  roster   : $($linked.Count) person(s) linked to Telegram - $(($linked | ForEach-Object { $_.full_name }) -join ', ')"
            } else {
                Write-Host '  roster   : nobody has telegram_chat_id set - the bot will reject every message' -ForegroundColor Yellow
            }
        } catch {
            Write-Host '  roster   : could not read /people' -ForegroundColor Yellow
        }

        # What the turns have cost so far. Anthropic bills every Telegram reply.
        try {
            $usage = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/audit/usage" `
                -Headers @{ 'x-api-key' = $envMap['BACKEND_SHARED_SECRET'] } -TimeoutSec 15
            $today = $usage.by_day | Where-Object { $_.day -eq (Get-Date -Format 'yyyy-MM-dd') }
            $todayCalls = 0
            if ($today) { $todayCalls = $today.calls }
            Write-Host ("  usage    : {0} model calls all-time ({1} today), {2} output tokens, reported cost `${3}" -f `
                    $usage.totals.calls, $todayCalls, $usage.totals.output_tokens, $usage.totals.cost_usd)
        } catch {
            Write-Host '  usage    : could not read /audit/usage' -ForegroundColor Yellow
        }
    }
    Write-Host ''
}

switch ($Action) {
    'start' {
        $python = Join-Path $root 'packages\core\.venv\Scripts\python.exe'
        if (-not (Test-Path $python)) { throw "No venv at $python - run 'uv sync' in packages/core first" }
        $ngrok = (Get-Command ngrok -ErrorAction SilentlyContinue).Source
        if (-not $ngrok) { throw 'ngrok is not on PATH' }

        Write-Host 'Starting the local stack...' -ForegroundColor Cyan

        # Child processes inherit this process's environment, which is how the
        # Next.js server gets BACKEND_SHARED_SECRET and the auth settings (it
        # does not read .env itself, unlike pydantic-settings on the API side).
        $envMap = Read-DotEnv
        foreach ($key in $envMap.Keys) { Set-Item -Path "env:$key" -Value $envMap[$key] }
        if (-not $envMap['BACKEND_SHARED_SECRET']) {
            Write-Warning 'BACKEND_SHARED_SECRET is empty - the API accepts every request, and the tunnel puts it on the public internet. Set it in .env.'
        }

        # 127.0.0.1, not 0.0.0.0: the tunnel must reach THIS server. Docker
        # Desktop publishes container ports on 0.0.0.0, and a container on the
        # same port would otherwise answer the tunnel instead of us.
        Start-Detached 'api' $python @(
            '-m', 'uvicorn', 'openexecutive.api.main:app', '--host', '127.0.0.1', '--port', "$ApiPort"
        ) (Join-Path $root 'packages\core') | Out-Null

        $NgrokArgs = @('http', "http://127.0.0.1:$ApiPort", '--log', 'stdout', '--log-format', 'logfmt')
        Start-Detached 'ngrok' $ngrok $NgrokArgs $root | Out-Null

        if (-not $NoUi) {
            $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
            if ($npm) {
                Start-Detached 'ui' $npm @('run', 'dev') (Join-Path $root 'packages\ui') | Out-Null
            } else {
                Write-Warning 'npm not found - skipping the UI'
            }
        }

        Wait-For { try { Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 3 | Out-Null; $true } catch { $false } } 60 'The API' | Out-Null
        Wait-For { Get-TunnelUrl } 30 'The ngrok tunnel' | Out-Null
        Set-TelegramWebhook
        Show-Status
    }
    'webhook' { Set-TelegramWebhook; Show-Status }
    'status' { Show-Status }
    'stop' {
        if (-not (Test-Path $pidFile)) { Write-Host 'Nothing recorded to stop.'; break }
        $pids = Get-Content $pidFile -Raw | ConvertFrom-Json
        foreach ($entry in $pids.PSObject.Properties) {
            try {
                Stop-Process -Id $entry.Value -Force -ErrorAction Stop
                Write-Host "  stopped $($entry.Name) (pid $($entry.Value))"
            } catch {
                Write-Host "  $($entry.Name) (pid $($entry.Value)) was not running"
            }
        }
        Remove-Item $pidFile -Force
    }
}
