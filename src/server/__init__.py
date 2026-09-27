"""RiftFlow API server: holds the Riot key, caches Riot data, and rate-limits devices.

실행: uvicorn server.app:create_app --factory --host 127.0.0.1 --port 8787
설계: docs/server-architecture.md, 배포: docs/server-deploy.md
"""
