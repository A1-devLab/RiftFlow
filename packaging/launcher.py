"""배포판(RiftFlow.exe) 진입점. packaging/build.py가 PyInstaller로 묶는다."""
from ui.__main__ import main

raise SystemExit(main())
