"""Windows 배포판 만들기 (저장소 루트에서 실행).

    python packaging/build.py --server-url https://riftflow-team.duckdns.org

결과: dist/RiftFlow/ (RiftFlow.exe, server.txt, 사용법) 와 dist/RiftFlow-<버전>.zip
배포판에는 API 키가 들어가지 않는다. AI와 전적은 server.txt의 RiftFlow 서버로 처리한다.
서버 주소가 바뀌면 다시 빌드하지 않고 dist/RiftFlow/server.txt만 고쳐도 된다.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = DIST / "RiftFlow"


def version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def build():
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "RiftFlow",
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'src' / 'ui' / 'demo_documents.json'}{os.pathsep}ui",
        # 앱이 쓰지 않는 서버·개발용 패키지는 넣지 않는다.
        "--exclude-module", "server", "--exclude-module", "fastapi", "--exclude-module", "uvicorn",
        "--exclude-module", "starlette", "--exclude-module", "httpx", "--exclude-module", "tkinter",
        "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        str(ROOT / "packaging" / "launcher.py"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description="Build the RiftFlow Windows package")
    parser.add_argument("--server-url", default="", help="RiftFlow 서버 주소 (예: https://riftflow-team.duckdns.org)")
    args = parser.parse_args()
    if args.server_url and not args.server_url.startswith("https://"):
        parser.error("서버 주소는 https:// 로 시작해야 합니다 (기기 토큰과 채팅이 오가므로).")
    build()
    (APP / "server.txt").write_text(args.server_url.strip(), encoding="utf-8")
    shutil.copyfile(ROOT / "packaging" / "README-친구용.txt", APP / "사용법.txt")
    archive = DIST / f"RiftFlow-{version()}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in APP.rglob("*"):
            bundle.write(path, Path("RiftFlow") / path.relative_to(APP))
    size = archive.stat().st_size / 1024 / 1024
    print(f"완료: {archive} ({size:.0f}MB)")
    print(f"서버 주소: {args.server_url or '(없음 - server.txt를 채워야 AI·전적이 동작)'}")


if __name__ == "__main__":
    main()
