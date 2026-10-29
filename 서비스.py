# 작성: 2026-10-29 21:48 (수정: 2026-10-29 22:55 지원 기록 읽기, AI를 끄고 배정하기 추가)
"""앱이 하는 일(로그인, 명단 올리기, 지원, 투표, 마감, 배정, 확정)을 DB에 반영하는 함수 모음.

화면 쪽에 돌려주는 안내는 모두 "승인", "대기", "거절", "막힘" 가운데 하나로 시작합니다.
쓰기 작업은 트랜잭션 안에서 쓰기잠금을 걸고 하므로 여러 학생이 동시에 눌러도 한 번에 하나씩 처리됩니다.
"""

import csv
import io
import json
from dataclasses import dataclass, field

import bcrypt
from psycopg.errors import UniqueViolation

import 인공지능
from 디비 import 쓰기잠금
from 규칙 import (
    역할목록,
    최대인원,
    학생,
    지원_검사,
    배정안_검사,
    배정_찾기,
    배정불가_사유,
)

관리자학번 = "admin"
학생비밀번호 = "1234"
명단열 = ["student_no", "name", "main_role", "sub_roles"]


def 해시_만들기(비밀번호):
    return bcrypt.hashpw(비밀번호.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def 해시_맞음(비밀번호, 해시):
    return bcrypt.checkpw(비밀번호.encode("utf-8"), 해시.encode("ascii"))


# ---------------------------------------------------------------- 상태 읽기


@dataclass
class 대기지원:
    id: int
    지원자: str
    팀번호: int
    찬성: set = field(default_factory=set)
    거부: set = field(default_factory=set)


@dataclass
class 앱상태:
    학생들: dict  # 학번 -> 학생 (관리자 제외)
    학생id: dict  # 학번 -> DB id
    팀들: list  # [{"번호", "이름", "id", "팀원": [학번, ...]}] 팀 번호 순서
    대기지원들: list
    최근지원: dict  # 학번 -> {"팀번호", "상태", "사유"}
    마감: bool
    확정: bool
    배정안: dict | None

    def 팀(self, 팀번호):
        return next((팀 for 팀 in self.팀들 if 팀["번호"] == 팀번호), None)

    def 소속팀(self, 학번):
        return next((팀["번호"] for 팀 in self.팀들 if 학번 in 팀["팀원"]), None)

    def 대기지원_찾기(self, 학번):
        return next((지원 for 지원 in self.대기지원들 if 지원.지원자 == 학번), None)

    def 팀별팀원(self):
        return {팀["번호"]: [self.학생들[학번] for 학번 in 팀["팀원"]] for 팀 in self.팀들}

    def 팀이름들(self):
        return {팀["번호"]: 팀["이름"] for 팀 in self.팀들}

    def 미배정(self):
        소속 = {학번 for 팀 in self.팀들 for 학번 in 팀["팀원"]}
        return [사람 for 학번, 사람 in self.학생들.items() if 학번 not in 소속]


def _상태_읽기(연결):
    학생줄들 = 연결.execute(
        """select s.id, s.student_no, s.name, s.main_role, s.is_admin,
                  coalesce(array_agg(r.role order by r.role) filter (where r.role is not null), '{}') as sub_roles
             from tf_students s left join tf_student_sub_roles r on r.student_id = s.id
            group by s.id order by s.student_no"""
    ).fetchall()
    학생들, 학생id, id학번 = {}, {}, {}
    for 줄 in 학생줄들:
        id학번[줄["id"]] = 줄["student_no"]
        if 줄["is_admin"]:
            continue
        학생들[줄["student_no"]] = 학생(줄["student_no"], 줄["name"], 줄["main_role"], tuple(줄["sub_roles"]))
        학생id[줄["student_no"]] = 줄["id"]

    팀줄들 = 연결.execute("select id, team_no, name from tf_teams order by team_no").fetchall()
    팀들 = [{"번호": 줄["team_no"], "이름": 줄["name"], "id": 줄["id"], "팀원": []} for 줄 in 팀줄들]
    id팀 = {팀["id"]: 팀 for 팀 in 팀들}
    for 줄 in 연결.execute("select team_id, student_id from tf_members order by team_id, slot_no"):
        id팀[줄["team_id"]]["팀원"].append(id학번[줄["student_id"]])

    대기지원들, 최근지원, id지원 = [], {}, {}
    for 줄 in 연결.execute("select id, team_id, student_id, status, reason from tf_applications order by id"):
        학번, 팀번호 = id학번[줄["student_id"]], id팀[줄["team_id"]]["번호"]
        최근지원[학번] = {"팀번호": 팀번호, "상태": 줄["status"], "사유": 줄["reason"]}
        if 줄["status"] == "대기":
            지원 = 대기지원(줄["id"], 학번, 팀번호)
            대기지원들.append(지원)
            id지원[줄["id"]] = 지원
    for 줄 in 연결.execute("select application_id, voter_id, vote from tf_votes"):
        지원 = id지원.get(줄["application_id"])
        if 지원:
            (지원.찬성 if 줄["vote"] == "찬성" else 지원.거부).add(id학번[줄["voter_id"]])

    설정 = {줄["key"]: 줄["value"] for 줄 in 연결.execute("select key, value from tf_settings")}
    return 앱상태(
        학생들=학생들,
        학생id=학생id,
        팀들=팀들,
        대기지원들=대기지원들,
        최근지원=최근지원,
        마감=설정.get("closed") == "1",
        확정=설정.get("confirmed") == "1",
        배정안=json.loads(설정["proposal"]) if "proposal" in 설정 else None,
    )


def 상태_읽기(풀):
    with 풀.connection() as 연결, 연결.transaction():
        return _상태_읽기(연결)


def _설정_쓰기(연결, 키, 값):
    연결.execute(
        "insert into tf_settings (key, value) values (%s, %s) on conflict (key) do update set value = excluded.value",
        (키, 값),
    )


def _빈자리(연결, 팀id):
    쓴자리 = {줄["slot_no"] for 줄 in 연결.execute("select slot_no from tf_members where team_id = %s", (팀id,))}
    return min(set(range(1, 최대인원 + 1)) - 쓴자리)


# ---------------------------------------------------------------- 계정


def 관리자_준비(풀, 비밀번호):
    """앱이 시작할 때 관리자 계정을 만들거나 비밀번호를 ADMIN_PASSWORD로 갱신합니다."""
    with 풀.connection() as 연결, 연결.transaction():
        쓰기잠금(연결)
        줄 = 연결.execute(
            "select id, password_hash from tf_students where student_no = %s", (관리자학번,)
        ).fetchone()
        if 줄 and 해시_맞음(비밀번호, 줄["password_hash"]):
            return
        if 줄:
            연결.execute("update tf_students set password_hash = %s, is_admin = true where id = %s", (해시_만들기(비밀번호), 줄["id"]))
        else:
            연결.execute(
                "insert into tf_students (student_no, name, main_role, password_hash, is_admin) values (%s, %s, null, %s, true)",
                (관리자학번, "관리자", 해시_만들기(비밀번호)),
            )


def 로그인(풀, 학번, 비밀번호):
    """학번과 비밀번호가 맞으면 사용자 정보를, 틀리면 None을 돌려줍니다."""
    with 풀.connection() as 연결:
        줄 = 연결.execute(
            "select student_no, name, is_admin, password_hash from tf_students where student_no = %s",
            (학번.strip(),),
        ).fetchone()
    if 줄 is None or not 해시_맞음(비밀번호, 줄["password_hash"]):
        return None
    return {"학번": 줄["student_no"], "이름": 줄["name"], "관리자": 줄["is_admin"]}


def 사용자_찾기(풀, 학번):
    with 풀.connection() as 연결:
        줄 = 연결.execute("select student_no, name, is_admin from tf_students where student_no = %s", (학번,)).fetchone()
    return None if 줄 is None else {"학번": 줄["student_no"], "이름": 줄["name"], "관리자": 줄["is_admin"]}


# ---------------------------------------------------------------- 명단


def 명단_읽기(내용):
    """명단 CSV(BOM이 있어도 됨)를 읽어 학생 목록을 돌려줍니다. 형식이 틀리면 ValueError를 냅니다."""
    try:
        글 = 내용.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV가 UTF-8이 아님")
    읽개 = csv.DictReader(io.StringIO(글))
    if [이름.strip() for 이름 in (읽개.fieldnames or [])] != 명단열:
        raise ValueError(f"첫 줄은 {','.join(명단열)} 이어야 함")
    학생들, 본학번 = [], set()
    for 줄번호, 줄 in enumerate(읽개, start=2):
        값 = {키.strip(): (값 or "").strip() for 키, 값 in 줄.items() if 키}
        if not any(값.values()):
            continue
        학번, 이름, 주역할 = 값["student_no"], 값["name"], 값["main_role"]
        보조역할 = tuple(역할.strip() for 역할 in 값["sub_roles"].split(";") if 역할.strip())
        if not 학번 or not 이름:
            raise ValueError(f"{줄번호}번째 줄에 학번이나 이름이 없음")
        if 학번 == 관리자학번 or 학번 in 본학번:
            raise ValueError(f"{줄번호}번째 줄의 학번 {학번}을 쓸 수 없음(관리자 학번이거나 중복)")
        if 주역할 not in 역할목록:
            raise ValueError(f"{줄번호}번째 줄의 주 역할 '{주역할}'이 6개 역할에 없음")
        if len(보조역할) > 2 or any(역할 not in 역할목록 for 역할 in 보조역할):
            raise ValueError(f"{줄번호}번째 줄의 보조 역할 '{값['sub_roles']}'이 틀림(6개 역할 가운데 0~2개)")
        본학번.add(학번)
        학생들.append(학생(학번, 이름, 주역할, 보조역할))
    if not 학생들:
        raise ValueError("학생이 한 명도 없음")
    return 학생들


def 명단_올리기(풀, 내용, 팀수):
    """명단과 팀 수로 처음 상태를 만듭니다. 관리자 계정과 AI 호출 기록은 남깁니다."""
    try:
        학생들 = 명단_읽기(내용)
    except ValueError as 오류:
        return f"막힘: 명단을 읽지 못함({오류})"
    if 팀수 < 1:
        return "막힘: 팀 수는 1 이상이어야 함"
    해시들 = [해시_만들기(학생비밀번호) for _ in 학생들]
    with 풀.connection() as 연결, 연결.transaction():
        쓰기잠금(연결)
        for 테이블 in ("tf_votes", "tf_applications", "tf_members", "tf_teams", "tf_settings"):
            연결.execute(f"delete from {테이블}")
        연결.execute("delete from tf_students where not is_admin")
        for 사람, 해시 in zip(학생들, 해시들):
            새id = 연결.execute(
                "insert into tf_students (student_no, name, main_role, password_hash) values (%s, %s, %s, %s) returning id",
                (사람.학번, 사람.이름, 사람.주역할, 해시),
            ).fetchone()["id"]
            for 역할 in 사람.보조역할:
                연결.execute("insert into tf_student_sub_roles (student_id, role) values (%s, %s)", (새id, 역할))
        for 번호 in range(1, 팀수 + 1):
            연결.execute("insert into tf_teams (team_no, name) values (%s, %s)", (번호, f"팀{번호}"))
    return f"승인: 명단을 올려 처음 상태를 만듦(학생 {len(학생들)}명, 팀 {팀수}개)"


# ---------------------------------------------------------------- 지원과 투표


def _쓰기(풀, 작업, *인자):
    """쓰기 작업을 잠금을 건 트랜잭션 안에서 실행합니다."""
    try:
        with 풀.connection() as 연결, 연결.transaction():
            쓰기잠금(연결)
            return 작업(연결, _상태_읽기(연결), *인자)
    except UniqueViolation:
        # 잠금이 있어도 DB 유일성 제약이 마지막으로 한 번 더 막아 줍니다.
        return "막힘: 다른 학생이 먼저 그 자리에 들어감. 다시 시도해 주세요"


def 지원하기(풀, 학번, 팀번호):
    return _쓰기(풀, _지원_처리, 학번, 팀번호)


def _지원_처리(연결, 상태, 학번, 팀번호):
    지원자 = 상태.학생들.get(학번)
    팀 = 상태.팀(팀번호)
    if 지원자 is None:
        return "막힘: 학생 계정만 지원할 수 있음"
    if 팀 is None:
        return "막힘: 없는 팀임"
    if 상태.마감:
        return "막힘: 모집이 마감됨"
    if 상태.소속팀(학번) is not None:
        return "막힘: 이미 팀이 있음"
    if 상태.대기지원_찾기(학번):
        return "막힘: 결과를 기다리는 지원이 있음"
    팀원들 = 상태.팀별팀원()[팀번호]
    사유 = 지원_검사(팀원들, 지원자)
    if 사유:
        return f"막힘: {사유}"
    if not 팀원들:
        연결.execute(
            "insert into tf_applications (team_id, student_id, status, reason, decided_at) values (%s, %s, '승인', '빈 팀에 지원', now())",
            (팀["id"], 상태.학생id[학번]),
        )
        연결.execute(
            "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
            (팀["id"], _빈자리(연결, 팀["id"]), 상태.학생id[학번]),
        )
        return f"승인: {팀['이름']}에 바로 들어감(빈 팀이라 투표할 팀원이 없음)"
    연결.execute(
        "insert into tf_applications (team_id, student_id, status) values (%s, %s, '대기')",
        (팀["id"], 상태.학생id[학번]),
    )
    return f"대기: {팀['이름']} 팀원 {len(팀원들)}명의 투표를 기다림"


def 투표하기(풀, 투표자, 지원자, 찬성):
    return _쓰기(풀, _투표_처리, 투표자, 지원자, 찬성)


def _투표_처리(연결, 상태, 투표자, 지원자학번, 찬성):
    if 투표자 not in 상태.학생들:
        return "막힘: 학생 계정만 투표할 수 있음"
    if 상태.마감:
        return "막힘: 모집이 마감됨"
    지원 = 상태.대기지원_찾기(지원자학번)
    if 지원 is None:
        return "막힘: 결과를 기다리는 지원이 없음"
    팀 = 상태.팀(지원.팀번호)
    if 투표자 not in 팀["팀원"]:
        return "막힘: 그 팀의 팀원만 투표할 수 있음"
    if 투표자 in 지원.찬성 | 지원.거부:
        return "막힘: 이미 투표함"
    지원자 = 상태.학생들[지원자학번]
    연결.execute(
        "insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)",
        (지원.id, 상태.학생id[투표자], "찬성" if 찬성 else "거부"),
    )
    if not 찬성:
        _지원_끝내기(연결, 지원.id, "거절", "팀원 거부")
        return f"거절: {지원자.이름}의 {팀['이름']} 지원이 팀원의 거부로 거절됨"

    찬성한팀원 = (지원.찬성 | {투표자}) & set(팀["팀원"])
    if len(찬성한팀원) < len(팀["팀원"]):
        return f"대기: 찬성 {len(찬성한팀원)}명 / 팀원 {len(팀['팀원'])}명"

    # 모든 팀원이 찬성했으므로 승인 직전에 규칙을 다시 검사합니다.
    # 같은 팀에 대기 중인 지원이 여럿이면 앞의 지원이 먼저 승인되어 팀이 바뀌었을 수 있기 때문입니다.
    사유 = 지원_검사(상태.팀별팀원()[팀["번호"]], 지원자)
    if 사유:
        _지원_끝내기(연결, 지원.id, "거절", f"승인 직전 검사: {사유}")
        return f"거절: 승인 직전 검사에서 걸림({사유})"
    연결.execute(
        "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
        (팀["id"], _빈자리(연결, 팀["id"]), 상태.학생id[지원자학번]),
    )
    _지원_끝내기(연결, 지원.id, "승인", "팀원 모두 찬성")
    return f"승인: {지원자.이름}이(가) {팀['이름']}의 팀원이 됨"


def _지원_끝내기(연결, 지원id, 결과, 사유):
    연결.execute(
        "update tf_applications set status = %s, reason = %s, decided_at = now() where id = %s",
        (결과, 사유, 지원id),
    )


def 지원기록_읽기(풀, 학번=None):
    """지원 기록을 지원한 순서로 돌려줍니다. 학번을 주면 그 학생의 기록만 돌려줍니다."""
    with 풀.connection() as 연결:
        return 연결.execute(
            """select s.name as 지원자, t.name as 팀, a.status as 상태, coalesce(a.reason, '') as 사유,
                      (select count(*) from tf_votes v where v.application_id = a.id and v.vote = '찬성') as 찬성,
                      a.created_at as 시각
                 from tf_applications a
                 join tf_students s on s.id = a.student_id
                 join tf_teams t on t.id = a.team_id
                where %(학번)s::text is null or s.student_no = %(학번)s
                order by a.id""",
            {"학번": 학번},
        ).fetchall()


# ---------------------------------------------------------------- 마감, 배정, 확정


def 모집_마감(풀):
    return _쓰기(풀, _마감_처리)


def _마감_처리(연결, 상태):
    if 상태.마감:
        return "막힘: 이미 모집이 마감됨"
    거절수 = 연결.execute(
        "update tf_applications set status = '거절', reason = '모집 마감', decided_at = now() where status = '대기'"
    ).rowcount
    빠진수 = 연결.execute(
        """delete from tf_members where team_id in
               (select team_id from tf_members group by team_id having count(*) = 1)"""
    ).rowcount
    _설정_쓰기(연결, "closed", "1")
    return f"승인: 모집을 마감함(대기 중이던 지원 {거절수}건 거절, 1명뿐인 팀에서 {빠진수}명이 빠짐)"


def _배정안_쓰기(풀, 배정안):
    with 풀.connection() as 연결, 연결.transaction():
        쓰기잠금(연결)
        if 배정안 is None:
            연결.execute("delete from tf_settings where key = 'proposal'")
        else:
            _설정_쓰기(연결, "proposal", json.dumps(배정안, ensure_ascii=False))


def AI기록_쓰기(풀, 순서, 모델, 결과, 내용, 걸린초):
    with 풀.connection() as 연결:
        연결.execute(
            "insert into tf_ai_logs (model_order, model, outcome, detail, elapsed_sec) values (%s, %s, %s, %s, %s)",
            (순서, 모델, 결과, 내용[:2000], 걸린초),
        )


def AI기록_읽기(풀, 개수=30):
    with 풀.connection() as 연결:
        return 연결.execute(
            "select created_at, model_order, model, outcome, detail, elapsed_sec from tf_ai_logs order by id desc limit %s",
            (개수,),
        ).fetchall()


def AI_배정(풀, 키, 모델들, 진행표시=lambda 문장: None, 제한초=인공지능.모델제한초, 주소=인공지능.오픈라우터주소, AI사용=True):
    """남은 학생의 배정안을 AI에게 받아 검사합니다. (결과 안내, 진행 안내)를 돌려줍니다.

    모델마다 제한초 안에 답하지 않거나, 빈 응답, 오류, 검사 실패이면 다음 모델로 넘어갑니다.
    3차 모델까지 실패하면 앱이 모든 경우를 따져 규칙을 지키는 배정을 스스로 찾습니다.
    AI사용이 False이면 AI를 부르지 않고 바로 앱이 배정합니다(연습할 때 AI 호출 횟수를 아끼려고).
    """
    상태 = 상태_읽기(풀)
    if not 상태.마감:
        return "막힘: 먼저 모집을 마감해 주세요", "모집을 마감한 뒤에 배정할 수 있습니다."
    if 상태.확정:
        return "막힘: 이미 배정을 확정함", "이미 확정했습니다. 다시 하려면 명단을 다시 올려 주세요."
    팀별팀원, 팀이름들, 미배정 = 상태.팀별팀원(), 상태.팀이름들(), 상태.미배정()

    if 배정_찾기(팀별팀원, 미배정) is None:
        _배정안_쓰기(풀, None)
        사유 = 배정불가_사유(팀별팀원, 팀이름들, 미배정)
        return "막힘: 규칙을 지키는 배정이 없음", f"규칙을 지키는 배정이 없음: {사유}"
    if not 미배정:
        _배정안_쓰기(풀, {"배정": {}, "출처": "팀이 없는 학생이 없음"})
        return "승인: 팀이 없는 학생이 없어 지금 팀 구성을 배정안으로 만듦", "AI를 부르지 않았습니다(팀이 없는 학생이 없음)."
    if not AI사용:
        _배정안_쓰기(풀, {"배정": 배정_찾기(팀별팀원, 미배정), "출처": "앱이 직접 배정함(AI를 부르지 않음)"})
        return "승인: AI를 부르지 않고 앱이 직접 배정안을 만듦", "AI를 부르지 않았습니다(관리자가 끔)."

    질문 =인공지능.배정_질문_만들기(팀별팀원, 팀이름들, 미배정)
    경과들 = []
    for 순서, 모델 in enumerate(모델들, start=1):
        진행표시(f"{순서}차 모델({모델})의 응답을 기다리는 중 (0초 / {제한초}초)")
        결과 = 인공지능.모델_부르기(
            키, 모델, 질문, 제한초,
            lambda 초, 순서=순서, 모델=모델: 진행표시(f"{순서}차 모델({모델})의 응답을 기다리는 중 ({초}초 / {제한초}초)"),
            주소,
        )
        종류, 내용 = 결과.종류, 결과.내용
        if 결과.성공:
            배정, 문제들 = 인공지능.배정_해석(결과.내용)
            if 배정 is not None:
                문제들 = 배정안_검사(팀별팀원, 팀이름들, 미배정, 배정)
            if not 문제들:
                AI기록_쓰기(풀, 순서, 모델, "성공", 결과.내용, 결과.걸린초)
                _배정안_쓰기(풀, {"배정": 배정, "출처": f"{순서}차 모델({모델})"})
                경과들.append(f"{순서}차 모델({모델}): 성공, 검사 통과 ({결과.걸린초:.0f}초)")
                return f"승인: {순서}차 모델의 배정안이 검사를 통과함", " → ".join(경과들)
            종류, 내용 = "검사 실패", "; ".join(문제들)
        AI기록_쓰기(풀, 순서, 모델, 종류, 내용, 결과.걸린초)
        경과들.append(f"{순서}차 모델({모델}): {종류} ({내용[:150]}) ({결과.걸린초:.0f}초)")

    배정 = 배정_찾기(팀별팀원, 미배정)
    _배정안_쓰기(풀, {"배정": 배정, "출처": "앱이 직접 배정함(3차 모델까지 실패)"})
    경과들.append("3차 모델까지 실패해 앱이 모든 경우를 따져 규칙을 지키는 배정을 찾음")
    return "승인: 3차 모델까지 실패해 앱이 직접 배정안을 만듦", " → ".join(경과들)


def 배정_확정(풀):
    return _쓰기(풀, _확정_처리)


def _확정_처리(연결, 상태):
    if not 상태.마감:
        return "막힘: 먼저 모집을 마감해 주세요"
    if 상태.확정:
        return "막힘: 이미 배정을 확정함"
    if 상태.배정안 is None:
        return "막힘: 확정할 배정안이 없음. 먼저 AI 배정을 눌러 주세요"
    배정 = {학번: int(팀) for 학번, 팀 in 상태.배정안["배정"].items()}
    문제들 = 배정안_검사(상태.팀별팀원(), 상태.팀이름들(), 상태.미배정(), 배정)
    if 문제들:
        return f"막힘: 배정안이 지금 상태와 맞지 않음({'; '.join(문제들)})"
    for 학번, 팀번호 in 배정.items():
        팀id = 상태.팀(팀번호)["id"]
        연결.execute(
            "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
            (팀id, _빈자리(연결, 팀id), 상태.학생id[학번]),
        )
    연결.execute("delete from tf_settings where key = 'proposal'")
    _설정_쓰기(연결, "confirmed", "1")
    return f"승인: 배정안을 확정함(학생 {len(배정)}명 배정)"
