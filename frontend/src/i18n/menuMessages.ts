// OneRAG 번역 카탈로그(타입 안전 사전).
//
// 설계 원칙(OneRAG 범용화):
//   - 특정 언어/도메인 특화 문자열을 차용하지 않는다.
//   - OneRAG 현 UI의 기존 한국어 문자열을 기준으로 카탈로그를 구성하고, 영어를 함께 제공한다.
//   - MenuMessages 인터페이스로 모든 로케일이 동일한 키 집합을 갖도록 컴파일 타임에 강제한다.
//   - 인프라 + 채팅 핵심 UI + PDF 인용 뷰어부터 우선 마이그레이션한다(전 컴포넌트 일괄 번역 아님).
//
// 지원 로케일: 한국어(ko, 기본) / 영어(en).
export const MENU_LOCALES = ["ko", "en"] as const;

export type MenuLocale = (typeof MENU_LOCALES)[number];

// 언어 셀렉터 UI에 표시할 라벨(각 로케일의 자국어 표기 + 선택 라벨).
type LocaleLabels = Record<MenuLocale, string> & {
  label: string;
  select: string;
};

/**
 * MenuMessages - 번역 사전의 키 구조 정의.
 * 모든 로케일은 이 인터페이스를 만족해야 하므로 키 누락 시 빌드가 실패한다.
 */
export interface MenuMessages {
  // 언어 셀렉터
  language: LocaleLabels;
  // 채팅 화면
  chat: {
    header: {
      title: string;
      subtitle: string;
      showDevTools: string;
      newSession: string;
      sessionPrefix: string;
    };
    input: {
      placeholder: string;
      offlinePlaceholder: string;
      offlineNotice: string;
      sendMessage: string;
      stopResponse: string;
      send: string;
      stop: string;
      disconnected: string;
    };
    message: {
      copyAnswer: string;
      copiedNotice: string;
      scrollToBottom: string;
      preparingResponse: string;
      sourcesCount: string;
    };
  };
  // 스트리밍/생성 진행 안내(채팅 메시지 목록)
  chatStream: {
    streaming: string;
    generating: string;
  };
  // 대화방 사이드바
  chatSidebar: {
    defaultTitle: string;
    heading: string;
    subtitle: string;
    newChat: string;
    emptyState: string;
    rename: string;
    delete: string;
    messageCount: string;
  };
  // 개발자 도구 패널
  chatDevTools: {
    title: string;
    close: string;
    sessionInfoTab: string;
    apiLogTab: string;
    currentSession: string;
    sessionStats: string;
    messages: string;
    tokens: string;
    processingTime: string;
    llmModelInfo: string;
    provider: string;
    model: string;
    generationTime: string;
    modelParameters: string;
    debugInfo: string;
    startNewSession: string;
    noApiCalls: string;
    copyLog: string;
    logCopiedNotice: string;
    copy: string;
  };
  // RAG Trace 패널
  ragTrace: {
    flowDescription: string;
    recentQuestion: string;
    noQuestionYet: string;
    topKDocuments: string;
    noSourcesYet: string;
    noContentPreview: string;
    noApiLogs: string;
    booleanTrue: string;
    booleanFalse: string;
  };
  // 청크(인용 출처) 상세 모달
  chunkDetail: {
    modalTitle: string;
    modalDesc: string;
    documentInfo: string;
    documentInfoUnavailable: string;
    chunkContent: string;
    loadingFullContent: string;
    close: string;
    // PDF 인라인 미리보기 / 인용 좌표(#56)
    pdfPreview: string;
    openInNewTab: string;
    pdfPreviewLoading: string;
    pdfPreviewFailed: string;
    citationLocation: string;
    pageSizePrefix: string;
    pagePrefix: string;
    confidencePrefix: string;
    tablePrefix: string;
  };
  // PDF 인용 하이라이트 뷰어(#55)
  pdfViewer: {
    heading: string;
    highlightSuffix: string;
    highlightOverlay: string;
    coordGuide: string;
    citationBox: string;
    loading: string;
    loadFailed: string;
    zoomIn: string;
    zoomOut: string;
    resetZoom: string;
  };
  // 공통
  common: {
    notAvailable: string;
  };
}

