/**
 * MSW (Mock Service Worker) 핸들러
 * API 엔드포인트 모킹을 위한 요청 핸들러 정의
 */
import { http, HttpResponse } from 'msw';
import type { Document, ChatResponse, HealthResponse } from '../../types';

const BASE_URL = 'http://localhost:8000';

// Mock 데이터
const mockDocuments: Document[] = [
  {
    id: '1',
    filename: 'test-document.pdf',
    size: 1024000,
    status: 'completed',
    uploadedAt: new Date('2025-01-01').toISOString(),
    chunks: 10,
    metadata: { type: 'application/pdf' },
  },
  {
    id: '2',
    filename: 'another-doc.txt',
    size: 512000,
    status: 'processing',
    uploadedAt: new Date('2025-01-02').toISOString(),
    chunks: 5,
    metadata: { type: 'text/plain' },
  },
];

const mockChatResponse: ChatResponse = {
  response: '테스트 응답입니다.',
  sources: [mockDocuments[0]],
  sessionId: 'test-session-123',
};

const mockChatEmptyStateSettings = {
  ko: {
    mainMessage: '무엇을 도와드릴까요?',
    subMessage: 'AI가 참고 문서를 분석하여 정확한 답변을 제공합니다',
    suggestions: [
      '이 문서에서 핵심 내용을 요약해주세요',
      '기본 질문 설정1',
      '기본 질문 설정2',
      '기본 질문 설정3',
    ],
  },
  en: {
    mainMessage: 'How can I help you?',
    subMessage: 'AI analyzes reference documents to provide accurate answers',
    suggestions: [
      'Summarize the key points of this document',
      'Sample question 1',
      'Sample question 2',
      'Sample question 3',
    ],
  },
  ja: {
    mainMessage: '何かお手伝いできますか？',
    subMessage: 'AIが参考文書を分析して正確な回答を提供します',
    suggestions: [
      'この文書の要点を要約してください',
      'サンプル質問1',
      'サンプル質問2',
      'サンプル質問3',
    ],
  },
  es: {
    mainMessage: '¿En qué puedo ayudarte?',
    subMessage: 'La IA analiza los documentos de referencia para ofrecer respuestas precisas',
    suggestions: [
      'Resume los puntos clave de este documento',
      'Pregunta de ejemplo 1',
      'Pregunta de ejemplo 2',
      'Pregunta de ejemplo 3',
    ],
  },
  zhHant: {
    mainMessage: '有什麼可以幫您的嗎？',
    subMessage: 'AI 分析參考文件以提供準確的回答',
    suggestions: [
      '請摘要這份文件的重點',
      '範例問題 1',
      '範例問題 2',
      '範例問題 3',
    ],
  },
};

export const handlers = [
  // Health Check
  http.get(`${BASE_URL}/health`, () => {
    return HttpResponse.json<HealthResponse>({
      status: 'healthy',
      timestamp: new Date().toISOString(),
    });
  }),

  // 문서 목록 조회
  http.get(`${BASE_URL}/api/upload/documents`, () => {
    return HttpResponse.json(mockDocuments);
  }),

  // 문서 업로드
  http.post(`${BASE_URL}/api/upload`, async () => {
    const newDocument: Document = {
      id: '3',
      filename: 'uploaded-file.pdf',
      size: 2048000,
      status: 'processing',
      uploadedAt: new Date().toISOString(),
      chunks: 0,
      metadata: { type: 'application/pdf' },
    };
    return HttpResponse.json(newDocument, { status: 201 });
  }),

  // 문서 삭제
  http.delete(`${BASE_URL}/api/upload/documents/:id`, ({ params }) => {
    const { id } = params;
    return HttpResponse.json({ success: true, id });
  }),

  // 전체 문서 삭제
  http.delete(`${BASE_URL}/api/documents/all`, () => {
    return HttpResponse.json({ success: true, deletedCount: mockDocuments.length });
  }),

  // 채팅 메시지 전송
  http.post(`${BASE_URL}/api/chat`, async ({ request }) => {
    const body = await request.json() as { message: string; sessionId?: string };

    // 특정 메시지에 대한 오류 시뮬레이션
    if (body.message === 'error') {
      return HttpResponse.json(
        { error: 'Internal server error' },
        { status: 500 }
      );
    }

    return HttpResponse.json<ChatResponse>({
      ...mockChatResponse,
      response: `Echo: ${body.message}`,
    });
  }),

  // 새 세션 시작
  http.post(`${BASE_URL}/api/chat/session`, () => {
    return HttpResponse.json({
      session_id: `session-${Date.now()}`,
      ws_token: 'mock-ws-token',
      upload_token: 'mock-upload-token',
      upload_token_expires_at: Math.floor(Date.now() / 1000) + 900,
      upload_token_ttl_seconds: 900,
    });
  }),

  // 채팅 기록 조회
  http.get(`${BASE_URL}/api/chat/history/:sessionId`, () => {
    return HttpResponse.json({
      messages: [
        { role: 'user', content: '안녕하세요', timestamp: new Date().toISOString() },
        { role: 'assistant', content: '안녕하세요! 무엇을 도와드릴까요?', timestamp: new Date().toISOString() },
      ],
    });
  }),

  // 채팅 빈 화면 설정 조회
  http.get(/\/api\/chat-empty-state$/, () => {
    return HttpResponse.json(mockChatEmptyStateSettings);
  }),

  // 세션 삭제
  http.delete(`${BASE_URL}/api/session/:sessionId`, ({ params }) => {
    const { sessionId } = params;
    return HttpResponse.json({ success: true, sessionId });
  }),

  // 프롬프트 목록 조회
  http.get(`${BASE_URL}/api/prompts`, () => {
    return HttpResponse.json([
      { id: '1', name: 'Default', content: 'You are a helpful assistant.' },
      { id: '2', name: 'Technical', content: 'You are a technical expert.' },
    ]);
  }),

  // Qdrant 컬렉션 정보
  http.get(`${BASE_URL}/api/qdrant/collections`, () => {
    return HttpResponse.json([
      { name: 'documents', vectorsCount: 1000, pointsCount: 1000 },
    ]);
  }),

  // 관리자 통계
  http.get(`${BASE_URL}/api/admin/stats`, () => {
    return HttpResponse.json({
      totalDocuments: 42,
      totalSessions: 15,
      totalMessages: 238,
      systemHealth: 'healthy',
    });
  }),
];

// 에러 핸들러 (네트워크 오류 시뮬레이션)
export const errorHandlers = [
  http.get(`${BASE_URL}/api/upload/documents`, () => {
    return HttpResponse.json(
      { error: 'Network error' },
      { status: 503 }
    );
  }),
];

// 지연 핸들러 (느린 네트워크 시뮬레이션)
export const delayedHandlers = [
  http.post(`${BASE_URL}/api/chat`, async ({ request }) => {
    const body = await request.json();
    await new Promise(resolve => setTimeout(resolve, 3000));
    return HttpResponse.json({
      ...mockChatResponse,
      response: `Delayed echo: ${(body as { message: string }).message}`,
    });
  }),
];
