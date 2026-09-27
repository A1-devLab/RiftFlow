"""DuckDNS 주소가 집의 현재 IP를 가리키도록 갱신한다. 5분마다 cron으로 실행.

서버에 curl이 없어서 표준 라이브러리로 만들었다.
설정 파일(본인만 읽기):
  ~/.config/duckdns/domain  예: riftflow-team   (.duckdns.org 앞부분만)
  ~/.config/duckdns/token   DuckDNS 사이트의 token
"""
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG = Path.home() / ".config" / "duckdns"


def main():
    domain = (CONFIG / "domain").read_text(encoding="utf-8").strip()
    token = (CONFIG / "token").read_text(encoding="utf-8").strip()
    query = urllib.parse.urlencode({"domains": domain, "token": token, "ip": ""})
    with urllib.request.urlopen("https://www.duckdns.org/update?" + query, timeout=20) as response:
        result = response.read().decode().strip()
    if result != "OK":
        print("DuckDNS 갱신 실패: %s" % result, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
