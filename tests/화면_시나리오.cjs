// 작성: 2026-10-29 21:53
// 로컬에서 띄운 앱을 채점 프로그램처럼 브라우저로 조작해 연습용 시나리오를 끝까지 해 봅니다.
// 화면 요소는 공고 2.7절의 key(.st-key-<key>)로만 찾습니다.
// 실행: NODE_PATH="$(npm root -g)" node tests/화면_시나리오.cjs <주소> <관리자 비밀번호> <시나리오 이름...>
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const [주소, 관리자비번, ...고른시나리오] = process.argv.slice(2);
const 명단폴더 = path.join(__dirname, '연습명단');

// 공고 부록의 단계. [동작, 누가, 대상, 기대 첫 단어]
const 시나리오들 = {
  쉬움: {
    파일: '쉬움.csv', 팀수: 3,
    단계: [
      ['지원', '학생1', 1, '승인'], ['지원', '학생2', 2, '승인'], ['지원', '학생3', 3, '승인'],
      ['지원', '학생4', 1, '대기'], ['찬성', '학생1', '학생4', '승인'],
      ['지원', '학생5', 2, '대기'], ['찬성', '학생2', '학생5', '승인'],
      ['지원', '학생7', 1, '대기'], ['찬성', '학생1', '학생7', '대기'], ['거부', '학생4', '학생7', '거절'],
      ['지원', '학생6', 3, '대기'], ['찬성', '학생3', '학생6', '승인'],
      ['마감'], ['배정'],
    ],
  },
  중간: {
    파일: '중간.csv', 팀수: 4,
    단계: [
      ['지원', '학생1', 1, '승인'],
      ['지원', '학생5', 1, '대기'], ['찬성', '학생1', '학생5', '승인'],
      ['지원', '학생2', 1, '막힘'],
      ['지원', '학생6', 2, '승인'],
      ['지원', '학생9', 2, '대기'], ['찬성', '학생6', '학생9', '승인'],
      ['지원', '학생10', 2, '대기'], ['찬성', '학생6', '학생10', '대기'], ['거부', '학생9', '학생10', '거절'],
      ['지원', '학생3', 3, '승인'], ['지원', '학생11', 4, '승인'],
      ['지원', '학생12', 4, '대기'], ['지원', '학생12', 3, '막힘'],
      ['마감'], ['미배정 확인', ['학생3', '학생11', '학생12']],
      ['지원', '학생2', 3, '막힘'],
      ['배정'],
    ],
  },
  어려움: {
    파일: '어려움.csv', 팀수: 4,
    단계: [
      ['지원', '학생1', 1, '승인'],
      ['지원', '학생4', 1, '대기'], ['찬성', '학생1', '학생4', '승인'],
      ['지원', '학생7', 1, '대기'], ['찬성', '학생1', '학생7', '대기'], ['찬성', '학생4', '학생7', '승인'],
      ['지원', '학생2', 2, '승인'],
      ['지원', '학생8', 2, '대기'], ['찬성', '학생2', '학생8', '승인'],
      ['지원', '학생5', 2, '대기'], ['지원', '학생6', 2, '대기'],
      ['찬성', '학생2', '학생5', '대기'], ['찬성', '학생8', '학생5', '승인'],
      ['찬성', '학생2', '학생6', '대기'], ['찬성', '학생8', '학생6', '대기'], ['찬성', '학생5', '학생6', '거절'],
      ['지원', '학생11', 3, '승인'],
      ['지원', '학생15', 3, '대기'], ['찬성', '학생11', '학생15', '승인'],
      ['지원', '학생14', 3, '막힘'],
      ['지원', '학생10', 4, '승인'],
      ['지원', '학생13', 1, '대기'], ['찬성', '학생1', '학생13', '대기'],
      ['마감'], ['미배정 확인', ['학생10', '학생13']],
      ['배정'],
    ],
  },
};

function 명단(파일) {
  const 줄들 = fs.readFileSync(path.join(명단폴더, 파일), 'utf-8').replace(/^﻿/, '').trim().split('\n').slice(1);
  const 학번 = {};
  for (const 줄 of 줄들) {
    const [번호, 이름] = 줄.split(',');
    학번[이름.split('(')[0]] = 번호;
  }
  return 학번;
}

async function 멈출때까지(페이지) {
  await 페이지.waitForTimeout(700);
  await 페이지.waitForFunction(() => !document.querySelector('[data-testid="stStatusWidget"]'), null, { timeout: 600000 });
  await 페이지.waitForTimeout(300);
}

async function 결과읽기(페이지) {
  return (await 페이지.locator('.st-key-result').innerText()).trim();
}

async function 로그인(브라우저, 학번, 비번) {
  const 페이지 = await (await 브라우저.newContext()).newPage();
  await 페이지.goto(주소);
  await 페이지.locator('.st-key-login_student_no input').fill(학번);
  await 페이지.locator('.st-key-login_password input').fill(비번);
  await 페이지.locator('.st-key-login_submit button').click();
  await 페이지.locator('.st-key-whoami').waitFor({ timeout: 15000 });
  return 페이지;
}

