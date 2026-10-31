# 작성: 2026-10-29 21:57 (수정: 2026-10-29 22:55 시범 앱 녹화를 보고 지원 기록, AI 끄기, 팀 칸 나란히 보기 추가; 2026-10-30 01:27 DB 연결 실패를 관리자 계정 준비 단계에서도 짧은 안내로 보여 줌; 2026-10-31 23:16 AI 배정을 화면 실행과 따로 도는 스레드로 옮겨 연결이 끊겨도 끝까지 진행되게 함)
"""팀 프로젝트를 위한 팀 편성 웹 앱(Streamlit).

화면 요소의 key는 공고 2.7절 표를 그대로 따릅니다. 자동 채점 프로그램이 key로 요소를 찾기 때문입니다.
다른 사람의 변경은 st.fragment가 3초마다 바뀐 부분만 다시 그려 보여 줍니다.
"""

import hashlib
import os
import threading
import time
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

import 서비스
import 인공지능
from 디비 import 스키마_만들기, 연결풀_만들기

다시그리기초 = 3
한국시간 = ZoneInfo("Asia/Seoul")

st.set_page_config(page_title="팀 편성", page_icon="👥", layout="wide")
load_dotenv()


def 설정값(이름, 기본=""):
    """.env(로컬) 또는 Streamlit Secrets(배포)에서 값을 읽습니다. 값을 화면에 출력하지 않습니다."""
    값 = os.environ.get(이름)
    if 값:
        return 값
    try:
        return st.secrets.get(이름, 기본)
    except Exception:
        return 기본


@st.cache_resource(show_spinner="DB에 연결하는 중입니다.")
def 풀_가져오기(_주소, 지문):
    # 지문(주소의 해시)이 같으면 앱이 살아 있는 동안 같은 연결 풀을 다시 씁니다.
    풀 = 연결풀_만들기(_주소)
    스키마_만들기(풀)
    return 풀


@st.cache_resource(show_spinner=False)
def 관리자_준비됨(_풀, _비밀번호, 지문):
    서비스.관리자_준비(_풀, _비밀번호)
    return True


def 지문(값):
    return hashlib.sha256(값.encode("utf-8")).hexdigest()


class AI배정작업:
    """AI 배정을 화면 실행과 따로 도는 스레드에서 진행합니다.

    화면은 다시 그려지거나 브라우저 연결이 잠깐 끊기면 하던 실행을 멈춥니다. AI 배정을 화면 실행 안에서 하면
    몇 분짜리 배정이 중간에 조용히 사라지므로, 스레드에서 끝까지 하고 화면은 진행 안내와 결과만 가져다 보여 줍니다.
    """

    def __init__(self):
        self.잠금 = threading.Lock()
        self.진행중 = False
        self.번호 = 0  # 지금(또는 마지막) 작업의 번호
        self.진행안내 = ""
        self.결과 = ""  # 마지막 작업의 결과 안내(승인/막힘)
        self.안내 = ""  # 마지막 작업의 진행 경과

    def 시작(self, 풀, 키, 모델들, AI사용):
        with self.잠금:
            if self.진행중:
                return self.번호
            self.진행중 = True
            self.번호 += 1
            self.진행안내 = "AI 배정을 시작하는 중"
            번호 = self.번호

        def 실행():
            try:
                결과, 안내 = 서비스.AI_배정(풀, 키, 모델들, 진행표시=self._진행_적기, AI사용=AI사용)
            except Exception as 오류:
                결과 = f"막힘: AI 배정 중 오류가 남({type(오류).__name__}). 다시 눌러 주세요"
                안내 = "AI 배정 중 오류가 났습니다."
            with self.잠금:
                self.결과, self.안내, self.진행중 = 결과, 안내, False

        threading.Thread(target=실행, daemon=True).start()
        return 번호

    def _진행_적기(self, 문장):
        self.진행안내 = 문장


@st.cache_resource(show_spinner=False)
def AI배정작업_가져오기():
    # 앱이 살아 있는 동안 모든 화면이 같은 작업 상태를 봅니다.
    return AI배정작업()


# ---------------------------------------------------------------- 공통


def 결과_보이기():
    """단추를 누른 결과 안내. key가 result인 컨테이너 안에 보입니다."""
    with st.container(key="result"):
        결과 = st.session_state.get("결과")
        if not 결과:
            return
        if 결과.startswith("승인"):
            st.success(결과)
        elif 결과.startswith("대기"):
            st.info(결과)
        else:
            st.error(결과)


def 결과_정하기(결과):
    st.session_state["결과"] = 결과


def 로그아웃():
    for 이름 in ("사용자", "결과", "기다리는작업"):
        st.session_state.pop(이름, None)


