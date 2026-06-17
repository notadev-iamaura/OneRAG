// OneRAG 번역 카탈로그(타입 안전 사전).
//
// 설계 원칙(OneRAG 범용화):
//   - JapanRAG의 일본어/도메인 특화 문자열을 차용하지 않는다.
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
    };
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
    },
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
    },
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
