# 작성: 2026-10-29 21:52
"""AI 호출 시험. 진짜 오픈라우터 대신 로컬 가짜 서버를 띄워 시간 초과, 오류, 빈 응답, 검사 실패를 흉내 냅니다."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import 서비스
import 인공지능
from conftest import 명단폴더


class 가짜오픈라우터(BaseHTTPRequestHandler):
    배정글 = ""  # 성공 모델이 돌려줄 내용

    def log_message(self, *인자):
        pass

    def do_POST(self):
        본문 = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        모델 = 본문["model"]
        if 모델 == "느림":
            # 응답은 바로 시작하지만 천천히 와서 전체 시간이 제한을 넘깁니다.
            self._시작()
            for _ in range(20):
                self._조각("{")
                time.sleep(0.5)
            return
        if 모델 == "429":
            self.send_response(429)
            self.end_headers()
            self.wfile.write(b'{"error":"rate limited"}')
            return
        self._시작()
        if 모델 == "빈응답":
            self._조각("")
        elif 모델 == "틀린배정":
            self._조각('{"assignments": []}')
        else:
            for 글자 in [self.배정글[i : i + 7] for i in range(0, len(self.배정글), 7)]:
                self._조각(글자)
        self.wfile.write(b"data: [DONE]\n\n")

    def _시작(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b": OPENROUTER PROCESSING\n\n")

    def _조각(self, 내용):
        줄 = json.dumps({"choices": [{"delta": {"content": 내용}}]}, ensure_ascii=False)
        self.wfile.write(f"data: {줄}\n\n".encode("utf-8"))
        self.wfile.flush()


@pytest.fixture
def 가짜주소():
    서버 = ThreadingHTTPServer(("127.0.0.1", 0), 가짜오픈라우터)
    threading.Thread(target=서버.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{서버.server_address[1]}/v1/chat/completions"
    서버.shutdown()


def test_전체_시간이_제한을_넘으면_끊는다(가짜주소):
    시작 = time.monotonic()
    결과 = 인공지능.모델_부르기("test-key", "느림", "질문", 제한초=2, 주소=가짜주소)
    assert 결과.종류 == "시간 초과"
    assert time.monotonic() - 시작 < 3.5


def test_한글_응답을_제대로_받는다(가짜주소):
    가짜오픈라우터.배정글 = "안녕하세요 팀 편성"
    결과 = 인공지능.모델_부르기("test-key", "성공", "질문", 제한초=5, 주소=가짜주소)
    assert 결과.성공 and 결과.내용 == "안녕하세요 팀 편성"


def test_배정_해석():
    assert 인공지능.배정_해석('```json\n{"assignments":[{"student_no":"1","team_no":"팀2"}]}\n```') == ({"1": 2}, [])
    assert 인공지능.배정_해석("모르겠어요")[0] is None
    배정, 문제 = 인공지능.배정_해석('{"assignments":[{"student_no":"1","team_no":1},{"student_no":"1","team_no":2}]}')
    assert 배정 is None and "여러 팀" in 문제[0]


def 마감된_쉬움(풀):
    서비스.명단_올리기(풀, (명단폴더 / "쉬움.csv").read_bytes(), 3)
    상태 = 서비스.상태_읽기(풀)
    학번 = {사람.이름.split("(")[0]: 번호 for 번호, 사람 in 상태.학생들.items()}
    for 이름, 팀 in [("학생1", 1), ("학생2", 2), ("학생3", 3)]:
        서비스.지원하기(풀, 학번[이름], 팀)
    for 이름, 팀, 팀원 in [("학생4", 1, "학생1"), ("학생5", 2, "학생2"), ("학생6", 3, "학생3")]:
        서비스.지원하기(풀, 학번[이름], 팀)
        서비스.투표하기(풀, 학번[팀원], 학번[이름], True)
    서비스.모집_마감(풀)
    return 학번


def test_앞_모델이_실패하면_다음_모델로_넘어간다(풀, 가짜주소):
    학번 = 마감된_쉬움(풀)
    가짜오픈라우터.배정글 = json.dumps(
        {"assignments": [{"student_no": 학번["학생7"], "team_no": 1}, {"student_no": 학번["학생8"], "team_no": 2}]}
    )
    안내들 = []
    결과, 안내 = 서비스.AI_배정(풀, "test-key", ["느림", "429", "성공"], 진행표시=안내들.append, 제한초=2, 주소=가짜주소)
    assert 결과 == "승인: 3차 모델의 배정안이 검사를 통과함"
    assert "1차 모델(느림): 시간 초과" in 안내 and "2차 모델(429): HTTP 오류" in 안내
    assert any(문장.startswith("1차 모델(느림)의 응답을 기다리는 중") for 문장 in 안내들)
    assert any(문장.startswith("3차 모델(성공)의 응답을 기다리는 중") for 문장 in 안내들)
    assert 서비스.상태_읽기(풀).배정안["출처"] == "3차 모델(성공)"
    assert 서비스.배정_확정(풀).startswith("승인")
    기록 = [줄["outcome"] for 줄 in 서비스.AI기록_읽기(풀, 3)][::-1]
    assert 기록 == ["시간 초과", "HTTP 오류", "성공"]


def test_3차까지_실패하면_앱이_배정한다(풀, 가짜주소):
    마감된_쉬움(풀)
    결과, 안내 = 서비스.AI_배정(풀, "test-key", ["빈응답", "틀린배정", "429"], 제한초=2, 주소=가짜주소)
    assert 결과.startswith("승인: 3차 모델까지 실패해 앱이 직접")
    assert "빈 응답" in 안내 and "검사 실패" in 안내 and "HTTP 오류" in 안내
    assert 서비스.배정_확정(풀).startswith("승인")
    assert 서비스.상태_읽기(풀).미배정() == []


def test_키에_한글이_있어도_멈추지_않는다(가짜주소):
    결과 = 인공지능.모델_부르기("sk-or-v1-자기 키", "성공", "질문", 제한초=5, 주소=가짜주소)
    assert not 결과.성공 and 결과.종류 == "연결 오류"
