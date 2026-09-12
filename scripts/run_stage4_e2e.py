"""Run isolated real-browser acceptance and stop both servers afterwards."""

import os
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

import httpx
from app.core.config import PROJECT_ROOT


def main():
    out = PROJECT_ROOT / "docs/verification/stage4"
    (out / "screenshots").mkdir(parents=True, exist_ok=True)
    for port in (8014, 3810):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    with tempfile.TemporaryDirectory(prefix="aftersale-stage4-") as directory:
        env = {
            **os.environ,
            "STAGE4_TEST_DATABASE": "sqlite:///" + (Path(directory) / "test.db").as_posix(),
            "BACKEND_URL": "http://127.0.0.1:8014",
            "NEXT_TELEMETRY_DISABLED": "1",
            "PYTHONUTF8": "1",
        }
        backend = [
            sys._base_executable,
            "-I",
            "-S",
            "-c",
            "import site,sys;site.addsitedir(sys.argv[1]);sys.path.insert(0,sys.argv[2]);"
            "import uvicorn;uvicorn.run('scripts.stage4_fixture:app',"
            "host='127.0.0.1',port=8014,proxy_headers=False)",
            sysconfig.get_path("purelib"),
            str(PROJECT_ROOT),
        ]
        node = shutil.which("node")
        frontend = [
            node,
            str(PROJECT_ROOT / "frontend/node_modules/next/dist/bin/next"),
            "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            "3810",
        ]
        processes = []
        with (out / "servers.log").open("w", encoding="utf-8") as log:
            try:
                for command in (backend, frontend):
                    processes.append(
                        subprocess.Popen(
                            command,
                            cwd=PROJECT_ROOT / "frontend",
                            env=env,
                            stdout=log,
                            stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        )
                    )
                with httpx.Client(trust_env=False) as client:
                    for endpoint in ("http://127.0.0.1:8014/health", "http://127.0.0.1:3810/login"):
                        for _ in range(90):
                            try:
                                if client.get(endpoint, timeout=2).status_code == 200:
                                    break
                            except httpx.RequestError:
                                pass
                            if any(p.poll() is not None for p in processes):
                                raise RuntimeError("A test server stopped; inspect servers.log")
                            time.sleep(0.5)
                        else:
                            raise RuntimeError("Test server startup timeout")
                result = subprocess.run(
                    [node, "node_modules/@playwright/test/cli.js", "test"],
                    cwd=PROJECT_ROOT / "frontend",
                    env=env,
                    timeout=600,
                )
                raise SystemExit(result.returncode)
            finally:
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)


if __name__ == "__main__":
    main()