def 팀원_줄(사람):
    return f"- {사람.표시()}"


def 팀칸들(팀수):
    """팀 카드를 한 줄에 4개까지 나란히 놓을 칸을 만듭니다."""
    return [칸 for 시작 in range(0, 팀수, 4) for 칸 in st.columns(4)][:팀수]


def 지원기록_표(기록들, 지원자_보임):
    if not 기록들:
        st.caption("지원 기록이 없습니다.")
        return
    줄들 = []
    for 기록 in 기록들:
        줄 = {"지원자": 기록["지원자"]} if 지원자_보임 else {}
        줄 |= {"팀": 기록["팀"], "상태": 기록["상태"], "사유": 기록["사유"]}
        if 지원자_보임:
            줄["찬성"] = 기록["찬성"]
        줄["시각"] = 기록["시각"].astimezone(한국시간).strftime("%m-%d %H:%M:%S")
        줄들.append(줄)
    st.dataframe(줄들, hide_index=True)


# ---------------------------------------------------------------- 로그인


def 로그인_누름(풀):
    학번 = st.session_state.get("login_student_no", "").strip()
    비밀번호 = st.session_state.get("login_password", "")
    사용자 = 서비스.로그인(풀, 학번, 비밀번호) if 학번 and 비밀번호 else None
    if 사용자 is None:
        결과_정하기("막힘: 학번 또는 비밀번호가 맞지 않음")
        return
    st.session_state["사용자"] = 사용자["학번"]
    결과_정하기(f"승인: {사용자['이름']}(으)로 로그인함")


def 로그인_화면(풀):
    st.title("팀 편성")
    st.caption("학번과 비밀번호로 로그인해 주세요. 관리자는 학번에 admin을 넣습니다.")
    st.text_input("학번", key="login_student_no")
    st.text_input("비밀번호", type="password", key="login_password")
    st.button("로그인", key="login_submit", type="primary", on_click=로그인_누름, args=(풀,))
    결과_보이기()


# ---------------------------------------------------------------- 학생 화면


def 지원_누름(풀, 학번, 팀번호):
    결과_정하기(서비스.지원하기(풀, 학번, 팀번호))


def 투표_누름(풀, 학번, 지원자, 찬성):
    결과_정하기(서비스.투표하기(풀, 학번, 지원자, 찬성))


@st.fragment(run_every=다시그리기초)
def 학생_본문(풀, 학번):
    상태 = 서비스.상태_읽기(풀)
    결과_보이기()
    if 학번 not in 상태.학생들:
        st.warning("명단에 없는 학생입니다. 로그아웃한 뒤 다시 로그인해 주세요.")
        return
    내팀 = 상태.소속팀(학번)
    내지원 = 상태.대기지원_찾기(학번)
    팀이름들 = 상태.팀이름들()

    if 내팀 is not None:
        st.markdown(f"**내 팀: {팀이름들[내팀]}**")
    else:
        st.markdown("**아직 팀이 없음**")
    if 내지원:
        팀원수 = len(상태.팀(내지원.팀번호)["팀원"])
        st.info(f"{팀이름들[내지원.팀번호]}에 지원함: 대기 중 (찬성 {len(내지원.찬성)}명 / 팀원 {팀원수}명)")
    elif 내팀 is None and (최근 := 상태.최근지원.get(학번)) and 최근["상태"] == "거절":
        st.caption(f"최근 지원: {팀이름들[최근['팀번호']]} 거절 ({최근['사유']}). 다른 팀에 다시 지원할 수 있습니다.")
    if 상태.마감:
        st.warning("모집이 마감되어 지원과 투표를 할 수 없습니다.")

    지원막힘 = 내팀 is not None or 내지원 is not None or 상태.마감
    st.subheader("팀 목록")
    if 내팀 is not None:
        st.caption(f"지원 단추를 쓸 수 없음: 이미 {팀이름들[내팀]}에 속해 있습니다.")
    elif 내지원:
        st.caption(f"지원 단추를 쓸 수 없음: {팀이름들[내지원.팀번호]}에 낸 지원이 대기 중입니다. 결과가 나온 뒤 다시 지원할 수 있습니다.")
    elif 상태.마감:
        st.caption("지원 단추를 쓸 수 없음: 모집이 마감되었습니다.")
    st.caption(f"화면은 {다시그리기초}초마다 저절로 바뀝니다.")
    for 팀, 칸 in zip(상태.팀들, 팀칸들(len(상태.팀들))):
        with 칸, st.container(key=f"team_{팀['번호']}", border=True):
            표시 = " (내 팀)" if 팀["번호"] == 내팀 else ""
            st.markdown(f"**{팀['이름']}{표시}** · {len(팀['팀원'])}/4명")
            for 팀원 in 팀["팀원"]:
                st.markdown(팀원_줄(상태.학생들[팀원]))
            if not 팀["팀원"]:
                st.caption("아직 팀원이 없습니다.")
            st.button(
                f"{팀['이름']}에 지원",
                key=f"apply_{팀['번호']}",
                disabled=지원막힘,
                on_click=지원_누름,
                args=(풀, 학번, 팀["번호"]),
            )

    st.subheader("내 지원 기록")
    지원기록_표(서비스.지원기록_읽기(풀, 학번), 지원자_보임=False)

    if 내팀 is None:
        return
    st.subheader("우리 팀에 들어온 지원")
    팀원들 = set(상태.팀(내팀)["팀원"])
    들어온지원 = [지원 for 지원 in 상태.대기지원들 if 지원.팀번호 == 내팀]
    if not 들어온지원:
        st.caption("대기 중인 지원이 없습니다.")
    for 지원 in 들어온지원:
        지원자 = 상태.학생들[지원.지원자]
        with st.container(border=True):
            st.markdown(f"**{지원자.표시()}**")
            st.caption(f"찬성 {len(지원.찬성 & 팀원들)}명 / 팀원 {len(팀원들)}명")
            if 학번 in 지원.찬성:
                st.markdown("내 투표: 찬성")
            elif 학번 in 지원.거부:
                st.markdown("내 투표: 거부")
            else:
                왼쪽, 오른쪽 = st.columns(2)
                왼쪽.button("찬성", key=f"vote_yes_{지원.지원자}", disabled=상태.마감,
                           on_click=투표_누름, args=(풀, 학번, 지원.지원자, True))
                오른쪽.button("거부", key=f"vote_no_{지원.지원자}", disabled=상태.마감,
                            on_click=투표_누름, args=(풀, 학번, 지원.지원자, False))


