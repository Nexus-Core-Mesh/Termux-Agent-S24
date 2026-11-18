"""Lightweight local drop-in ingestion daemon for the Termux agent."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .memory import MemoryManager


class DropInDaemon:
    """Monitor a central inbox and route incoming files into the correct project folder."""

    def __init__(
        self,
        workspace_dir: str | Path = "workspace",
        inbox_dir: str | Path | None = None,
        memory_path: str | Path | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir = Path(inbox_dir or self.workspace_dir / "inbox").resolve()
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.memory = MemoryManager(memory_path or self.workspace_dir / "memory.json")
        self.poll_interval = float(poll_interval)
        self.memory.log_action("drop_in_daemon_initialized", inbox=str(self.inbox_dir), workspace=str(self.workspace_dir))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _safe_name(filename: str) -> str:
        stem = Path(filename).stem
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
        return cleaned[:80] or "drop_in"

    def _discover_files(self) -> list[Path]:
        if not self.inbox_dir.exists():
            return []
        return sorted(path for path in self.inbox_dir.iterdir() if path.is_file() and not path.name.startswith("."))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _read_text_file(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def _extract_pdf_text(self, path: Path) -> str:
        for name in ("pdftotext", "mutool"):
            if shutil.which(name):
                try:
                    completed = subprocess.run(
                        [name, str(path), "-"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if completed.returncode == 0 and completed.stdout.strip():
                        return completed.stdout
                except OSError:
                    continue

        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(str(path))
            pages: list[str] = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
        except Exception:
            pass

        return "[PDF text extraction unavailable locally; pypdf or pdftotext is required for full PDF parsing on this device.]"

    def _extract_image_text(self, path: Path) -> str:
        tesseract = shutil.which("tesseract")
        if tesseract:
            try:
                completed = subprocess.run(
                    [tesseract, str(path), "stdout"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode == 0 and completed.stdout.strip():
                    return completed.stdout
            except OSError:
                pass

        try:
            from PIL import Image  # type: ignore

            image = Image.open(path)
            return (
                f"[Image OCR unavailable locally: {path.name}]\n"
                f"image_format={image.format or 'unknown'} image_size={image.size}"
            )
        except Exception:
            return f"[Image OCR unavailable locally for {path.name}; install tesseract or pillow for OCR on aarch64.]"

    def extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".json", ".csv", ".log", ".yaml", ".yml", ".ini", ".cfg"}:
            return self._read_text_file(path)
        if suffix == ".pdf":
            return self._extract_pdf_text(path)
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            return self._extract_image_text(path)
        if suffix in {".rtf"}:
            return self._read_text_file(path)
        return self._read_text_file(path) if path.is_file() else ""

    def _candidate_projects(self) -> list[Path]:
        workspace = self.workspace_dir
        candidates: list[Path] = []
        if workspace.exists():
            for child in sorted(workspace.iterdir()):
                if child.is_dir() and child.name not in {"inbox", "__pycache__"}:
                    candidates.append(child)
        return candidates

    def _project_keywords(self, project_dir: Path) -> set[str]:
        keywords: set[str] = set()
        tokens = [project_dir.name]
        for name in ("README.md", "README", "CHANGELOG.md", "CHANGELOG"):
            readme = project_dir / name
            if readme.exists():
                try:
                    tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", readme.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    pass
        for candidate in tokens:
            keywords.update(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", candidate))
        return {token.lower() for token in keywords if len(token) > 2}

    def classify_project(self, text: str, *, fallback: str | Path | None = None) -> Path:
        lowered = text.lower()
        project_dirs = self._candidate_projects()
        if not project_dirs:
            return Path(fallback or self.workspace_dir)

        tag_match = re.search(r"(?:project|tag|route|target)\s*[:=]\s*([A-Za-z0-9_.-]+)", lowered)
        if tag_match:
            name = tag_match.group(1).strip()
            for project in project_dirs:
                if project.name.lower() == name.lower():
                    return project

        best_project = Path(fallback or self.workspace_dir)
        best_score = -1
        for project in project_dirs:
            score = 0
            keywords = self._project_keywords(project)
            if not keywords:
                continue
            for keyword in keywords:
                if keyword in lowered:
                    score += 2
            project_name = project.name.lower()
            if project_name in lowered:
                score += 3
            if score > best_score:
                best_score = score
                best_project = project

        if best_score < 0:
            for project in project_dirs:
                if project.name.lower() in {"workspace", "root"}:
                    return project
        return best_project

    def _append_to_project_log(self, project_dir: Path, payload: str) -> Path:
        project_dir.mkdir(parents=True, exist_ok=True)
        log_path = project_dir / "drop_in_log.txt"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        return log_path

    def route_drop(self, path: Path) -> dict[str, Any]:
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": f"Missing or invalid drop file: {path}", "path": str(path)}

        extracted = self.extract_text(path)
        project_dir = self.classify_project(extracted, fallback=self.workspace_dir)
        timestamp = self._now_iso().replace(":", "-")
        safe_name = self._safe_name(path.name)
        archive_dir = project_dir / "drop_in"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{timestamp}_{safe_name}.txt"

        record = (
            "\n---\n"
            f"timestamp={self._now_iso()}\n"
            f"source={path.name}\n"
            f"source_sha256={self._sha256(path)}\n"
            f"project={project_dir.name}\n"
            f"route={archive_path.relative_to(self.workspace_dir)}\n"
            "\n"
            f"{extracted}\n"
        )
        archive_path.write_text(record, encoding="utf-8")
        log_path = self._append_to_project_log(project_dir, record)

        payload = {
            "ok": True,
            "source": str(path),
            "project": str(project_dir),
            "archive_path": str(archive_path),
            "log_path": str(log_path),
            "text_length": len(extracted),
            "timestamp": self._now_iso(),
        }
        self.memory.log_action("drop_in_routed", **payload)
        self.memory.update_state("last_drop_in", payload)
        return payload

    def process_once(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for dropped in self._discover_files():
            try:
                result = self.route_drop(dropped)
            except Exception as exc:  # pragma: no cover - defensive local daemon path
                result = {"ok": False, "path": str(dropped), "error": str(exc)}
            results.append(result)
            try:
                dropped.unlink()
            except OSError:
                pass
        return results

    def run_forever(self, *, max_iterations: int | None = None) -> list[dict[str, Any]]:
        total: list[dict[str, Any]] = []
        iterations = 0
        while True:
            results = self.process_once()
            if results:
                total.extend(results)
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(self.poll_interval)
        return total


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the drop-in inbox daemon for Termux-Agent-S24.")
    parser.add_argument("--workspace", default="workspace", help="Workspace root to monitor")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="Process any queued files once and exit")
    args = parser.parse_args()

    daemon = DropInDaemon(workspace_dir=args.workspace, poll_interval=args.interval)
    if args.once:
        print(json.dumps(daemon.process_once(), indent=2, ensure_ascii=False))
        return
    print(f"Drop-in daemon started for {daemon.inbox_dir} (poll interval={args.interval}s)")
    daemon.run_forever()


if __name__ == "__main__":
    main()
