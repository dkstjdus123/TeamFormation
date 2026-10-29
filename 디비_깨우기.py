# 작성: 2026-10-29 22:01
"""Supabase 무료 프로젝트가 일시정지되지 않도록 DB에 질의를 하나 보냅니다.

깃허브 Actions(.github/workflows/db_keepalive.yml)가 매일 한 번 실행합니다.
DATABASE_URL은 깃허브 저장소의 Secrets에서 받으며, 화면이나 기록에 출력하지 않습니다.
"""

import os
import sys

import psycopg

try:
    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None, connect_timeout=20) as 연결:
        학생수 = 연결.execute("select count(*) from tf_students").fetchone()[0]
except Exception as 오류:
    # 오류 문장에 DB 주소가 들어갈 수 있으므로 오류 종류만 출력합니다.
    print(f"DB 질의 실패: {type(오류).__name__}")
    sys.exit(1)
print(f"DB 질의 성공: tf_students {학생수}행")
