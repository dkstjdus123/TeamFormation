# 작성: 2026-10-29 21:46
"""DB 연결. 연결은 한 번만 만들어 연결 풀에 두고, 질의마다 풀에서 빌려 씁니다."""

from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

스키마파일 = Path(__file__).with_name("schema.sql")
쓰기잠금번호 = 20261102


def 연결풀_만들기(주소):
    # prepare_threshold=None: Supabase 연결 풀러(트랜잭션 모드)에서도 문제없이 쓰려고 준비된 문장을 끕니다.
    return ConnectionPool(
        주소,
        min_size=1,
        max_size=5,
        timeout=20,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        check=ConnectionPool.check_connection,
        open=True,
    )


def 스키마_만들기(풀):
    with 풀.connection() as 연결:
        연결.execute(스키마파일.read_text(encoding="utf-8"))


def 쓰기잠금(연결):
    """쓰기 작업을 한 번에 하나씩만 하도록 트랜잭션 안에서 잠급니다. 트랜잭션이 끝나면 저절로 풀립니다."""
    연결.execute("select pg_advisory_xact_lock(%s)", (쓰기잠금번호,))
