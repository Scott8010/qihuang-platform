# 岐黄智脑商业化平台 — Makefile
# 统一入口: make test / make lint / make clean

.PHONY: test test-quick test-cov lint lint-ruff lint-ast clean

PYTHON := python

test:
	$(PYTHON) -m pytest tests/ -v --tb=short -p no:cacheprovider

test-quick:
	$(PYTHON) -m pytest tests/ -v --tb=short -m "not slow" -p no:cacheprovider

test-cov:
	$(PYTHON) -m pytest tests/ -v --tb=short \
		--cov=qihuang_platform \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		-p no:cacheprovider
	@echo "覆盖率报告: htmlcov/index.html"

lint: lint-ast lint-ruff

lint-ruff:
	$(PYTHON) -m ruff check qihuang_platform/ tests/ --ignore=E501,F841

lint-ast:
	$(PYTHON) -c "\
import ast, os, sys; \
errors = 0; \
for root_name in ['qihuang_platform', 'tests']: \
    for root, dirs, files in os.walk(root_name): \
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache', 'frontend-admin')]; \
        for f in files: \
            if f.endswith('.py'): \
                path = os.path.join(root, f); \
                try: \
                    with open(path) as fp: ast.parse(fp.read()) \
                except SyntaxError as e: \
                    print(f'SYNTAX ERROR: {path}: {e}'); errors += 1; \
sys.exit(1 if errors else 0)"

clean:
	rm -f test_qihuang_platform.db
	rm -rf .pytest_cache htmlcov __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
