param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [string]$MediaRoot
)

$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath $RepoRoot

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Host ('[ERROR] 找不到配置文件：' + $ConfigPath)
    Write-Host '请确认仓库完整，或自行创建 config/backend.json。'
    exit 10
}

try {
    $cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
} catch {
    Write-Host ('[ERROR] 配置解析失败：' + $ConfigPath)
    Write-Host $_.Exception.Message
    exit 12
}

if ([string]::IsNullOrWhiteSpace($MediaRoot)) {
    $MediaRoot = $cfg.media_root
}

if ($null -ne $MediaRoot) {
    $MediaRoot = $MediaRoot.ToString().Trim()
}

if ([string]::IsNullOrWhiteSpace($MediaRoot)) {
    Write-Host '[ERROR] MediaRoot 为空。'
    Write-Host ('请编辑 ' + $ConfigPath + ' 并设置 media_root 为媒体库绝对路径；或执行：')
    Write-Host '  start.bat D:\Media'
    exit 13
}

if (-not (Test-Path -LiteralPath $MediaRoot -PathType Container)) {
    Write-Host ('[ERROR] MediaRoot 路径不存在：' + $MediaRoot)
    exit 14
}

$mediaRootFull = (Resolve-Path -LiteralPath $MediaRoot).Path

$bindHost = $cfg.host
if ($null -ne $bindHost) {
    $bindHost = $bindHost.ToString().Trim()
}

$port = $null
if ($null -ne $cfg.port) {
    try {
        $port = [int]$cfg.port
    } catch {
        Write-Host ('[ERROR] port 必须是整数：' + $cfg.port)
        exit 15
    }
}

$pythonCmd = Get-Command py -ErrorAction SilentlyContinue
$usePyLauncher = $true
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    $usePyLauncher = $false
}

if (-not $pythonCmd) {
    Write-Host '[ERROR] 未找到 Python（py 或 python）。请安装 Python 3 并确保已加入 PATH。'
    exit 11
}

$pythonExe = $pythonCmd.Source

$pyArgs = @()
if ($usePyLauncher) {
    $pyArgs += '-3'
}
$pyArgs += @('-m', 'backend.api', '--config', $ConfigPath, '--media-root', $mediaRootFull)
if (-not [string]::IsNullOrWhiteSpace($bindHost)) {
    $pyArgs += @('--host', $bindHost)
}
if ($null -ne $port) {
    $pyArgs += @('--port', [string]$port)
}
$pyArgs += @('--port-conflict', 'auto')

Write-Host ('RepoRoot:  ' + $RepoRoot)
Write-Host ('Config:    ' + $ConfigPath)
Write-Host ('MediaRoot: ' + $mediaRootFull)
if (-not [string]::IsNullOrWhiteSpace($bindHost)) {
    Write-Host ('Host:      ' + $bindHost)
}
if ($null -ne $port) {
    Write-Host ('Port:      ' + $port)
}
Write-Host ''
Write-Host '启动后端服务中...（首次成功启动会自动打开默认浏览器）'
Write-Host '停止服务：按 Ctrl+C 或直接关闭窗口。'

$opened = $false
$prevErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $pythonExe @pyArgs 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        if (-not $opened) {
            $m = [regex]::Match($line, 'https?://\S+')
            if ($m.Success) {
                $url = $m.Value
                Start-Process $url | Out-Null
                $opened = $true
            }
        }
    }
} finally {
    $ErrorActionPreference = $prevErrorActionPreference
}

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host ('[ERROR] 后端退出（exit code=' + $exitCode + '）。')
}
exit $exitCode
