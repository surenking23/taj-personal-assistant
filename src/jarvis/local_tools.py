import os
import subprocess
from pathlib import Path

from fastapi import HTTPException

from jarvis.schemas import LocalActionRequest

MAX_READ_BYTES = 256_000
MAX_OUTPUT_CHARS = 16_000
ALLOWED_APPS = {
    "notepad": ("notepad.exe",),
    "calculator": ("calc.exe",),
    "explorer": ("explorer.exe",),
}


class LocalSystemTools:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve()

    def execute(self, request: LocalActionRequest) -> dict:
        action = request.action
        if action == "list_files":
            folder = self._resolve(request.path or ".")
            if not folder.is_dir():
                raise HTTPException(status_code=400, detail="The requested path is not a directory")
            return {
                "path": self._relative(folder),
                "entries": [
                    {"name": item.name, "type": "directory" if item.is_dir() else "file"}
                    for item in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
                ],
            }
        if action == "read_file":
            file_path = self._resolve(request.path or "")
            if not file_path.is_file():
                raise HTTPException(status_code=404, detail="File not found")
            if file_path.stat().st_size > MAX_READ_BYTES:
                raise HTTPException(status_code=413, detail="File exceeds the 256 KB read limit")
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise HTTPException(status_code=415, detail="File is not valid UTF-8 text") from error
            return {"path": self._relative(file_path), "content": content}
        if action == "create_file":
            file_path = self._resolve(request.path or "")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with file_path.open("x", encoding="utf-8", newline="") as output:
                    output.write(request.content or "")
            except FileExistsError as error:
                raise HTTPException(
                    status_code=409,
                    detail="File already exists; use the approval-gated update action to overwrite it",
                ) from error
            return {"path": self._relative(file_path), "created": True}
        if action == "update_file":
            file_path = self._resolve(request.path or "")
            if not file_path.is_file():
                raise HTTPException(status_code=404, detail="File not found")
            file_path.write_text(request.content or "", encoding="utf-8")
            return {"path": self._relative(file_path), "updated": True}
        if action == "delete_file":
            file_path = self._resolve(request.path or "")
            if not file_path.is_file():
                raise HTTPException(status_code=404, detail="File not found")
            file_path.unlink()
            return {"path": self._relative(file_path), "deleted": True}
        if action == "launch_app":
            app_name = (request.app_name or "").casefold()
            executable = ALLOWED_APPS.get(app_name)
            if executable is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"App not allow-listed. Available apps: {', '.join(ALLOWED_APPS)}",
                )
            subprocess.Popen(list(executable), cwd=self.workspace)
            return {"app": app_name, "launched": True}
        if action == "run_command":
            return self._run_command(request.command or "")
        raise HTTPException(status_code=400, detail="Unsupported local action")

    def _resolve(self, relative_path: str) -> Path:
        if not relative_path:
            raise HTTPException(status_code=422, detail="A workspace-relative path is required")
        candidate = (self.workspace / relative_path).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as error:
            raise HTTPException(status_code=403, detail="Path must stay inside the configured workspace") from error
        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix() or "."

    def _run_command(self, command: str) -> dict:
        if not command.strip():
            raise HTTPException(status_code=422, detail="A command is required")
        if os.name != "nt":
            raise HTTPException(status_code=501, detail="Approved shell execution is currently Windows-only")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise HTTPException(status_code=408, detail="Command exceeded the 30 second time limit") from error
        except OSError as error:
            raise HTTPException(status_code=500, detail="PowerShell could not be started") from error
        return {
            "return_code": result.returncode,
            "stdout": result.stdout[:MAX_OUTPUT_CHARS],
            "stderr": result.stderr[:MAX_OUTPUT_CHARS],
            "output_truncated": len(result.stdout) > MAX_OUTPUT_CHARS or len(result.stderr) > MAX_OUTPUT_CHARS,
        }