// 한국어 카탈로그(OneRAG 현 UI 기준 기본 로케일).
const ko: MenuMessages = {
  language: {
    ko: "한국어",
    en: "English",
    label: "언어",
    select: "언어 선택",
  },
  chat: {
    header: {
      // 브랜드명은 ChatHeader가 BRAND_CONFIG.appName을 앞에 붙입니다.
      // 여기서는 접미 라벨만 보관 → 기본 출력 "OneRAG Chat" 유지, 리브랜딩 시 브랜드명만 교체.
      title: "Chat",
      subtitle: "- 궁금한 것을 질문해주세요!",
      showDevTools: "개발자 도구 보기",
      newSession: "새 대화 시작",
      sessionPrefix: "세션",
    },
    input: {
      placeholder: "메시지를 입력하세요...",
      offlinePlaceholder: "서버 연결 대기 중...",
      offlineNotice: "백엔드 서버와 연결이 끊어졌습니다. 채팅이 불가능합니다.",
      sendMessage: "메시지 보내기",
      stopResponse: "응답 중단하기",
      send: "보내기",
      stop: "중단하기",
      disconnected: "연결 끊김",
    },
    message: {
      copyAnswer: "답변 복사",
      copiedNotice: "답변이 복사되었습니다",
      scrollToBottom: "맨 아래로 이동",
      preparingResponse: "응답을 준비하고 있습니다...",
      sourcesCount: "참고한 문서 ({count}개)",
    },
  },
  chatStream: {
    streaming: "스트리밍 중...",
    generating: "답변을 생성하고 있습니다...",
  },
  chatSidebar: {
    defaultTitle: "새 대화",
    heading: "대화방",
    subtitle: "최근 대화를 빠르게 전환합니다",
    newChat: "새 대화",
    emptyState: "저장된 대화가 없습니다",
    rename: "이름 변경",
    delete: "삭제",
    messageCount: "메시지 {count}개",
  },
  chatDevTools: {
    title: "개발자 도구",
    close: "개발자 도구 닫기",
    sessionInfoTab: "세션 정보",
    apiLogTab: "API 로그",
    currentSession: "현재 세션",
    sessionStats: "세션 통계",
    messages: "메시지",
    tokens: "토큰",
    processingTime: "처리시간",
    llmModelInfo: "LLM 모델 정보",
    provider: "프로바이더",
    model: "모델",
    generationTime: "생성시간",
    modelParameters: "모델 파라미터",
    debugInfo: "Debug 정보",
    startNewSession: "새 세션 시작",
    noApiCalls: "API 호출 내역이 없습니다.",
    copyLog: "로그 복사",
    logCopiedNotice: "로그가 복사되었습니다",
    copy: "복사",
  },
  ragTrace: {
    flowDescription: "검색·재순위·생성 흐름을 확인합니다",
    recentQuestion: "최근 질문",
    noQuestionYet: "아직 질문이 없습니다.",
    topKDocuments: "검색된 문서 Top-K",
    noSourcesYet: "아직 표시할 출처가 없습니다.",
    noContentPreview: "본문 미리보기가 없습니다.",
    noApiLogs: "API 로그가 없습니다.",
    booleanTrue: "예",
    booleanFalse: "아니오",
  },
  chunkDetail: {
    modalTitle: "RAG 참고 자료 상세",
    modalDesc: "선택한 RAG 참고 자료의 문서 정보와 청크 내용을 확인합니다.",
    documentInfo: "문서 정보",
    documentInfoUnavailable: "문서 정보를 불러올 수 없습니다.",
    chunkContent: "청크 내용",
    loadingFullContent: "전체 원문을 불러오는 중...",
    close: "닫기",
    pdfPreview: "PDF 미리보기",
    openInNewTab: "새 탭에서 열기",
    pdfPreviewLoading: "PDF를 불러오는 중...",
    pdfPreviewFailed: "PDF 미리보기를 불러올 수 없습니다.",
    citationLocation: "인용 위치",
    pageSizePrefix: "페이지 크기:",
    pagePrefix: "p.",
    confidencePrefix: "신뢰도",
    tablePrefix: "표",
  },
  pdfViewer: {
    heading: "PDF 인용 위치",
    highlightSuffix: "인용 하이라이트",
    highlightOverlay: "PDF 인용 하이라이트 오버레이",
    coordGuide: "PDF 인용 좌표 안내",
    citationBox: "인용 영역",
    loading: "PDF를 불러오는 중...",
    loadFailed: "PDF를 불러오지 못했습니다.",
    zoomIn: "확대",
    zoomOut: "축소",
    resetZoom: "배율 초기화",
  },
  common: {
    notAvailable: "N/A",
  },
};

