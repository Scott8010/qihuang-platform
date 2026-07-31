# 岐黄智脑 CI — Windows 本地测试运行器
# 用法: powershell -File scripts/run_tests.ps1

param(
    [switch]$Quick,      # 快速模式：跳过慢速测试
    [switch]$Coverage,   # 生成覆盖率报告
    [string]$Filter = "" # 运行指定测试（如 "gateway"）
)

$ErrorActionPreference = "Stop"

# ─── 配置 ───
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  岐黄智脑商业化平台 — CI 测试流水线" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ─── 环境检查 ───
Write-Host "[1/4] 环境检查..." -ForegroundColor Yellow
if (-not (Test-Path $Python)) {
    Write-Host "  ERROR: Python 未找到: $Python" -ForegroundColor Red
    Write-Host "  请确认 workbuddy Python 环境已安装" -ForegroundColor Red
    exit 1
}

# 检查依赖
$deps = & $Python -c "import fastapi; import pytest; import sqlalchemy; print('OK')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: 缺少依赖，尝试安装..." -ForegroundColor Yellow
    & $Python -m pip install -r "$ProjectRoot/requirements-test.txt" -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: 依赖安装失败" -ForegroundColor Red
        exit 1
    }
}
Write-Host "  Python: $(& $Python --version)" -ForegroundColor Green
Write-Host "  Pytest: $(& $Python -m pytest --version)" -ForegroundColor Green

# ─── 清理旧数据 ───
Write-Host ""
Write-Host "[2/4] 清理旧测试数据..." -ForegroundColor Yellow
$testDb = Join-Path $ProjectRoot "test_qihuang_platform.db"
if (Test-Path $testDb) {
    Remove-Item $testDb -Force
    Write-Host "  已删除旧测试数据库" -ForegroundColor Gray
}

# 清理 pytest 缓存
$cache = Join-Path $ProjectRoot ".pytest_cache"
if (Test-Path $cache) {
    Remove-Item $cache -Recurse -Force
}

# ─── 运行测试 ───
Write-Host ""
Write-Host "[3/4] 运行测试..." -ForegroundColor Yellow

$pytestArgs = @(
    "tests/",
    "-v",
    "--tb=short",
    "--strict-markers",
    "-p", "no:cacheprovider"
)

# 并行运行（加速）- 需要 pytest-xdist
# $pytestArgs += "-n", "auto"

# 过滤
if ($Filter) {
    $pytestArgs += "-k", $Filter
    Write-Host "  过滤: $Filter" -ForegroundColor Gray
}

# 慢速测试处理
if ($Quick) {
    $pytestArgs += "-m", "not slow"
    Write-Host "  模式: 快速（跳过 LLM 调用测试）" -ForegroundColor Gray
}

# 覆盖率
if ($Coverage) {
    $pytestArgs += @(
        "--cov=qihuang_platform",
        "--cov-report=term-missing",
        "--cov-report=html:htmlcov"
    )
}

Push-Location $ProjectRoot
try {
    $result = & $Python -m pytest @pytestArgs 2>&1
    $testExitCode = $LASTEXITCODE
    
    # 输出结果
    Write-Host $result
    
    # ─── 结果报告 ───
    Write-Host ""
    Write-Host "[4/4] 测试报告" -ForegroundColor Yellow
    
    if ($testExitCode -eq 0) {
        Write-Host "  ✅ 全部测试通过!" -ForegroundColor Green
    } else {
        Write-Host "  ❌ 有测试失败 (退出码: $testExitCode)" -ForegroundColor Red
    }
    
    # 覆盖率
    if ($Coverage) {
        $covDir = Join-Path $ProjectRoot "htmlcov"
        if (Test-Path $covDir) {
            Write-Host "  覆盖率报告: file:///$covDir/index.html" -ForegroundColor Cyan
        }
    }
    
    exit $testExitCode
} finally {
    Pop-Location
}
