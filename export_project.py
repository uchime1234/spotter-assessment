
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "project_source_code.txt"

ALLOWED_EXTENSIONS = {
    ".py", ".html", ".css", ".js", ".ts",
    ".tsx", ".json", ".md", ".txt",
    ".yaml", ".yml", ".toml"
}

EXCLUDED_FOLDERS = {
    ".git", ".venv", "venv", "env",
    "__pycache__", "node_modules",
    ".pytest_cache", ".idea", ".vscode",
    "dist", "build", "data", "private",
    "secrets", "logs", "cache"
}

EXCLUDED_FILES = {
    "export_project.py",
    "project_source_code.txt",
    "package-lock.json",
    "credentials.json",
    "secrets.json",
    "service_account.json"
}

count = 0

with OUTPUT.open("w", encoding="utf-8") as output:

    output.write("SPOTTER PROJECT SOURCE CODE\n")
    output.write("=" * 80 + "\n\n")

    for file in sorted(ROOT.rglob("*")):

        if not file.is_file() or file.is_symlink():
            continue

        relative_path = file.relative_to(ROOT)

        if any(
            part in EXCLUDED_FOLDERS
            for part in relative_path.parts
        ):
            continue

        if file.name in EXCLUDED_FILES:
            continue

        if file.name.startswith(".env"):
            continue

        if file.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        try:
            content = file.read_text(encoding="utf-8")

            output.write("\n" + "=" * 80 + "\n")
            output.write(f"FILE: {relative_path.as_posix()}\n")
            output.write("=" * 80 + "\n\n")
            output.write(content)
            output.write("\n\n")

            count += 1
            print(f"Copied: {relative_path}")

        except (UnicodeError, OSError) as error:
            print(f"Skipped: {relative_path} - {error}")

print("\nExport completed successfully!")
print(f"Total files copied: {count}")
print(f"Output file: {OUTPUT}")
