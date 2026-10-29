# 작성: 2026-10-29 21:50
"""시험 공통 준비. 시험용 PostgreSQL 주소는 TEST_DATABASE_URL로 정합니다(Supabase가 아닌 로컬 DB를 씀)."""

import os
import sys
from pathlib import Path

import pytest

루트 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(루트))

from 디비 import 스키마_만들기, 연결풀_만들기  # noqa: E402

명단폴더 = Path(__file__).with_name("연습명단")


@pytest.fixture(scope="session")
def 풀():
    주소 = os.environ.get("TEST_DATABASE_URL")
    if not 주소:
        pytest.skip("TEST_DATABASE_URL이 없어 DB를 쓰는 시험을 건너뜀")
    풀 = 연결풀_만들기(주소)
    with 풀.connection() as 연결:
        연결.execute(
            "drop table if exists tf_votes, tf_applications, tf_members, tf_teams, "
            "tf_student_sub_roles, tf_students, tf_settings, tf_ai_logs cascade"
        )
    스키마_만들기(풀)
    yield 풀
    풀.close()
