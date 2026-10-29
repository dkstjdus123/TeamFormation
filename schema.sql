-- 작성: 2026-10-29 21:46
-- 팀 편성 앱이 Supabase에 만드는 테이블입니다. 앱이 시작할 때 이 파일을 그대로 실행하므로
-- 여기 적힌 테이블, 열, 제약이 앱이 실제로 쓰는 것과 같습니다.
-- 모든 테이블 이름은 tf_로 시작합니다(6장 실습 테이블과 구분).

-- 학생과 관리자. 비밀번호는 bcrypt 해시로만 저장합니다.
create table if not exists tf_students (
    id serial primary key,
    student_no text not null unique,
    name text not null,
    main_role text check (main_role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너', '테스터', '보고서 작성자', '발표자')),
    password_hash text not null,
    is_admin boolean not null default false
);

-- 보조 역할. 학생 1명에 0~2행.
create table if not exists tf_student_sub_roles (
    student_id int not null references tf_students(id) on delete cascade,
    role text not null check (role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너', '테스터', '보고서 작성자', '발표자')),
    primary key (student_id, role)
);

-- 팀. team_no는 화면 key(team_1, apply_1 …)에 쓰는 번호입니다.
create table if not exists tf_teams (
    id serial primary key,
    team_no int not null unique,
    name text not null unique
);

-- 팀원. (team_id, slot_no) 기본 키로 한 자리에 한 명만, student_id 유일성으로 한 학생은 한 팀에만 들어갑니다.
-- 마지막 자리에 두 명이 동시에 들어가려 해도 DB가 먼저 도착한 학생만 기록합니다.
create table if not exists tf_members (
    team_id int not null references tf_teams(id) on delete cascade,
    slot_no int not null check (slot_no between 1 and 4),
    student_id int not null unique references tf_students(id) on delete cascade,
    joined_at timestamptz not null default now(),
    primary key (team_id, slot_no)
);

-- 지원. 결과가 나오기 전의 지원(대기)은 학생마다 하나만 있을 수 있습니다.
create table if not exists tf_applications (
    id serial primary key,
    team_id int not null references tf_teams(id) on delete cascade,
    student_id int not null references tf_students(id) on delete cascade,
    status text not null default '대기' check (status in ('대기', '승인', '거절')),
    reason text,
    created_at timestamptz not null default now(),
    decided_at timestamptz
);
create unique index if not exists tf_applications_one_pending
    on tf_applications (student_id) where status = '대기';

-- 투표. 한 지원에 한 팀원은 한 번만 투표합니다.
create table if not exists tf_votes (
    application_id int not null references tf_applications(id) on delete cascade,
    voter_id int not null references tf_students(id) on delete cascade,
    vote text not null check (vote in ('찬성', '거부')),
    created_at timestamptz not null default now(),
    primary key (application_id, voter_id)
);

-- 마감 여부, 확정 여부, 배정안 같은 앱 상태.
create table if not exists tf_settings (
    key text primary key,
    value text not null
);

-- AI 호출 기록. 모델마다 성공, 시간 초과, 빈 응답, 검사 실패 등을 남깁니다.
create table if not exists tf_ai_logs (
    id serial primary key,
    created_at timestamptz not null default now(),
    model_order int not null,
    model text not null,
    outcome text not null,
    detail text,
    elapsed_sec real
);