// 영어 카탈로그.
const en: MenuMessages = {
  language: {
    ko: "한국어",
    en: "English",
    label: "Language",
    select: "Select language",
  },
  chat: {
    header: {
      // 브랜드명은 ChatHeader가 BRAND_CONFIG.appName을 앞에 붙입니다.
      // 여기서는 접미 라벨만 보관 → 기본 출력 "OneRAG Chat" 유지, 리브랜딩 시 브랜드명만 교체.
      title: "Chat",
      subtitle: "- Ask anything you're curious about!",
      showDevTools: "Show developer tools",
      newSession: "Start new chat",
      sessionPrefix: "Session",
    },
    input: {
      placeholder: "Type a message...",
      offlinePlaceholder: "Waiting for server connection...",
      offlineNotice: "Disconnected from the backend server. Chat is unavailable.",
      sendMessage: "Send message",
      stopResponse: "Stop response",
      send: "Send",
      stop: "Stop",
      disconnected: "Disconnected",
    },
    message: {
      copyAnswer: "Copy answer",
      copiedNotice: "Answer copied",
      scrollToBottom: "Scroll to bottom",
      preparingResponse: "Preparing a response...",
      sourcesCount: "Referenced documents ({count})",
    },
  },
  chatStream: {
    streaming: "Streaming...",
    generating: "Generating a response...",
  },
  chatSidebar: {
    defaultTitle: "New chat",
    heading: "Conversations",
    subtitle: "Quickly switch between recent chats",
    newChat: "New chat",
    emptyState: "No saved conversations",
    rename: "Rename",
    delete: "Delete",
    messageCount: "{count} messages",
  },
  chatDevTools: {
    title: "Developer tools",
    close: "Close developer tools",
    sessionInfoTab: "Session info",
    apiLogTab: "API logs",
    currentSession: "Current session",
    sessionStats: "Session stats",
    messages: "Messages",
    tokens: "Tokens",
    processingTime: "Processing time",
    llmModelInfo: "LLM model info",
    provider: "Provider",
    model: "Model",
    generationTime: "Generation time",
    modelParameters: "Model parameters",
    debugInfo: "Debug info",
    startNewSession: "Start new session",
    noApiCalls: "No API calls yet.",
    copyLog: "Copy log",
    logCopiedNotice: "Log copied",
    copy: "Copy",
  },
  ragTrace: {
    flowDescription: "Review the search, rerank, and generation flow",
    recentQuestion: "Recent question",
    noQuestionYet: "No question yet.",
    topKDocuments: "Top-K retrieved documents",
    noSourcesYet: "No sources to display yet.",
    noContentPreview: "No content preview available.",
    noApiLogs: "No API logs.",
    booleanTrue: "Yes",
    booleanFalse: "No",
  },
  chunkDetail: {
    modalTitle: "RAG Source Details",
    modalDesc: "Review the document info and chunk content of the selected RAG source.",
    documentInfo: "Document info",
    documentInfoUnavailable: "Document info is unavailable.",
    chunkContent: "Chunk content",
    loadingFullContent: "Loading full content...",
    close: "Close",
    pdfPreview: "PDF preview",
    openInNewTab: "Open in new tab",
    pdfPreviewLoading: "Loading PDF...",
    pdfPreviewFailed: "Failed to load the PDF preview.",
    citationLocation: "Citation location",
    pageSizePrefix: "Page size:",
    pagePrefix: "p.",
    confidencePrefix: "Confidence",
    tablePrefix: "Table",
  },
  pdfViewer: {
    heading: "PDF Citation Location",
    highlightSuffix: "citation highlight",
    highlightOverlay: "PDF citation highlight overlay",
    coordGuide: "PDF citation coordinate guide",
    citationBox: "Citation region",
    loading: "Loading PDF...",
    loadFailed: "Failed to load the PDF.",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    resetZoom: "Reset zoom",
  },
  common: {
    notAvailable: "N/A",
  },
};

// 로케일별 사전(모든 로케일이 동일한 키 집합을 보장한다).
export const menuMessages: Record<MenuLocale, MenuMessages> = {
  ko,
  en,
};
