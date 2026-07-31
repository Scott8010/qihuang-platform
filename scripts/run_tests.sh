#!/bin/bash
# 岐黄智脑 CI — Linux 测试运行器（服务器用）
# 用法: bash scripts/run_tests.sh [--quick] [--coverage] [--filter=xxx]

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUICK=false
COVERAGE=false
FILTER=""

# ─── 参数解析 ───
for arg in "$@"; do
    case $arg in
        --quick) QUICK=true ;;
        --coverage) COVERAGE=true ;;
        --filter=*) FILTER="${arg#*=}" ;;
    esac
done

echo "========================================"
echo "  岐黄智脑商业化平台 — CI 测试流水线"
echo "========================================"
echo ""

# ─── 环境检查 ───
echo "[1/4] 环境检查..."
PYTHON=$(which python3 || which python)
if [ -z "$PYTHON" ]; then
    echo "  ERROR: Python 未找到"
    exit 1
fi

# 检查依赖
$PYTHON -c "import fastapi; import pytest; import sqlalchemy" 2>/dev/null || {
    echo "  WARNING: 缺少依赖，安装中..."
    $PYTHON -m pip install -r "$PROJECT_ROOT/requirements-test.txt" -q
}

echo "  Python: $($PYTHON --version)"
echo "  Pytest: $($PYTHON -m pytest --version)"

# ─── 清理 ───
echo ""
echo "[2/4] 清理旧测试数据..."
rm -f "$PROJECT_ROOT/test_qihuang_platform.db"
rm -rf "$PROJECT_ROOT/.pytest_cache"
echo "  已清理"

# ─── 运行测试 ───
echo ""
echo "[3/4] 运行测试..."

PYTEST_ARGS=("tests/" "-v" "--tb=short" "--strict-markers" "-p" "no:cacheprovider")

if [ -n "$FILTER" ]; then
    PYTEST_ARGS+=("-k" "$FILTER")
    echo "  过滤: $FILTER"
fi

if [ "$QUICK" = true ]; then
    PYTEST_ARGS+=("-m" "not slow")
    echo "  模式: 快速"
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_ARGS+=("--cov=qihuang_platform" "--cov-report=term-missing" "--cov-report=html:htmlcov")
fi

cd "$PROJECT_ROOT"
$PYTHON -m pytest "${PYTEST_ARGS[@]}" && TEST_EXIT=$? || TEST_EXIT=$?

# ─── 报告 ───
echo ""
echo "[4/4] 测试报告"

if [ $TEST_EXIT -eq 0 ]; then
    echo "  ✅ 全部测试通过!"
else
    echo "  ❌ 有测试失败 (退出码: $TEST_EXIT)"
fi

if [ "$COVERAGE" = true ] && [ -d "$PROJECT_ROOT/htmlcov" ]; then
    echo "  覆盖率报告: $PROJECT_ROOT/htmlcov/index.html"
fi

exit $TEST_EXIT
