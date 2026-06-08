#!/usr/bin/env node
// Railway에서 런타임 설정을 동적으로 생성하는 스크립트

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Railway 환경 변수에서 URL 가져오기
const getAPIBaseURL = () => {
  if (process.env.VITE_API_BASE_URL) {
    return process.env.VITE_API_BASE_URL;
  }
  
  if (process.env.API_BASE_URL) {
    return process.env.API_BASE_URL;
  }
  
  // Railway 환경에서 같은 서비스라면
  if (process.env.RAILWAY_PUBLIC_DOMAIN) {
    return `https://${process.env.RAILWAY_PUBLIC_DOMAIN}`;
  }
  
  return '';
};

const getWSBaseURL = () => {
  if (process.env.VITE_WS_BASE_URL) {
    return process.env.VITE_WS_BASE_URL;
  }
  
  if (process.env.WS_BASE_URL) {
    return process.env.WS_BASE_URL;
  }
  
  // Railway 환경에서 WebSocket URL 생성
  if (process.env.RAILWAY_PUBLIC_DOMAIN) {
    return `wss://${process.env.RAILWAY_PUBLIC_DOMAIN}`;
  }
  
  return '';
};

// Feature Flag 로드 함수
const loadFeatureFlags = () => {
  const parseBool = (val) => {
    if (val === undefined || val === null) return undefined;
    return val.toLowerCase() === 'true';
  };

  return {
    chatbot: {
      enabled: parseBool(process.env.VITE_FEATURE_CHATBOT) ?? true,
      streaming: parseBool(process.env.VITE_FEATURE_CHATBOT_STREAMING) ?? true,
      history: parseBool(process.env.VITE_FEATURE_CHATBOT_HISTORY) ?? true,
      sessionManagement: parseBool(process.env.VITE_FEATURE_CHATBOT_SESSION) ?? true,
      markdown: parseBool(process.env.VITE_FEATURE_CHATBOT_MARKDOWN) ?? true,
    },
    documentManagement: {
      enabled: parseBool(process.env.VITE_FEATURE_DOCUMENTS) ?? false,
      upload: parseBool(process.env.VITE_FEATURE_DOCUMENTS_UPLOAD) ?? false,
      bulkDelete: parseBool(process.env.VITE_FEATURE_DOCUMENTS_BULK_DELETE) ?? false,
      search: parseBool(process.env.VITE_FEATURE_DOCUMENTS_SEARCH) ?? false,
      pagination: parseBool(process.env.VITE_FEATURE_DOCUMENTS_PAGINATION) ?? false,
      dragAndDrop: parseBool(process.env.VITE_FEATURE_DOCUMENTS_DND) ?? false,
      preview: parseBool(process.env.VITE_FEATURE_DOCUMENTS_PREVIEW) ?? false,
    },
    admin: {
      enabled: parseBool(process.env.VITE_FEATURE_ADMIN) ?? false,
      userManagement: parseBool(process.env.VITE_FEATURE_ADMIN_USERS) ?? false,
      systemStats: parseBool(process.env.VITE_FEATURE_ADMIN_STATS) ?? false,
      qdrantManagement: parseBool(process.env.VITE_FEATURE_ADMIN_QDRANT) ?? false,
      accessControl: parseBool(process.env.VITE_FEATURE_ADMIN_ACCESS) ?? false,
    },
    prompts: {
      enabled: parseBool(process.env.VITE_FEATURE_PROMPTS) ?? false,
      templates: parseBool(process.env.VITE_FEATURE_PROMPTS_TEMPLATES) ?? false,
      history: parseBool(process.env.VITE_FEATURE_PROMPTS_HISTORY) ?? false,
    },
    analysis: {
      enabled: parseBool(process.env.VITE_FEATURE_ANALYSIS) ?? false,
      realtime: parseBool(process.env.VITE_FEATURE_ANALYSIS_REALTIME) ?? false,
      export: parseBool(process.env.VITE_FEATURE_ANALYSIS_EXPORT) ?? false,
      visualization: parseBool(process.env.VITE_FEATURE_ANALYSIS_VIZ) ?? false,
    },
  };
};

const config = {
  API_BASE_URL: getAPIBaseURL(),
  WS_BASE_URL: getWSBaseURL(),
  NODE_ENV: process.env.NODE_ENV || 'production',
  TIMESTAMP: new Date().toISOString(),
  RAILWAY_ENVIRONMENT: process.env.RAILWAY_ENVIRONMENT || null,
  // Railway 환경변수에서 접근코드 가져오기
  ACCESS_CODE: process.env.VITE_ACCESS_CODE || process.env.ACCESS_CODE || '1127',
  // Feature Flag 설정 추가
  FEATURES: loadFeatureFlags(),
};

const redactedConfig = {
  ...config,
  ACCESS_CODE: config.ACCESS_CODE ? '***masked***' : null,
};

// config.js 파일 생성
const configContent = `// Railway 런타임 설정 (자동 생성됨)
window.RUNTIME_CONFIG = ${JSON.stringify(config, null, 2)};

console.log('Railway Runtime Config Loaded');`;

// public/config.js에 쓰기
const outputPath = path.join(__dirname, 'dist', 'config.js');
fs.writeFileSync(outputPath, configContent, 'utf8');

console.log('✅ Runtime config generated:', outputPath);
console.log('📋 Config:', redactedConfig);
