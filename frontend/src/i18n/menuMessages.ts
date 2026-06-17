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
  // 네비게이션 / 레이아웃 / 헤더
  nav: {
    chatbot: string;
    documents: string;
    prompts: string;
    admin: string;
    operationSettings: string;
    adminDashboard: string;
    globalOperationSettings: string;
    upload: string;
    collapseSidebar: string;
    expandSidebar: string;
    floatingExpandSidebar: string;
    logout: string;
    lightMode: string;
    darkMode: string;
    statusHealthy: string;
    statusChecking: string;
    statusError: string;
  };
  // 에러 경계(ErrorBoundary)
  errorBoundary: {
    title: string;
    description: string;
    resetTitle: string;
    reset: string;
    goBack: string;
    contactAdmin: string;
  };
  // 관리자 접근 제어(AccessControl)
  accessControl: {
    title: string;
    description: string;
    placeholder: string;
    invalidCode: string;
    cancel: string;
    confirm: string;
  };
  // 채팅 빈 상태(ChatEmptyState) 잔여
  emptyState: {
    suggestionsHeading: string;
  };
  // 챗봇 Empty State 설정 관리(ChatSettingsManager)
  chatSettings: {
    cardTitle: string;
    cardTooltip: string;
    cardDescription: string;
    editLanguageLabel: string;
    editLanguageSelect: string;
    adminKeyRequiredTitle: string;
    adminKeyPlaceholder: string;
    errorTitle: string;
    mainMessageLabel: string;
    mainMessagePlaceholder: string;
    mainMessageCounter: string;
    subMessageLabel: string;
    subMessagePlaceholder: string;
    subMessageCounter: string;
    suggestionsLabel: string;
    addSuggestion: string;
    suggestionPlaceholder: string;
    suggestionCounter: string;
    deleteSuggestion: string;
    resetToDefault: string;
    saveSettings: string;
    maxSuggestions: string;
    minSuggestions: string;
    adminKeyRequired: string;
    saveFailedTitle: string;
    saveErrorFallback: string;
    saveSuccessTitle: string;
    saveSuccessDescription: string;
    resetSuccessTitle: string;
    resetSuccessDescription: string;
    resetConfirm: string;
  };
  // 공통
  common: {
    notAvailable: string;
    confirm: string;
    cancel: string;
    // 토스트 제목(성공/오류/알림 공통)
    toastError: string;
    toastSuccess: string;
    toastInfo: string;
  };
  // ChatTab — 청크(인용 출처) 상세 정보 라벨
  chatTab: {
    documentId: string;
    documentFilename: string;
    displayTitle: string;
    priority: string;
    chunkNumber: string;
    page: string;
    similarity: string;
    totalChunks: string;
    originalScore: string;
    rerankMethod: string;
    uploadedAt: string;
  };
  // DocumentsTab — 목록 에러/로딩/빈 상태 및 액션
  documentsTab: {
    errorTitle: string;
    errorDescription: string;
    retry: string;
    loading: string;
    emptyTitle: string;
    emptyDescription: string;
    downloadFailed: string;
  };
  // UploadTab — 검증/토스트/상태/UI 라벨
  uploadTab: {
    unsupportedFormat: string;
    fileSizeExceeded: string;
    uploadError: string;
    processingFailed: string;
    processingError: string;
    timeout: string;
    networkError: string;
    jobIdFailed: string;
    uploadCompleted: string;
    uploadFailed: string;
    settingsTitle: string;
    splitterLabel: string;
    splitterPlaceholder: string;
    chunkSizeLabel: string;
    chunkOverlapLabel: string;
    bulkProcessing: string;
    bulkStart: string;
    readyOnly: string;
    selectFilesAria: string;
    dropOrClick: string;
    supportedFormats: string;
    maxSizeNotice: string;
    selectFiles: string;
    uploadFileAria: string;
    uploadListTitle: string;
    removeFileAria: string;
    statusCompleted: string;
    statusFailed: string;
    statusReady: string;
    statusUploading: string;
    statusProcessing: string;
    statusSelected: string;
    badgeUploading: string;
    badgeProcessing: string;
    actionReady: string;
    actionStart: string;
    actionRetry: string;
    processingDetailsToggle: string;
    detailProcessingTime: string;
    detailProcessingTimeValue: string;
    detailChunks: string;
    detailChunksValue: string;
    detailLoaderSplitter: string;
    detailStorageLocation: string;
  };
  // PromptManager — 오류 및 활성화 규칙 안내
  promptManager: {
    errorTitle: string;
    activationRule: string;
  };
  // 페이지 공용 — 탭 라벨, 접근 제어 제목, 저장 메시지
  pages: {
    documentUploadTab: string;
    documentManagementTab: string;
    chatSettingsTab: string;
    documentAccessTitle: string;
    promptAccessTitle: string;
    chatSettingsSaved: string;
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
  nav: {
    chatbot: "챗봇",
    documents: "문서 관리",
    prompts: "프롬프트",
    admin: "관리자",
    operationSettings: "운영 설정",
    adminDashboard: "관리자 대시보드",
    globalOperationSettings: "글로벌 운영 설정",
    upload: "업로드",
    collapseSidebar: "사이드바 축소",
    expandSidebar: "사이드바 확장",
    floatingExpandSidebar: "사이드바 플로팅 확장",
    logout: "로그아웃",
    lightMode: "라이트 모드",
    darkMode: "다크 모드",
    statusHealthy: "정상",
    statusChecking: "확인중",
    statusError: "오류",
  },
  errorBoundary: {
    title: "오류가 발생했습니다",
    description: "예상치 못한 오류가 발생했습니다. 아래 버튼을 클릭하여 다시 시도해주세요.",
    resetTitle: "현재 화면을 초기화하고 다시 로드합니다",
    reset: "화면 새로고침 (초기화)",
    goBack: "이전으로 돌아가기",
    contactAdmin: "문제가 지속되면 관리자에게 문의해주세요.",
  },
  accessControl: {
    title: "관리자 접근",
    description: "이 페이지에 접근하려면 접근코드를 입력하세요.",
    placeholder: "접근코드를 입력하세요",
    invalidCode: "잘못된 접근코드입니다.",
    cancel: "취소",
    confirm: "확인",
  },
  emptyState: {
    suggestionsHeading: "맞춤형 추천 질문 (Personalized Suggestions)",
  },
  chatSettings: {
    cardTitle: "챗봇 Empty State 설정",
    cardTooltip: "채팅이 비어있을 때 표시되는 메시지와 추천 질문을 설정합니다",
    cardDescription: "사용자가 채팅을 시작할 때 표시되는 환영 메시지와 추천 질문을 로케일별로 서버에서 관리합니다",
    editLanguageLabel: "편집 언어",
    editLanguageSelect: "편집 언어 선택",
    adminKeyRequiredTitle: "관리자 API 키가 필요합니다",
    adminKeyPlaceholder: "X-API-Key (관리자 키)",
    errorTitle: "오류가 발생했습니다",
    mainMessageLabel: "메인 메시지",
    mainMessagePlaceholder: "무엇을 도와드릴까요?",
    mainMessageCounter: "{count} / 100자",
    subMessageLabel: "보조 메시지",
    subMessagePlaceholder: "RAG 기반 AI가 문서를 분석하여 정확한 답변을 제공합니다",
    subMessageCounter: "{count} / 200자",
    suggestionsLabel: "추천 질문",
    addSuggestion: "추가",
    suggestionPlaceholder: "추천 질문 {index}",
    suggestionCounter: "{count} / 200자",
    deleteSuggestion: "삭제",
    resetToDefault: "기본값으로 초기화",
    saveSettings: "설정 저장",
    maxSuggestions: "추천 질문은 최대 10개까지 추가할 수 있습니다",
    minSuggestions: "최소 1개의 추천 질문이 필요합니다",
    adminKeyRequired: "관리자 API 키가 필요합니다",
    saveFailedTitle: "저장 실패",
    saveErrorFallback: "설정 저장 중 오류가 발생했습니다",
    saveSuccessTitle: "설정 저장 완료",
    saveSuccessDescription: "대화 시작 화면 설정이 저장되었습니다.",
    resetSuccessTitle: "설정 초기화",
    resetSuccessDescription: "기본 설정으로 복원되었습니다.",
    resetConfirm: "기본 설정으로 초기화하시겠습니까?",
  },
  common: {
    notAvailable: "N/A",
    confirm: "확인",
    cancel: "취소",
    toastError: "오류",
    toastSuccess: "성공",
    toastInfo: "알림",
  },
  chatTab: {
    documentId: "문서 ID",
    documentFilename: "문서 파일명",
    displayTitle: "표시 제목",
    priority: "우선순위",
    chunkNumber: "청크 번호",
    page: "페이지",
    similarity: "유사도",
    totalChunks: "총 청크 수",
    originalScore: "원본 점수",
    rerankMethod: "재순위 방법",
    uploadedAt: "업로드 일시",
  },
  documentsTab: {
    errorTitle: "문서 목록을 불러올 수 없습니다",
    errorDescription: "백엔드 연결을 확인하거나 아래 버튼을 눌러 다시 시도해주세요.",
    retry: "다시 시도",
    loading: "문서 목록을 불러오는 중...",
    emptyTitle: "문서가 없습니다",
    emptyDescription: "검색어를 바꾸거나 새 문서를 업로드해 보세요",
    downloadFailed: "다운로드 실패",
  },
  uploadTab: {
    unsupportedFormat: "지원되지 않는 형식입니다. PDF, TXT, Markdown, DOCX, PPTX, Excel, HTML, JSON만 가능합니다.",
    fileSizeExceeded: "파일 크기는 {limit}를 초과할 수 없습니다.",
    uploadError: "업로드 중 오류가 발생했습니다.",
    processingFailed: "문서 처리에 실패했습니다.",
    processingError: "처리 오류",
    timeout: "시간 초과",
    networkError: "네트워크 상의 문제로 상태 확인 중단",
    jobIdFailed: "작업 ID 생성 실패",
    uploadCompleted: "업로드 완료: {count}개 청크",
    uploadFailed: "{name} 실패: {message}",
    settingsTitle: "업로드 설정",
    splitterLabel: "스플리터",
    splitterPlaceholder: "스플리터 선택",
    chunkSizeLabel: "청크 크기",
    chunkOverlapLabel: "청크 겹침",
    bulkProcessing: "일괄 처리 중...",
    bulkStart: "일괄 처리 시작 ({count})",
    readyOnly: "준비만",
    selectFilesAria: "업로드할 파일 선택",
    dropOrClick: "파일을 여기에 드래그하거나 클릭하세요",
    supportedFormats: "PDF, TXT, Markdown, DOCX, PPTX, Excel, HTML, JSON",
    maxSizeNotice: "(파일당 최대 {limit} 지원, 대용량은 분할 업로드)",
    selectFiles: "파일 선택하기",
    uploadFileAria: "업로드 파일",
    uploadListTitle: "업로드 목록",
    removeFileAria: "{name} 제거",
    statusCompleted: "완료",
    statusFailed: "실패",
    statusReady: "준비됨",
    statusUploading: "업로드 중",
    statusProcessing: "처리 중",
    statusSelected: "선택됨",
    badgeUploading: "Uploading...",
    badgeProcessing: "Processing...",
    actionReady: "준비",
    actionStart: "시작",
    actionRetry: "재시도",
    processingDetailsToggle: "처리 상세 정보",
    detailProcessingTime: "처리 시간",
    detailProcessingTimeValue: "{value}초",
    detailChunks: "청크",
    detailChunksValue: "{count}개",
    detailLoaderSplitter: "로더/스플리터",
    detailStorageLocation: "저장 위치",
  },
  promptManager: {
    errorTitle: "오류 발생",
    activationRule: "프롬프트는 오직 1개만 활성화할 수 있습니다. 새로운 프롬프트를 활성화하면 기존 프롬프트는 자동으로 비활성화됩니다.",
  },
  pages: {
    documentUploadTab: "문서 업로드",
    documentManagementTab: "문서 관리",
    chatSettingsTab: "챗봇 설정",
    documentAccessTitle: "문서 관리 접근",
    promptAccessTitle: "프롬프트 관리 접근",
    chatSettingsSaved: "챗봇 설정이 저장되었습니다",
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
  nav: {
    chatbot: "Chatbot",
    documents: "Documents",
    prompts: "Prompts",
    admin: "Admin",
    operationSettings: "Operation settings",
    adminDashboard: "Admin dashboard",
    globalOperationSettings: "Global operation settings",
    upload: "Upload",
    collapseSidebar: "Collapse sidebar",
    expandSidebar: "Expand sidebar",
    floatingExpandSidebar: "Expand floating sidebar",
    logout: "Log out",
    lightMode: "Light mode",
    darkMode: "Dark mode",
    statusHealthy: "Healthy",
    statusChecking: "Checking",
    statusError: "Error",
  },
  errorBoundary: {
    title: "Something went wrong",
    description: "An unexpected error occurred. Please click the button below to try again.",
    resetTitle: "Reset the current screen and reload",
    reset: "Reload screen (reset)",
    goBack: "Go back",
    contactAdmin: "If the problem persists, please contact your administrator.",
  },
  accessControl: {
    title: "Admin access",
    description: "Enter the access code to access this page.",
    placeholder: "Enter the access code",
    invalidCode: "Invalid access code.",
    cancel: "Cancel",
    confirm: "Confirm",
  },
  emptyState: {
    suggestionsHeading: "Personalized Suggestions",
  },
  chatSettings: {
    cardTitle: "Chatbot Empty State settings",
    cardTooltip: "Configure the message and suggested questions shown when the chat is empty",
    cardDescription: "Manage the welcome message and suggested questions shown when users start a chat, per locale, on the server",
    editLanguageLabel: "Edit language",
    editLanguageSelect: "Select edit language",
    adminKeyRequiredTitle: "An admin API key is required",
    adminKeyPlaceholder: "X-API-Key (admin key)",
    errorTitle: "Something went wrong",
    mainMessageLabel: "Main message",
    mainMessagePlaceholder: "How can I help you?",
    mainMessageCounter: "{count} / 100 chars",
    subMessageLabel: "Secondary message",
    subMessagePlaceholder: "A RAG-based AI analyzes documents to provide accurate answers",
    subMessageCounter: "{count} / 200 chars",
    suggestionsLabel: "Suggested questions",
    addSuggestion: "Add",
    suggestionPlaceholder: "Suggested question {index}",
    suggestionCounter: "{count} / 200 chars",
    deleteSuggestion: "Delete",
    resetToDefault: "Reset to defaults",
    saveSettings: "Save settings",
    maxSuggestions: "You can add up to 10 suggested questions",
    minSuggestions: "At least one suggested question is required",
    adminKeyRequired: "An admin API key is required",
    saveFailedTitle: "Save failed",
    saveErrorFallback: "An error occurred while saving the settings",
    saveSuccessTitle: "Settings saved",
    saveSuccessDescription: "The chat start screen settings have been saved.",
    resetSuccessTitle: "Settings reset",
    resetSuccessDescription: "Restored to default settings.",
    resetConfirm: "Reset to default settings?",
  },
  common: {
    notAvailable: "N/A",
    confirm: "Confirm",
    cancel: "Cancel",
    toastError: "Error",
    toastSuccess: "Success",
    toastInfo: "Notice",
  },
  chatTab: {
    documentId: "Document ID",
    documentFilename: "Document file name",
    displayTitle: "Display title",
    priority: "Priority",
    chunkNumber: "Chunk number",
    page: "Page",
    similarity: "Similarity",
    totalChunks: "Total chunks",
    originalScore: "Original score",
    rerankMethod: "Rerank method",
    uploadedAt: "Uploaded at",
  },
  documentsTab: {
    errorTitle: "Failed to load the document list",
    errorDescription: "Check the backend connection or click the button below to try again.",
    retry: "Try again",
    loading: "Loading the document list...",
    emptyTitle: "No documents",
    emptyDescription: "Try a different search term or upload a new document",
    downloadFailed: "Download failed",
  },
  uploadTab: {
    unsupportedFormat: "Unsupported format. Only PDF, TXT, Markdown, DOCX, PPTX, Excel, HTML, and JSON are allowed.",
    fileSizeExceeded: "File size cannot exceed {limit}.",
    uploadError: "An error occurred during upload.",
    processingFailed: "Failed to process the document.",
    processingError: "Processing error",
    timeout: "Timed out",
    networkError: "Status check stopped due to a network problem",
    jobIdFailed: "Failed to create job ID",
    uploadCompleted: "Upload complete: {count} chunks",
    uploadFailed: "{name} failed: {message}",
    settingsTitle: "Upload settings",
    splitterLabel: "Splitter",
    splitterPlaceholder: "Select splitter",
    chunkSizeLabel: "Chunk size",
    chunkOverlapLabel: "Chunk overlap",
    bulkProcessing: "Bulk processing...",
    bulkStart: "Start bulk processing ({count})",
    readyOnly: "Ready only",
    selectFilesAria: "Select files to upload",
    dropOrClick: "Drag files here or click",
    supportedFormats: "PDF, TXT, Markdown, DOCX, PPTX, Excel, HTML, JSON",
    maxSizeNotice: "(Up to {limit} per file; large files are uploaded in chunks)",
    selectFiles: "Choose files",
    uploadFileAria: "Upload file",
    uploadListTitle: "Upload list",
    removeFileAria: "Remove {name}",
    statusCompleted: "Completed",
    statusFailed: "Failed",
    statusReady: "Ready",
    statusUploading: "Uploading",
    statusProcessing: "Processing",
    statusSelected: "Selected",
    badgeUploading: "Uploading...",
    badgeProcessing: "Processing...",
    actionReady: "Ready",
    actionStart: "Start",
    actionRetry: "Retry",
    processingDetailsToggle: "Processing details",
    detailProcessingTime: "Processing time",
    detailProcessingTimeValue: "{value}s",
    detailChunks: "Chunks",
    detailChunksValue: "{count}",
    detailLoaderSplitter: "Loader/Splitter",
    detailStorageLocation: "Storage location",
  },
  promptManager: {
    errorTitle: "An error occurred",
    activationRule: "Only one prompt can be active at a time. Activating a new prompt automatically deactivates the existing one.",
  },
  pages: {
    documentUploadTab: "Document upload",
    documentManagementTab: "Documents",
    chatSettingsTab: "Chatbot settings",
    documentAccessTitle: "Document management access",
    promptAccessTitle: "Prompt management access",
    chatSettingsSaved: "Chatbot settings saved",
  },
};

// 로케일별 사전(모든 로케일이 동일한 키 집합을 보장한다).
export const menuMessages: Record<MenuLocale, MenuMessages> = {
  ko,
  en,
};
