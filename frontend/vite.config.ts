import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// dev 서버의 iframe 임베드 정책을 프로덕션(nginx)과 일관되게 env로 제어한다.
// - IFRAME_FRAME_ANCESTORS: CSP frame-ancestors 값(기본 'self' → same-origin만 임베드 허용).
//   외부 사이트 임베드 테스트가 필요하면 해당 origin을 지정한다(예: "'self' https://example.com").
// - X_FRAME_OPTIONS: 레거시 호환용. 설정된 경우에만 X-Frame-Options 헤더를 추가한다
//   (frame-ancestors와 충돌하므로 기본 미설정).
const frameAncestors = process.env.IFRAME_FRAME_ANCESTORS || "'self'"
const xFrameOptions = process.env.X_FRAME_OPTIONS

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5000,
    headers: {
      'Content-Security-Policy': [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self' http://localhost:8000 ws://localhost:8000 https://*.railway.app wss://*.railway.app",
        `frame-ancestors ${frameAncestors}`,
        "base-uri 'self'",
        "form-action 'self'",
      ].join('; '),
      'X-Content-Type-Options': 'nosniff',
      // X-Frame-Options는 frame-ancestors와 충돌하므로, 명시적으로 지정한 경우에만 추가한다.
      ...(xFrameOptions ? { 'X-Frame-Options': xFrameOptions } : {}),
      'X-XSS-Protection': '1; mode=block',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE_URL || 'http://localhost:8000',
        changeOrigin: true,
        secure: true,
      },
      '/api/admin/ws': {
        target: process.env.VITE_WS_BASE_URL || 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        secure: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: false,
        drop_debugger: true,
      },
    },
    cssCodeSplit: true,
  },
})
