# 작성: 2026-10-29 21:52
"""오픈라우터 AI 호출. 모델마다 전체 대기 시간을 재서 제한초가 넘으면 끊고 다음 모델로 넘어갑니다."""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as 기다림초과
from dataclasses import dataclass

import requests

from 규칙 import 최대인원

오픈라우터주소 = "https://openrouter.ai/api/v1/chat/completions"
모델제한초 = 120
기본모델들 = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "z-ai/glm-4.5-air:free",
)


@dataclass
class 호출결과:
    성공: bool
    종류: str  # 응답, 시간 초과, HTTP 오류, 빈 응답, 연결 오류, 키 없음
    내용: str
    걸린초: float


def 배정_질문_만들기(팀별팀원, 팀이름들, 미배정):
    팀정보 = [
        {
            "team_no": 팀번호,
            "team_name": 팀이름들[팀번호],
            "free_seats": 최대인원 - len(팀원들),
            "members": [{"name": 사람.이름, "main_role": 사람.주역할, "sub_roles": list(사람.보조역할)} for 사람 in 팀원들],
        }
        for 팀번호, 팀원들 in sorted(팀별팀원.items())
    ]
    학생정보 = [
        {"student_no": 사람.학번, "name": 사람.이름, "main_role": 사람.주역할, "sub_roles": list(사람.보조역할)}
        for 사람 in 미배정
    ]
    return f"""팀 프로젝트의 팀 편성을 도와줘. 팀이 없는 학생을 지금 팀에 넣는 배정안을 만들어야 해.

규칙:
1. 팀이 없는 학생은 빠짐없이 정확히 한 팀에만 넣는다. 이미 팀에 있는 학생은 옮기지 않는다.
2. 배정한 뒤 모든 팀은 2~4명이어야 한다. 빈 팀(0명)이나 1명인 팀이 남으면 안 된다.
3. 한 팀 안에 주 역할(main_role)이 같은 학생이 2명 이상이면 안 된다.
4. 모든 팀에는 '기획자'를 맡을 학생과 '웹 프로그래머'를 맡을 학생이 서로 다른 사람으로 1명씩 있어야 한다.
   주 역할이나 보조 역할(sub_roles)로 맡을 수 있다. 한 학생이 두 역할을 동시에 맡을 수는 없다.

지금 팀:
{json.dumps(팀정보, ensure_ascii=False, indent=1)}

팀이 없는 학생:
{json.dumps(학생정보, ensure_ascii=False, indent=1)}

규칙을 모두 지키는지 스스로 확인한 뒤, 설명 없이 아래 형식의 JSON 하나만 출력해:
{{"assignments": [{{"student_no": "학번", "team_no": 팀번호}}, ...]}}"""


def 배정_해석(글):
    """AI 응답에서 배정안을 꺼냅니다. (배정, 문제들)을 돌려주며, 꺼내지 못하면 배정은 None입니다."""
    시작, 끝 = 글.find("{"), 글.rfind("}")
    if 시작 < 0 or 끝 <= 시작:
        return None, ["응답에 JSON이 없음"]
    try:
        자료 = json.loads(글[시작 : 끝 + 1])
        항목들 = 자료["assignments"]
        배정 = {}
        for 항목 in 항목들:
            학번 = str(항목["student_no"]).strip()
            팀번호 = int(re.sub(r"\D", "", str(항목["team_no"])))
            if 학번 in 배정:
                return None, [f"한 학생({학번})이 여러 팀에 배정됨"]
            배정[학번] = 팀번호
    except (ValueError, KeyError, TypeError) as 오류:
        return None, [f"JSON 형식이 틀림({type(오류).__name__})"]
    return 배정, []


def 모델_부르기(키, 모델, 질문, 제한초=모델제한초, 진행알림=lambda 초: None, 주소=오픈라우터주소):
    """모델 하나를 부릅니다. 응답이 시작됐는지와 상관없이 제한초가 지나면 끊습니다."""
    시작 = time.monotonic()
    if not 키:
        return 호출결과(False, "키 없음", "OPENROUTER_API_KEY가 설정되지 않음", 0.0)
    중단 = threading.Event()
    실행기 = ThreadPoolExecutor(max_workers=1)
    미래 = 실행기.submit(_스트리밍_받기, 키, 모델, 질문, 제한초, 중단, 주소)
    try:
        while True:
            남은초 = 제한초 - (time.monotonic() - 시작)
            if 남은초 <= 0:
                중단.set()
                return 호출결과(False, "시간 초과", f"{제한초}초 안에 응답을 다 받지 못함", time.monotonic() - 시작)
            try:
                종류, 내용 = 미래.result(timeout=min(1.0, 남은초))
                break
            except 기다림초과:
                진행알림(int(time.monotonic() - 시작))
    finally:
        실행기.shutdown(wait=False)
    걸린초 = time.monotonic() - 시작
    if 종류 == "응답" and not 내용.strip():
        return 호출결과(False, "빈 응답", "응답 내용이 비어 있음", 걸린초)
    return 호출결과(종류 == "응답", 종류, 내용, 걸린초)


def _스트리밍_받기(키, 모델, 질문, 제한초, 중단, 주소):
    본문 = {
        "model": 모델,
        "messages": [{"role": "user", "content": 질문}],
        "max_tokens": 8000,
        "reasoning": {"effort": "low"},
        "stream": True,
    }
    머리 = {"Authorization": f"Bearer {키}", "Content-Type": "application/json"}
    try:
        with requests.post(주소, headers=머리, json=본문, stream=True, timeout=(10, 제한초)) as 응답:
            if 응답.status_code != 200:
                return "HTTP 오류", f"HTTP {응답.status_code}: {응답.text[:200]}"
            조각들 = []
            # 줄을 바이트로 받아 직접 UTF-8로 풉니다(requests가 한글을 다른 인코딩으로 풀 수 있음).
            for 줄 in 응답.iter_lines():
                if 중단.is_set():
                    return "시간 초과", "중단됨"
                줄 = 줄.decode("utf-8", errors="replace")
                if not 줄.startswith("data:"):
                    continue
                자료 = 줄[5:].strip()
                if 자료 == "[DONE]":
                    break
                조각 = json.loads(자료)
                if "error" in 조각:
                    return "HTTP 오류", f"응답 중 오류: {str(조각['error'])[:200]}"
                선택 = 조각.get("choices") or [{}]
                조각들.append((선택[0].get("delta") or {}).get("content") or "")
            return "응답", "".join(조각들)
    except json.JSONDecodeError:
        return "HTTP 오류", "응답 형식이 틀림"
    except Exception as 오류:
        # 연결 실패, 키에 영문이 아닌 글자가 들어간 경우 등. 앱이 멈추지 않고 다음 모델로 넘어가게 합니다.
        return "연결 오류", type(오류).__name__