// 단추가 7초 안에 나타나지 않거나 비활성이면 채점 프로그램처럼 "막힘"으로 봅니다.
async function 단추누르기(페이지, key) {
  const 단추 = 페이지.locator(`.st-key-${key} button`);
  try {
    await 단추.waitFor({ timeout: 7000 });
  } catch {
    return '막힘(단추 없음)';
  }
  if (await 단추.isDisabled()) return '막힘(단추 비활성)';
  await 단추.click();
  await 멈출때까지(페이지);
  return 결과읽기(페이지);
}

async function 실행(브라우저, 이름) {
  const 시나리오 = 시나리오들[이름];
  const 학번 = 명단(시나리오.파일);
  const 관리자 = await 로그인(브라우저, 'admin', 관리자비번);
  await 관리자.locator('.st-key-admin_roster_file input[type=file]').setInputFiles(path.join(명단폴더, 시나리오.파일));
  await 관리자.locator('.st-key-admin_roster_file').getByText(시나리오.파일).waitFor({ timeout: 15000 });
  const 팀수칸 = 관리자.locator('.st-key-admin_team_count input');
  await 팀수칸.fill(String(시나리오.팀수));
  await 팀수칸.press('Enter');
  await 멈출때까지(관리자);
  let 결과 = await 단추누르기(관리자, 'admin_start');
  if (!결과.startsWith('승인')) throw new Error(`명단 올리기 실패: ${결과}`);

  const 학생페이지 = {};
  const 학생 = async (누구) => (학생페이지[누구] ??= await 로그인(브라우저, 학번[누구], '1234'));
  let 틀림 = 0;
  for (const [동작, ...인자] of 시나리오.단계) {
    let 설명, 기대;
    if (동작 === '지원') {
      const [누구, 팀, 기대값] = 인자;
      설명 = `${누구} → 팀${팀} 지원`; 기대 = 기대값;
      결과 = await 단추누르기(await 학생(누구), `apply_${팀}`);
    } else if (동작 === '찬성' || 동작 === '거부') {
      const [누구, 지원자, 기대값] = 인자;
      설명 = `${누구}가 ${지원자}에 ${동작}`; 기대 = 기대값;
      const key = `${동작 === '찬성' ? 'vote_yes' : 'vote_no'}_${학번[지원자]}`;
      결과 = await 단추누르기(await 학생(누구), key);
    } else if (동작 === '마감') {
      설명 = '관리자 마감'; 기대 = '승인';
      결과 = await 단추누르기(관리자, 'admin_close');
    } else if (동작 === '미배정 확인') {
      설명 = `팀이 없는 학생에 ${인자[0].join(', ')}`; 기대 = '있음';
      await 관리자.waitForTimeout(3500);
      const 글 = await 관리자.locator('.st-key-unassigned').innerText();
      결과 = 인자[0].every((누구) => 글.includes(`${누구}(`)) ? '있음' : `없음: ${글}`;
    } else if (동작 === '배정') {
      설명 = '관리자 AI 배정'; 기대 = '승인';
      결과 = await 단추누르기(관리자, 'admin_assign');
      const 안내 = await 관리자.locator('.st-key-assign_status').innerText();
      console.log(`   배정 안내: ${안내.trim().slice(0, 300)}`);
      if (결과.startsWith('승인')) {
        console.log(`  ✔ ${설명}: ${결과}`);
        설명 = '관리자 확정';
        결과 = await 단추누르기(관리자, 'admin_confirm');
      }
    }
    const 맞음 = 결과.startsWith(기대);
    if (!맞음) 틀림 += 1;
    console.log(`  ${맞음 ? '✔' : '✘'} ${설명}: ${결과}${맞음 ? '' : ` (기대: ${기대})`}`);
  }

  // 새 브라우저로 열어 확정한 팀 구성이 남아 있는지 봅니다.
  const 확인 = await 로그인(브라우저, 'admin', 관리자비번);
  const 미배정 = (await 확인.locator('.st-key-unassigned').innerText()).trim();
  const 팀글 = [];
  for (let 번호 = 1; 번호 <= 시나리오.팀수; 번호 += 1) {
    팀글.push((await 확인.locator(`.st-key-team_${번호}`).innerText()).replace(/\n/g, ' | '));
  }
  console.log(`  확정 뒤 팀이 없는 학생: ${미배정}`);
  팀글.forEach((글) => console.log(`  ${글}`));
  for (const 페이지 of [관리자, 확인, ...Object.values(학생페이지)]) await 페이지.context().close();
  return 틀림;
}

(async () => {
  const 브라우저 = await chromium.launch();
  let 전체틀림 = 0;
  for (const 이름 of 고른시나리오.length ? 고른시나리오 : Object.keys(시나리오들)) {
    console.log(`[${이름}]`);
    전체틀림 += await 실행(브라우저, 이름);
  }
  await 브라우저.close();
  console.log(전체틀림 === 0 ? '모든 단계가 기대 결과와 같음' : `기대 결과와 다른 단계 ${전체틀림}개`);
  process.exit(전체틀림 === 0 ? 0 : 1);
})();
