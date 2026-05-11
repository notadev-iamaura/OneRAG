#!/usr/bin/env node
// 빌드 전 환경변수 검증 스크립트

console.log('\n========================================');
console.log('🔍 빌드 환경변수 검증');
console.log('========================================\n');

// 필수 환경변수 목록
const requiredEnvVars = [
  'VITE_API_BASE_URL',
];

const optionalEnvVars = [
  'VITE_ACCESS_CODE',
  'VITE_DEV_API_BASE_URL',
  'VITE_DEV_WS_BASE_URL',
];

let hasErrors = false;

console.log('📋 필수 환경변수:');
requiredEnvVars.forEach((varName) => {
  const value = process.env[varName];
  if (value) {
    console.log(`  ✅ ${varName}: ${value}`);
  } else {
    console.error(`  ❌ ${varName}: NOT SET`);
    hasErrors = true;
  }
});

console.log('\n📋 선택적 환경변수:');
optionalEnvVars.forEach((varName) => {
  const value = process.env[varName];
  if (value) {
    console.log(`  ✅ ${varName}: ${value}`);
  } else {
    console.log(`  ⚠️  ${varName}: NOT SET (선택적)`);
  }
});

console.log('\n========================================');

if (hasErrors) {
  console.error('\n❌ 필수 환경변수가 설정되지 않았습니다!');
  console.error('Railway 대시보드 → Variables 탭에서 설정해주세요.\n');
  process.exit(1);
} else {
  console.log('\n✅ 모든 필수 환경변수가 설정되었습니다!\n');
}
