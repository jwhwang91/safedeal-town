from pathlib import Path

# ===== 설정 =====
PROJECT_ROOT = Path(".").resolve()
OUTPUT_FILE = PROJECT_ROOT / "project_code_dump.txt"

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    "out",
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
}

EXCLUDE_FILES = {
    ".DS_Store",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "project_code_dump.txt",
}

# 보안상 기본 제외
EXCLUDE_SECRET_FILES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
}

TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".html", ".css", ".scss", ".sass",
    ".json", ".md", ".txt",
    ".yml", ".yaml",
    ".toml", ".ini",
    ".sh", ".zsh", ".bash",
    ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".swift",
    ".php",
    ".rb",
    ".sql",
    ".xml",
    ".vue",
    ".svelte",
}

MAX_FILE_SIZE_MB = 2


def is_excluded_path(path: Path) -> bool:
    parts = set(path.parts)

    if parts & EXCLUDE_DIRS:
        return True

    if path.name in EXCLUDE_FILES:
        return True

    if path.name in EXCLUDE_SECRET_FILES:
        return True

    return False


def is_probably_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True

    # 확장자가 없어도 텍스트면 포함하고 싶을 때
    try:
        with path.open("rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return False
        chunk.decode("utf-8")
        return True
    except Exception:
        return False


def read_text_safely(path: Path) -> str:
    encodings = ["utf-8", "utf-8-sig", "cp949", "latin-1"]

    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue

    return path.read_text(errors="replace")


def main():
    collected_files = []

    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue

        if is_excluded_path(path):
            continue

        if path.resolve() == OUTPUT_FILE.resolve():
            continue

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            continue

        if not is_probably_text_file(path):
            continue

        collected_files.append(path)

    with OUTPUT_FILE.open("w", encoding="utf-8") as out:
        out.write("# Project Code Dump\n\n")
        out.write(f"Project Root: {PROJECT_ROOT}\n")
        out.write(f"Total Files: {len(collected_files)}\n\n")

        for path in collected_files:
            relative_path = path.relative_to(PROJECT_ROOT)

            out.write("\n")
            out.write("=" * 100 + "\n")
            out.write(f"FILE: {relative_path}\n")
            out.write("=" * 100 + "\n\n")

            try:
                content = read_text_safely(path)
                out.write(content)
                if not content.endswith("\n"):
                    out.write("\n")
            except Exception as e:
                out.write(f"[ERROR READING FILE: {e}]\n")

    print(f"Done. Collected {len(collected_files)} files into:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()