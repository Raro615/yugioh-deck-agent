/*
 * 브라우저 준비 상태를 **돌리기 전에** 확인한다 (Phase 6-AY).
 *
 * 🔴 이 컨테이너에 깔려 있다는 이유로 사용자 PC 에도 있다고 가정하지
 *    않는다. 없으면 **무엇을 어떻게 깔아야 하는지** 한 줄로 적는다.
 *
 * 결과: JSON 한 줄을 stdout 에 쓴다 (종료 코드 0 = 준비됨).
 */
'use strict';
const out = { node: process.version, playwright: null, chromium: null,
              ready: false, problems: [], hints: [] };
try {
  out.playwright = require('playwright/package.json').version;
} catch (_) {
  out.problems.push('playwright 모듈이 없습니다');
  out.hints.push('npm install');
}
if (out.playwright) {
  try {
    const { chromium } = require('playwright');
    const fs = require('fs');
    const exe = chromium.executablePath();
    out.chromium = exe;
    if (!exe || !fs.existsSync(exe)) {
      out.problems.push('크로뮴 실행 파일이 없습니다: ' + exe);
      out.hints.push('npx playwright install chromium');
    }
  } catch (error) {
    out.problems.push('크로뮴 경로를 읽지 못했습니다: ' + error.message);
    out.hints.push('npx playwright install chromium');
  }
}
out.ready = out.problems.length === 0;
console.log(JSON.stringify(out));
process.exit(out.ready ? 0 : 1);
