"""Статический гейт: запрет float в бизнес-коде.

Требование из ТЗ: «float запрещён на уровне линтера».
Деньги — только Decimal и nanoTON (int).

Float допустим лишь там, где измеряются физические величины
(таймауты, backoff, метрики) — такие модули добавляются в WHITELIST.

Запуск:  python scripts/no_float.py [корень_к_проверке]
"""

import ast
import sys
from pathlib import Path

WHITELIST_MARKERS: tuple[str, ...] = (
    "nftsniper/infrastructure/http",  # таймауты и backoff — секунды
    "nftsniper/observability",  # метрики
)


def is_whitelisted(path: Path) -> bool:
    posix = path.as_posix()
    return any(marker in posix for marker in WHITELIST_MARKERS)


def check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            violations.append(f"{path}:{node.lineno}: float-литерал {node.value!r}")
        elif isinstance(node, ast.Name) and node.id == "float":
            violations.append(f"{path}:{node.lineno}: обращение к `float`")
    return violations


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    else:
        root = Path(__file__).resolve().parent.parent / "src"

    files = [p for p in sorted(root.rglob("*.py")) if not is_whitelisted(p)]
    violations: list[str] = []
    for path in files:
        violations.extend(check_file(path))

    if violations:
        print("float запрещён в бизнес-коде (деньги — Decimal, nanoTON — int):")
        print("\n".join(violations))
        return 1

    print(f"no-float: ok (проверено файлов: {len(files)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