# ---------------------------------------------------------------- 관리자 화면


def 명단_누름(풀):
    파일 = st.session_state.get("admin_roster_file")
    if 파일 is None:
        결과_정하기("막힘: 명단 CSV 파일을 골라 주세요")
        return
    결과_정하기(서비스.명단_올리기(풀, 파일.getvalue(), int(st.session_state["admin_team_count"])))
    작업 = AI배정작업_가져오기()
    if not 작업.진행중:
        작업.안내 = ""


def 마감_누름(풀):
    결과_정하기(서비스.모집_마감(풀))


def 확정_누름(풀):
    결과_정하기(서비스.배정_확정(풀))


@st.fragment(run_every=다시그리기초)
def 관리자_현황(풀):
    상태 = 서비스.상태_읽기(풀)
    st.subheader("지금 팀 구성")
    for 팀, 칸 in zip(상태.팀들, 팀칸들(len(상태.팀들))):
        with 칸, st.container(key=f"team_{팀['번호']}", border=True):
            st.markdown(f"**{팀['이름']}** · {len(팀['팀원'])}/4명")
            for 팀원 in 팀["팀원"]:
                st.markdown(팀원_줄(상태.학생들[팀원]))
            for 지원 in 상태.대기지원들:
                if 지원.팀번호 == 팀["번호"]:
                    st.caption(f"대기 중인 지원: {상태.학생들[지원.지원자].이름} (찬성 {len(지원.찬성)}명)")
    st.markdown("**팀이 없는 학생**")
    with st.container(key="unassigned", border=True):
        미배정 = 상태.미배정()
        for 사람 in 미배정:
            st.markdown(팀원_줄(사람))
        if not 미배정:
            st.caption("팀이 없는 학생이 없습니다.")
    st.caption(f"화면은 {다시그리기초}초마다 저절로 바뀝니다.")
    st.markdown("**지원 기록**")
    지원기록_표(서비스.지원기록_읽기(풀), 지원자_보임=True)


def 배정안_보이기(상태):
    배정안 = 상태.배정안
    if 배정안 is None:
        return
    st.markdown(f"**배정안** (만든 곳: {배정안['출처']})")
    새로온 = {}
    for 학번, 팀번호 in 배정안["배정"].items():
        새로온.setdefault(int(팀번호), []).append(학번)
    for 팀 in 상태.팀들:
        줄들 = [팀원_줄(상태.학생들[학번]) for 학번 in 팀["팀원"]]
        줄들 += [f"{팀원_줄(상태.학생들[학번])} ← 새로 배정" for 학번 in 새로온.get(팀["번호"], [])]
        st.markdown(f"*{팀['이름']}* ({len(줄들)}명)\n" + "\n".join(줄들))


