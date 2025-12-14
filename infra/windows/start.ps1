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


# --- Python venv + dependencies (Pillow) ---
$pyBaseArgs = @()
if ($usePyLauncher) {
    $pyBaseArgs += '-3'
}

$venvDir = Join-Path $RepoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host ('准备 Python 虚拟环境：' + $venvDir)
    & $pythonExe @pyBaseArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host ('[ERROR] 创建虚拟环境失败（exit code=' + $LASTEXITCODE + '）。')
        exit 16
    }
}

$pythonExe = $venvPython
$requirementsPath = Join-Path $RepoRoot 'backend\requirements.txt'
$requirementsHashPath = Join-Path $venvDir '.ppm-requirements.sha256'
if (Test-Path -LiteralPath $requirementsPath) {
    $reqHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirementsPath).Hash.ToLowerInvariant()
    $prevHash = ''
    if (Test-Path -LiteralPath $requirementsHashPath) {
        try {
            $prevHash = (Get-Content -LiteralPath $requirementsHashPath -Raw).Trim().ToLowerInvariant()
        } catch {
            $prevHash = ''
        }
    }

    if ($prevHash -ne $reqHash) {
        Write-Host '安装/更新 Python 依赖（首次运行可能需要几分钟）...'
        & $pythonExe -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            Write-Host ('[ERROR] pip 升级失败（exit code=' + $LASTEXITCODE + '）。')
            exit 17
        }
        & $pythonExe -m pip install -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host ('[ERROR] 依赖安装失败（exit code=' + $LASTEXITCODE + '）。')
            Write-Host ('请手动执行：' + $pythonExe + ' -m pip install -r ' + $requirementsPath)
            exit 18
        }
        Set-Content -LiteralPath $requirementsHashPath -Value $reqHash -NoNewline -Encoding ASCII
    }
} else {
    Write-Host ('[WARN] 未找到 requirements.txt：' + $requirementsPath)
}

$ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCmd) {
    Write-Host '[WARN] 未找到 ffmpeg：视频 2×2 预览缩略图将不可用。'
    Write-Host '       你仍然可以浏览/播放视频；如需缩略图，请安装 ffmpeg 并加入 PATH。'
}

$pyArgs = @('-m', 'backend.api', '--config', $ConfigPath, '--media-root', $mediaRootFull)
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
