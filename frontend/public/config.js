/**
 * 런타임 설정 파일
 * 
 * 이 파일은 빌드 후에도 수정 가능한 런타임 설정을 제공합니다.
 * Railway 배포 시 환경변수 대신 이 파일을 직접 수정하여 API URL을 설정할 수 있습니다.
 * 
 * 우선순위:
 * 1. VITE_API_BASE_URL 환경변수 (빌드 시점)
 * 2. 이 파일의 API_BASE_URL (런타임)
 * 3. localhost:8000 (개발 폴백)
 */
window.RUNTIME_CONFIG = {
  // Railway 백엔드 서비스 URL을 여기에 설정하세요
  // 예: 'https://simple-rag-backend-production.up.railway.app'
  API_BASE_URL: 'https://simple-rag-back-junggu-production-23c1.up.railway.app',
  
  // 환경 설정 (production, development, staging)
  NODE_ENV: 'production',

  // 관리자 접근 코드 (런타임 설정). 빈 문자열이면 기본 접근 코드로 폴백한다.
  // 배포 시 generate-config.js가 ACCESS_CODE 환경변수로 이 값을 덮어쓴다.
  ACCESS_CODE: '',

  // 임베드(embed) 허용 부모 origin 화이트리스트.
  // 외부 사이트에 /embed/chat을 iframe(onerag-embed.js)으로 임베드할 때
  // postMessage 통신을 허용할 origin 목록이다.
  // 예: ['https://docs.example.com', 'https://app.example.com']
  // 빈 배열이면 현재 origin(same-origin)만 허용한다. 와일드카드('*')는 지원하지 않는다.
  EMBED_ALLOWED_ORIGINS: [],

  // 추가 런타임 설정이 필요한 경우 여기에 추가
};