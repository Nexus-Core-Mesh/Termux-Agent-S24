"""Local watchdog daemon for ingesting dropped files from storage/download roots."""

from __future__ import annotations

import argparse
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
from .tools import ToolExecutor


class WatchdogDaemon:
    """Continuously polls local storage/download roots and routes new files into workspace projects."""

    def __init__(
        self,
        workspace_dir: str | Path = "workspace",
        memory_path: str | Path | None = None,
        watch_roots: Iterable[str | Path] | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.memory = MemoryManager(memory_path or self.workspace_dir / "memory.json")
        self.tools = ToolExecutor()
        self.poll_interval = float(poll_interval)
        self.inbox_dir = (self.workspace_dir / "inbox").resolve()
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.watch_roots = self._resolve_watch_roots(watch_roots)
        self._seen: set[str] = set()
        self.memory.log_action(
            "watchdog_daemon_initialized",
            workspace=str(self.workspace_dir),
            watch_roots=[str(path) for path in self.watch_roots],
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _resolve_watch_roots(self, watch_roots: Iterable[str | Path] | None) -> list[Path]:
        roots: list[Path] = []
        for root in watch_roots or ():
            candidate = Path(root).expanduser().resolve()
            if candidate not in roots:
                roots.append(candidate)

        home = Path.home()
        default_paths = [
            self.workspace_dir / "inbox",
            home / "storage" / "downloads",
            home / "Downloads",
            Path("/sdcard/Download"),
            Path("/storage/emulated/0/Download"),
            Path("/storage/self/primary/Download"),
        ]
        for candidate in default_paths:
            try:
                resolved = candidate.expanduser().resolve(strict=False)
            except OSError:
                continue
            if resolved not in roots:
                roots.append(resolved)
        return roots

    @staticmethod
    def _safe_name(filename: str) -> str:
        stem = Path(filename).stem
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
        return cleaned[:80] or "watchdog_ingest"

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

    def _ensure_parser_dependencies(self) -> dict[str, Any]:
        package_plan = [
            {"binary": "tesseract", "package": "tesseract"},
            {"binary": "pdftotext", "package": "poppler"},
            {"python_module": "pypdf", "package": "pypdf"},
            {"python_module": "PIL", "package": "pillow"},
            {"python_module": "docx", "package": "python-docx"},
        ]
        results: list[dict[str, Any]] = []
        for requirement in package_plan:
            result = self.tools.ensure_local_dependency(**requirement)
            results.append(result)
            if result.get("ok"):
                continue
            self.memory.log_action("watchdog_dependency_install_attempt", **result)
        return {"ok": all(item.get("ok") or item.get("status") == "available" for item in results), "results": results}

    def _extract_pdf_text(self, path: Path) -> str:
        dependency_probe = self._ensure_parser_dependencies()
        self.memory.log_action("watchdog_dependency_probe", **dependency_probe)
        for binary in ("pdftotext", "mutool"):
            executable = shutil.which(binary)
            if executable:
                try:
                    completed = subprocess.run(
                        [binary, str(path), "-"],
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
            return "[PDF extraction unavailable locally: install pdftotext, mutool, or pypdf on this device.]"

    def _extract_image_text(self, path: Path) -> str:
        dependency_probe = self._ensure_parser_dependencies()
        self.memory.log_action("watchdog_dependency_probe", **dependency_probe)
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
                f"[Image OCR unavailable locally for {path.name}]\n"
                f"image_format={image.format or 'unknown'} image_size={image.size}"
            )
        except Exception:
            return f"[Image OCR unavailable locally for {path.name}; install tesseract or pillow for OCR on aarch64.]"

    def extract_text(self, path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".json", ".csv", ".log", ".yaml", ".yml", ".ini", ".cfg"}:
            return self._read_text_file(path)
        if suffix == ".pdf":
            return self._extract_pdf_text(path)
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            return self._extract_image_text(path)
        if suffix in {".rtf"}:
            return self._read_text_file(path)
        try:
            return self._read_text_file(path)
        except OSError:
            return "[Unable to decode file as text; the file was preserved for manual review.]"

    def _candidate_projects(self) -> list[Path]:
        candidates: list[Path] = []
        for child in sorted(self.workspace_dir.iterdir()):
            if child.is_dir() and child.name not in {"inbox", "drop_in", "__pycache__"}:
                candidates.append(child)
        return candidates

    def _project_keywords(self, project_dir: Path) -> set[str]:
        keywords: set[str] = set()
        tokens = [project_dir.name]
        for filename in ("README.md", "README", "CHANGELOG.md", "CHANGELOG"):
            readme = project_dir / filename
            if readme.exists():
                try:
                    text = readme.read_text(encoding="utf-8", errors="replace")
                    tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text))
                except OSError:
                    continue
        for token in tokens:
            keywords.update(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", token))
        return {item.lower() for item in keywords if len(item) > 2}

    def _memory_project_names(self) -> list[str]:
        names: list[str] = []
        state = self.memory.data.get("state", {}) if isinstance(self.memory.data, dict) else {}
        projects = state.get("projects") if isinstance(state, dict) else None
        if isinstance(projects, list):
            for item in projects:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("path")
                    if isinstance(name, str) and name.strip():
                        names.append(name.strip())
        return names

    def classify_project(self, text: str, *, fallback: str | Path | None = None) -> Path:
        lowered = (text or "").lower()
        project_dirs = self._candidate_projects()
        if not project_dirs:
            return Path(fallback or self.workspace_dir)

        explicit = re.search(r"(?:project|tag|route|target|destination)\s*[:=]\s*([A-Za-z0-9_.-]+)", lowered)
        if explicit:
            target_name = explicit.group(1)
            for project in project_dirs:
                if project.name.lower() == target_name.lower():
                    return project
            for project in project_dirs:
                if target_name.lower() in project.name.lower():
                    return project

        memory_names = self._memory_project_names()
        for name in memory_names:
            candidate = self.workspace_dir / name
            if candidate.exists() and candidate.is_dir():
                if name.lower() in lowered or lowered in name.lower():
                    return candidate

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
            if project.name.lower() in lowered:
                score += 3
            if score > best_score:
                best_score = score
                best_project = project
        return best_project

    def _append_project_log(self, project_dir: Path, entry: str) -> Path:
        project_dir.mkdir(parents=True, exist_ok=True)
        log_path = project_dir / "drop_in_log.txt"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
            handle.write("\n")
        return log_path

    def _queue_file(self, source_path: Path) -> Path:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        queue_name = f"{timestamp}_{self._safe_name(source_path.name)}{source_path.suffix}"
        destination = self.inbox_dir / queue_name
        if destination.exists():
            counter = 1
            while destination.exists():
                destination = self.inbox_dir / f"{timestamp}_{counter}_{self._safe_name(source_path.name)}{source_path.suffix}"
                counter += 1
        destination.write_bytes(source_path.read_bytes())
        return destination

    def route_drop(self, source_path: Path) -> dict[str, Any]:
        if not source_path.exists() or not source_path.is_file():
            return {"ok": False, "error": "missing file", "path": str(source_path)}

        queued = self._queue_file(source_path)
        extracted = self.extract_text(queued)
        project_dir = self.classify_project(extracted, fallback=self.workspace_dir)
        archive_dir = project_dir / "drop_in"
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self._now_iso().replace(":", "-")
        archive_path = archive_dir / f"{timestamp}_{self._safe_name(queued.name)}.txt"
        log_entry = (
            "---\n"
            f"timestamp={self._now_iso()}\n"
            f"source={source_path}\n"
            f"queued_copy={queued}\n"
            f"project={project_dir}\n"
            f"archive={archive_path}\n"
            f"sha256={self._sha256(queued)}\n"
            "\n"
            f"{extracted[:4000]}\n"
        )
        archive_path.write_text(log_entry, encoding="utf-8")
        project_log = self._append_project_log(project_dir, log_entry)

        payload = {
            "ok": True,
            "source": str(source_path),
            "queued_copy": str(queued),
            "project": str(project_dir),
            "archive_path": str(archive_path),
            "log_path": str(project_log),
            "text_length": len(extracted),
            "timestamp": self._now_iso(),
        }
        self.memory.log_action("watchdog_ingest_routed", **payload)
        self.memory.update_state("last_watchdog_ingest", payload)
        self.memory.update_state("last_ingest_path", str(archive_path))
        return payload

    def _discover_files(self) -> list[Path]:
        discovered: list[Path] = []
        for root in self.watch_roots:
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.iterdir()):
                if path.is_file() and not path.name.startswith("."):
                    discovered.append(path)
        return discovered

    def process_once(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_files = set(self._seen)
        for source in self._discover_files():
            identity = f"{source.resolve()}::{source.stat().st_mtime_ns}::{source.stat().st_size}"
            if identity in seen_files:
                continue
            self._seen.add(identity)
            try:
                result = self.route_drop(source)
                if result.get("ok"):
                    try:
                        source.unlink()
                    except OSError:
                        pass
                else:
                    self.memory.log_action("watchdog_ingest_failed", path=str(source), error=result.get("error"))
            except Exception as exc:  # pragma: no cover - defensive local ingest
                result = {"ok": False, "path": str(source), "error": str(exc)}
                self.memory.log_action("watchdog_ingest_exception", path=str(source), error=str(exc))
            results.append(result)
        return results

    def run_forever(self, *, max_iterations: int | None = None, sleep_seconds: float | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        iterations = 0
        while True:
            batch = self.process_once()
            results.extend(batch)
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(float(sleep_seconds if sleep_seconds is not None else self.poll_interval))
        return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Termux watchdog ingestion daemon.")
    parser.add_argument("--workspace", default="workspace", help="Workspace root to classify routes and keep memory")
    parser.add_argument("--watch-root", action="append", default=[], help="Additional local directory to poll for drops")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Process any queued files once and exit")
    parser.add_argument("--max-iterations", type=int, default=None, help="Maximum iterations for the daemon loop")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    daemon = WatchdogDaemon(workspace_dir=args.workspace, watch_roots=args.watch_root, poll_interval=args.interval)
    if args.once:
        results = daemon.process_once()
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    daemon.run_forever(max_iterations=args.max_iterations)


if __name__ == "__main__":
    main()