def 관리자_화면(풀):
    결과칸 = st.container()
    상태 = 서비스.상태_읽기(풀)
    단계 = "확정됨" if 상태.확정 else "마감됨" if 상태.마감 else "모집 중"
    st.markdown(f"지금 단계: **{단계}** · 학생 {len(상태.학생들)}명 · 팀 {len(상태.팀들)}개")

    st.subheader("1. 명단 올리기")
    st.file_uploader("명단 CSV (UTF-8)", type=["csv"], key="admin_roster_file")
    st.number_input("팀 수", min_value=1, max_value=20, value=3, step=1, key="admin_team_count")
    st.button("명단으로 처음 상태 만들기", key="admin_start", on_click=명단_누름, args=(풀,))
    st.caption("누르면 지원, 투표, 팀원, 마감 표시를 모두 지우고 명단의 학생과 빈 팀을 만듭니다.")

    st.subheader("2. 모집 마감")
    st.button("모집 마감", key="admin_close", on_click=마감_누름, args=(풀,))

    st.subheader("3. AI 배정과 확정")
    st.checkbox("AI를 부름 (끄면 AI 없이 앱이 바로 배정함. 연습할 때 AI 호출 횟수를 아낄 수 있음)", value=True, key="admin_use_ai")
    작업 = AI배정작업_가져오기()
    배정누름 = st.button("AI 배정", key="admin_assign", disabled=작업.진행중)
    with st.container(key="assign_status"):
        if 배정누름:
            모델들 = [설정값(f"AI_MODEL_{순서}", 기본) for 순서, 기본 in enumerate(인공지능.기본모델들, start=1)]
            st.session_state["기다리는작업"] = 작업.시작(
                풀, 설정값("OPENROUTER_API_KEY"), 모델들, st.session_state["admin_use_ai"]
            )
        elif 작업.진행중:
            # 연결이 끊겼다 다시 붙었거나 새로 열린 화면도 진행 중인 배정을 이어서 기다립니다.
            st.session_state["기다리는작업"] = 작업.번호
        if "기다리는작업" in st.session_state:
            진행칸 = st.empty()
            while 작업.진행중:
                진행칸.info(작업.진행안내)
                time.sleep(1)
            진행칸.empty()
            if st.session_state.pop("기다리는작업") == 작업.번호:
                결과_정하기(작업.결과)
            상태 = 서비스.상태_읽기(풀)
        if 작업.안내:
            st.info(작업.안내)
    배정안_보이기(상태)
    st.button("배정안 확정", key="admin_confirm", type="primary", on_click=확정_누름, args=(풀,))

    with 결과칸:
        결과_보이기()

    관리자_현황(풀)

    with st.expander("AI 호출 기록 (최근 30건, 한국 시각)"):
        for 기록 in 서비스.AI기록_읽기(풀):
            시각 = 기록["created_at"].astimezone(한국시간).strftime("%m-%d %H:%M:%S")
            st.markdown(
                f"`{시각}` {기록['model_order']}차 `{기록['model']}` → **{기록['outcome']}** "
                f"({기록['elapsed_sec']:.0f}초) {기록['detail'][:300]}"
            )


# ---------------------------------------------------------------- 시작


def 시작():
    주소 = 설정값("DATABASE_URL")
    if not 주소:
        st.error("DATABASE_URL이 설정되지 않았습니다. .env 또는 Streamlit Secrets를 확인해 주세요.")
        st.stop()
    관리자비밀번호 = 설정값("ADMIN_PASSWORD")
    try:
        풀 = 풀_가져오기(주소, 지문(주소))
        if 관리자비밀번호:
            관리자_준비됨(풀, 관리자비밀번호, 지문(관리자비밀번호))
    except Exception as 오류:
        # 오류 문장에 DB 주소가 들어갈 수 있으므로 오류 종류만 보여 줍니다.
        st.error(f"DB에 연결하지 못했습니다({type(오류).__name__}). DATABASE_URL과 Supabase 프로젝트 상태를 확인해 주세요.")
        st.stop()
    if not 관리자비밀번호:
        st.warning("ADMIN_PASSWORD가 설정되지 않아 관리자 계정이 없습니다.")

    if "사용자" not in st.session_state:
        로그인_화면(풀)
        return
    사용자 = 서비스.사용자_찾기(풀, st.session_state["사용자"])
    if 사용자 is None:
        로그아웃()
        st.rerun()

    st.title("팀 편성")
    with st.container(key="whoami"):
        구분 = "관리자" if 사용자["관리자"] else "학생"
        st.markdown(f"로그인: **{사용자['이름']}** ({사용자['학번']}, {구분})")
    st.button("로그아웃", key="logout", on_click=로그아웃)

    if 사용자["관리자"]:
        관리자_화면(풀)
    else:
        학생_본문(풀, 사용자["학번"])


시작()
