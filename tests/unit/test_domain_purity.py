"""Критерий  (ТЗ): домен не импортирует ничего из infrastructure.

Статическая проверка (AST) по всем .py в:
- shared/ (ядро: money, ton_address, domain);
- contexts/*/domain/ и contexts/*/ports/.

Запрещены импорты: nftsniper.infrastructure, nftsniper.entrypoints,
nftsniper.config, нфтsniper.bootstrap, а также внешние I/O-библиотеки
(fastapi, httpx, redis, sqlalchemy, aiogram, pydantic, ...).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "nftsniper"

_FORBIDDEN_PREFIXES = (
    "nftsniper.infrastructure",
    "nftsniper.entrypoints",
    "nftsniper.config",
    "nftsniper.bootstrap",
    "fastapi",
    "httpx",
    "redis",
    "sqlalchemy",
    "alembic",
    "aiogram",
    "pydantic",
    "structlog",
    "prometheus_client",
    "uvicorn",
    "segno",
)


def _domain_files() -> list[Path]:
    files: list[Path] = []
    files.extend(SRC.joinpath("shared").rglob("*.py"))
    for context in sorted(SRC.joinpath("contexts").iterdir()):
        if not context.is_dir():
            continue
        for sub in ("domain", "ports"):
            directory = context / sub
            if directory.is_dir():
                files.extend(directory.rglob("*.py"))
    return files


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_domain_files_exist() -> None:
    files = _domain_files()
    assert len(files) >= 20, "ожидалось ≥20 файлов домена/портов, похоже что-то пропало"


def test_domain_does_not_import_infrastructure() -> None:
    violations: list[str] = []
    for path in _domain_files():
        rel = path.relative_to(SRC.parent.parent.parent).as_posix()
        for module in _imported_modules(path):
            if module.startswith(_FORBIDDEN_PREFIXES):
                violations.append(f"{rel}: {module}")
    assert not violations, "домен/порты должны быть чистыми, нарушены:\n" + "\n".join(violations)
