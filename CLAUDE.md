<!-- 작성: 2026-10-29 22:05 -->

# CLAUDE.md

중간 과제 "팀 프로젝트를 위한 팀을 편성하는 웹 앱"입니다. 규칙은 `docs/PRD.md`, 구조는 `docs/구현 계획.md`에 있습니다.

## 꼭 지킬 것

- **화면 key는 바꾸지 않습니다.** 자동 채점 프로그램이 공고 2.7절의 key(`login_student_no`, `result`, `team_1`, `apply_1`, `vote_yes_{학번}`, `admin_start`, `assign_status` 등)로 요소를 찾습니다.
- 결과 안내는 "승인", "대기", "거절", "막힘" 가운데 하나로 시작합니다.
- 연습용 시나리오의 학생 이름이나 순서에 맞춘 코드를 넣지 않습니다(공고 6.3절 19번). 규칙은 `규칙.py`의 일반 함수로만 따집니다.
- 키, DB 주소, 관리자 비밀번호를 코드, 화면, 출력, 커밋에 넣지 않습니다. 있는지 확인할 때는 "있음, 없음"만 말합니다.
- 테이블 이름은 `tf_`로 시작하고, 테이블을 바꾸면 `schema.sql`을 고칩니다(앱이 이 파일을 실행함).
- 마감(11/2 23:59) 뒤에는 커밋하지 않습니다.

## 확인 방법

- `python -m pytest -q tests` (로컬 PostgreSQL, `TEST_DATABASE_URL`)
- 앱을 띄운 뒤 `LANG=C.UTF-8 NODE_PATH="$(npm root -g)" node tests/화면_시나리오.cjs http://localhost:8501 관리자비밀번호`
