# Railway 최적화된 프론트엔드 Dockerfile
# Multi-stage build for production optimization

# Stage 1: Dependencies 설치
FROM node:20-alpine AS deps
WORKDIR /app

# package.json과 package-lock.json만 먼저 복사 (의존성 캐싱 최적화)
COPY package*.json ./

# 프로덕션 의존성만 설치 (개발 의존성 제외)
RUN npm ci --only=production --frozen-lockfile

# Stage 2: Build stage
FROM node:20-alpine AS builder
WORKDIR /app

# 전체 의존성 설치 (devDependencies 포함)
COPY package*.json ./
RUN npm ci --frozen-lockfile

# 소스 코드 복사
COPY . .

# TypeScript 및 ESLint 검사 (빌드 시 오류 조기 발견)
RUN npm run lint

# 런타임 config.js는 entrypoint에서 생성하므로 빌드 시 배포 URL을 강제하지 않는다.
RUN npm run build:warning-gate

# Stage 3: Production runtime
FROM nginx:alpine AS production

# 불필요한 nginx 기본 파일 제거
RUN rm -rf /usr/share/nginx/html/*

# 빌드된 파일을 nginx html 디렉토리에 복사
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx 설정 파일 복사
COPY nginx.conf /etc/nginx/conf.d/default.conf.template

# entrypoint 스크립트 복사 (런타임 config.js 생성용)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Railway에서 동적으로 할당하는 포트 사용
ENV PORT=80
EXPOSE 80

# entrypoint.sh 실행 (config.js 생성 후 nginx 시작)
ENTRYPOINT ["/entrypoint.sh"]
