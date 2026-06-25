// OneRAG 번역 카탈로그(타입 안전 사전).
//
// 설계 원칙(OneRAG 범용화):
//   - 특정 언어/도메인 특화 문자열을 차용하지 않는다.
//   - OneRAG 현 UI의 기존 한국어 문자열을 기준으로 카탈로그를 구성하고, 영어를 함께 제공한다.
//   - MenuMessages 인터페이스로 모든 로케일이 동일한 키 집합을 갖도록 컴파일 타임에 강제한다.
//   - 인프라 + 채팅 핵심 UI + PDF 인용 뷰어부터 우선 마이그레이션한다(전 컴포넌트 일괄 번역 아님).
//
// 지원 로케일: 한국어(ko, 기본) / 영어(en) / 일본어(ja) / 스페인어(es) / 번체중국어(zhHant).
// ko/en은 이 파일에 인라인, 그 외 로케일은 src/i18n/locales/* 모듈에서 합성한다.
import { ja } from "./locales/ja";
import { es } from "./locales/es";
import { zhHant } from "./locales/zhHant";

export const MENU_LOCALES = ["ko", "en", "ja", "es", "zhHant"] as const;

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
    imageLoadFailed: string;
    // 라우트 지연 로딩 폴백 등 공용 로딩 문구
    loading: string;
  };
  // 랜딩 페이지(App.tsx) — 모듈 진입 카드 라벨/설명, 빈 상태, 안내 문구
  landing: {
    prompt: string;
    emptyTitle: string;
    emptyDescription: string;
    chatbotLabel: string;
    chatbotDescription: string;
    documentsLabel: string;
    documentsDescription: string;
    promptsLabel: string;
    promptsDescription: string;
    adminLabel: string;
    adminDescription: string;
  };
  // 프롬프트 카테고리(PROMPT_CATEGORIES) — value별 라벨/설명(상수 value는 보존, 표시 문자열만 카탈로그화)
  promptCategories: {
    system: { label: string; description: string };
    style: { label: string; description: string };
    custom: { label: string; description: string };
  };
  // 테마 프리셋(THEME_PRESETS) — 색상 프리셋 카드 라벨/설명(프리셋 id는 보존, 표시 문자열만 카탈로그화)
  themePresets: {
    monotone: { name: string; description: string };
    modernBlue: { name: string; description: string };
    corporateGreen: { name: string; description: string };
    elegantPurple: { name: string; description: string };
    warmOrange: { name: string; description: string };
    professionalGray: { name: string; description: string };
    vibrantRed: { name: string; description: string };
    tealCyan: { name: string; description: string };
  };
  // VirtualizedDocumentList — 가상화 문서 목록(상태 라벨/크기·업로드 메타)
  virtualDocList: {
    sizeLabel: string;
    uploadLabel: string;
    statusCompleted: string;
    statusProcessing: string;
    statusFailed: string;
    statusUnknown: string;
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
  // DocumentDetailDialog — 문서 상세 정보 다이얼로그
  docDetail: {
    title: string;
    description: string;
    filename: string;
    documentId: string;
    fileSize: string;
    mimeType: string;
    uploadedAt: string;
    status: string;
    chunkCount: string;
    chunkCountValue: string;
    pageCount: string;
    pageCountValue: string;
    wordCount: string;
    wordCountValue: string;
    close: string;
  };
  // 문서 삭제 다이얼로그(단일/일괄/전체) 공용
  docDelete: {
    // 단일 삭제(DocumentDeleteDialog) — 설명은 <br /> 줄바꿈을 사이에 두고 두 줄로 구성
    singleTitle: string;
    singleDescriptionLine1: string;
    singleDescriptionLine2: string;
    deleting: string;
    delete: string;
    // 일괄 삭제(DocumentBulkDeleteDialog) — 설명은 <br /> 줄바꿈을 사이에 두고 두 줄로 구성
    bulkTitle: string;
    bulkDescriptionLine1: string;
    bulkDescriptionLine2: string;
    bulkConfirm: string;
    // 전체 삭제(DocumentDeleteAllDialog)
    allTitle: string;
    allWarning: string;
    allTypingGuide: string;
    allConfirmPhrase: string;
    allTypingPlaceholder: string;
    allConfirmStep: string;
    allExecuteStep: string;
    allCancel: string;
  };
  // DocumentToolbar — 검색/정렬/뷰 모드/삭제 액션
  docToolbar: {
    searchAria: string;
    searchPlaceholder: string;
    sortFieldAria: string;
    sortFieldPlaceholder: string;
    sortUploadedAt: string;
    sortFilename: string;
    sortSize: string;
    sortType: string;
    sortAsc: string;
    sortDesc: string;
    viewList: string;
    viewGrid: string;
    bulkDelete: string;
    deleteAll: string;
    refreshing: string;
    refresh: string;
  };
  // DocumentListView / DocumentGridView — 테이블 헤더 및 카드 액션
  docList: {
    columnFilename: string;
    columnSize: string;
    columnUploadedAt: string;
    columnStatus: string;
    columnAction: string;
    cardDetail: string;
    cardDownload: string;
    cardDelete: string;
  };
  // PromptHeader — 프롬프트 관리 헤더(타이틀/부제/액션 버튼)
  promptHeader: {
    title: string;
    subtitle: string;
    refresh: string;
    import: string;
    export: string;
    createNew: string;
  };
  // PromptTable — 컬럼 헤더, 로딩/빈 상태, 행 액션 툴팁/aria
  promptTable: {
    columnName: string;
    columnDescription: string;
    columnCategory: string;
    columnStatus: string;
    columnUpdatedAt: string;
    columnAction: string;
    loading: string;
    empty: string;
    tooltipView: string;
    tooltipEdit: string;
    tooltipDuplicate: string;
    tooltipDelete: string;
    // aria 라벨은 프롬프트명을 보간한다(어순 보존을 위해 템플릿 전체 보유)
    ariaToggle: string;
    ariaView: string;
    ariaEdit: string;
    ariaDuplicate: string;
    ariaDelete: string;
  };
  // PromptFilterBar — 검색/카테고리/상태 필터
  promptFilter: {
    searchPlaceholder: string;
    categoryPlaceholder: string;
    allCategories: string;
    statusPlaceholder: string;
    allStatus: string;
    activeOnly: string;
    inactiveOnly: string;
    // 총 개수 표시(보간)
    totalCount: string;
  };
  // PromptDeleteDialog — 삭제 확인(설명은 <br /> 줄바꿈을 사이에 두고 두 줄로 구성, 이름은 보간)
  promptDelete: {
    title: string;
    descriptionLine1: string;
    descriptionLine2: string;
    systemWarning: string;
    confirmDelete: string;
  };
  // PromptEditDialog — 생성/편집 폼 라벨, 플레이스홀더, 버튼
  promptEdit: {
    editTitle: string;
    createTitle: string;
    editDescription: string;
    createDescription: string;
    inputErrorTitle: string;
    nameLabel: string;
    namePlaceholder: string;
    systemNameLocked: string;
    descriptionLabel: string;
    descriptionPlaceholder: string;
    categoryLabel: string;
    categoryPlaceholder: string;
    contentLabel: string;
    contentPlaceholder: string;
    activeLabel: string;
    activeHelp: string;
    save: string;
  };
  // PromptViewDialog — 상세 조회 라벨, 본문, 액션
  promptView: {
    title: string;
    description: string;
    nameLabel: string;
    categoryLabel: string;
    descriptionLabel: string;
    noDescription: string;
    createdAtLabel: string;
    updatedAtLabel: string;
    bodyLabel: string;
    copy: string;
    close: string;
    edit: string;
  };
  // PromptImportDialog — 가져오기 폼 라벨, 안내, 버튼
  promptImport: {
    title: string;
    description: string;
    infoNotice: string;
    jsonLabel: string;
    overwriteLabel: string;
    overwriteHelp: string;
    importButton: string;
  };
  // PromptCategoryTabs — 카테고리 탭 라벨(value는 보존, 라벨만 카탈로그화)
  promptTabs: {
    all: string;
    system: string;
    style: string;
    custom: string;
  };
  // AdminDashboard — 관리자 관제 대시보드 전체(헤더/탭/카드/테이블/다이얼로그/토스트/window.confirm)
  adminDashboard: {
    // 토스트(데이터 로딩/연결/세션/인덱스/로그/문서)
    loadFailedToastTitle: string;
    loadFailedToastDesc: string;
    connectedToastTitle: string;
    connectedToastDesc: string;
    disconnectedToastTitle: string;
    disconnectedToastDesc: string;
    newSessionToastTitle: string;
    // 세션 생성 토스트 설명(세션 ID 보간)
    newSessionToastDesc: string;
    rebuildIndexToastTitle: string;
    rebuildIndexToastDesc: string;
    rebuildIndexFailToastTitle: string;
    rebuildIndexFailToastDesc: string;
    logDownloadToastTitle: string;
    logDownloadToastDesc: string;
    downloadFailToastTitle: string;
    downloadFailToastDesc: string;
    sessionLoadFailToastTitle: string;
    sessionLoadFailToastDesc: string;
    sessionDeleteToastTitle: string;
    sessionDeleteToastDesc: string;
    deleteFailToastTitle: string;
    sessionDeleteFailToastDesc: string;
    documentDeleteToastTitle: string;
    documentDeleteToastDesc: string;
    documentDeleteFailToastDesc: string;
    reprocessToastTitle: string;
    reprocessToastDesc: string;
    reprocessFailToastTitle: string;
    reprocessFailToastDesc: string;
    // window.confirm 확인 문구
    rebuildIndexConfirm: string;
    sessionDeleteConfirm: string;
    documentDeleteConfirm: string;
    // 헤더
    headerTitle: string;
    headerSubtitle: string;
    // 헤더 배지(값 보간)
    activeConnections: string;
    responseTime: string;
    // 탭 라벨
    tabOverview: string;
    tabSessions: string;
    tabDocuments: string;
    tabPerformance: string;
    tabPrompts: string;
    tabSettings: string;
    // 개요 탭 — 메트릭 카드 라벨
    metricTotalSessions: string;
    metricTotalQueries: string;
    metricAvgResponseTime: string;
    metricRealtimeConnections: string;
    // 개요 탭 — 인사이트 리스트 제목 및 카운트 단위(보간)
    insightKeywordsTitle: string;
    insightChunksTitle: string;
    insightCountUnit: string;
    // 개요 탭 — 최근 대화 / 시스템 도구 / 글로벌 지표
    recentChatsTitle: string;
    viewAll: string;
    systemToolsTitle: string;
    quickTestRag: string;
    rebuildIndexAction: string;
    exportLogs: string;
    globalMetricsTitle: string;
    // 세션 탭
    sessionsTitle: string;
    sessionsDescription: string;
    statusFilterPlaceholder: string;
    statusAll: string;
    statusActive: string;
    statusIdle: string;
    statusExpired: string;
    columnSessionId: string;
    columnStatus: string;
    columnMessages: string;
    columnCreatedAt: string;
    columnLastActivity: string;
    columnManage: string;
    // 문서 탭
    documentsTitle: string;
    documentsDescription: string;
    registerDocument: string;
    columnDocumentName: string;
    columnChunks: string;
    columnSize: string;
    columnDocStatus: string;
    columnLastUpdate: string;
    columnAction: string;
    reprocessButton: string;
    // 성능 탭
    deviceLoadTitle: string;
    latencyTitle: string;
    // 테스트 다이얼로그
    testDialogTitle: string;
    testDialogDescription: string;
    testQueryLabel: string;
    testQueryPlaceholder: string;
    retrievedChunksLabel: string;
    llmAnswerLabel: string;
    closeButton: string;
    testStartButton: string;
    // 세션 상세 다이얼로그
    sessionDetailTitle: string;
    sessionForceClose: string;
    // 문서 상세 다이얼로그
    documentDetailTitle: string;
    documentPermanentDelete: string;
    // 유지보수 팝업
    maintenanceTitle: string;
    maintenanceDescriptionLine1: string;
    maintenanceDescriptionLine2: string;
    maintenanceBack: string;
  };
  // GlobalSettingsPage — 글로벌 운영 설정 UI 전체
  globalSettings: {
    // 토스트(저장/초기화)
    saveToastTitle: string;
    saveToastDesc: string;
    resetToastTitle: string;
    resetToastDesc: string;
    // 헤더
    badgeOperatorPreview: string;
    badgeLocalStorageMvp: string;
    pageTitle: string;
    pageSubtitle: string;
    resetButton: string;
    saveButton: string;
    // 안내 알림
    mvpNotice: string;
    // 탭
    tabConnection: string;
    tabRagDefaults: string;
    tabFeatureToggle: string;
    // 연결 탭
    connectionCardTitle: string;
    connectionCardDescription: string;
    systemNoticeLabel: string;
    systemNoticePlaceholder: string;
    // RAG 기본값 탭
    ragCardTitle: string;
    ragCardDescription: string;
    defaultModelLabel: string;
    ragProfileLabel: string;
    // 기능 토글 탭
    featureToggleCardTitle: string;
    featureToggleCardDescription: string;
    featureStreaming: string;
    featureDocumentUpload: string;
    featurePhoneMasking: string;
    previewCardTitle: string;
    previewCardDescription: string;
  };
  // SettingsPage — 시스템 설정 UI 전체(프리셋/레이아웃/기능 플래그)
  adminSettings: {
    // 토스트(프리셋/저장/초기화/내보내기)
    presetChangeToastTitle: string;
    // 프리셋 선택 토스트 설명(프리셋 이름 보간)
    presetChangeToastDesc: string;
    saveToastTitle: string;
    saveToastDesc: string;
    resetToastTitle: string;
    resetToastDesc: string;
    exportFailToastTitle: string;
    exportFailToastDesc: string;
    exportSuccessToastTitle: string;
    exportSuccessToastDesc: string;
    // 헤더
    pageTitle: string;
    pageSubtitle: string;
    resetButton: string;
    exportJsonButton: string;
    saveButton: string;
    // 안내 알림(인라인 강조 3조각: 전·중·후)
    noticeBeforeSave: string;
    noticeSave: string;
    noticeBetween: string;
    noticeRefresh: string;
    noticeAfterRefresh: string;
    // 탭
    tabBrand: string;
    tabColors: string;
    tabLayout: string;
    tabFeatures: string;
    // 브랜드 탭
    brandHeading: string;
    brandDescription: string;
    logoCardTitle: string;
    logoCardDescription: string;
    logoPreviewLabel: string;
    logoEmptyPreview: string;
    logoCurrentCustom: string;
    logoCurrentText: string;
    logoHelpText: string;
    logoUploadButton: string;
    logoRemoveButton: string;
    logoSupportedFormats: string;
    logoInvalidFileToastTitle: string;
    logoInvalidFileToastDesc: string;
    logoTooLargeToastDesc: string;
    logoReadFailToastTitle: string;
    logoReadFailToastDesc: string;
    logoSelectedToastTitle: string;
    logoSelectedToastDesc: string;
    // 색상 프리셋 탭
    colorsHeading: string;
    colorsDescription: string;
    presetSelected: string;
    // 레이아웃 탭
    layoutHeading: string;
    layoutDescription: string;
    sidebarWidthLabel: string;
    headerHeightLabel: string;
    contentPaddingLabel: string;
    // 기능 플래그 탭
    featuresHeading: string;
    featuresDescription: string;
    moduleGroupTitle: string;
    moduleGroupDescription: string;
    moduleChatbot: string;
    moduleDocumentManagement: string;
    modulePrompts: string;
    moduleAnalysis: string;
    moduleAdmin: string;
    modulePrivacy: string;
    detailGroupTitle: string;
    detailGroupDescription: string;
    featureStreaming: string;
    featureHistory: string;
    featureUpload: string;
    featureSearch: string;
    featureMaskPhoneNumbers: string;
  };
}

// 한국어 카탈로그(OneRAG 현 UI 기준 기본 로케일).
const ko: MenuMessages = {
  language: {
    ko: "한국어",
    en: "English",
    ja: "日本語",
    es: "Español",
    zhHant: "繁體中文",
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
    imageLoadFailed: "이미지 로드 실패",
    loading: "로딩 중...",
  },
  landing: {
    prompt: "어떤 서비스를 이용하시겠습니까?",
    emptyTitle: "활성화된 기능이 없습니다",
    emptyDescription: "시스템 관리자에게 문의하세요",
    chatbotLabel: "챗봇 사용하기",
    chatbotDescription: "AI 어시스턴트와 대화하세요",
    documentsLabel: "문서 관리",
    documentsDescription: "지식 베이스 문서를 관리합니다",
    promptsLabel: "프롬프트 관리",
    promptsDescription: "AI 모델의 페르소나를 설정합니다",
    adminLabel: "관리자",
    adminDescription: "시스템 설정을 관리합니다",
  },
  promptCategories: {
    system: { label: "시스템", description: "기본 시스템 프롬프트" },
    style: { label: "스타일", description: "답변 스타일 프롬프트" },
    custom: { label: "커스텀", description: "사용자 정의 프롬프트" },
  },
  themePresets: {
    monotone: { name: "모노톤", description: "깔끔한 흑백 디자인으로 전문적인 느낌" },
    modernBlue: { name: "모던 블루", description: "신뢰감 있는 블루 톤으로 기업 이미지에 적합" },
    corporateGreen: { name: "코퍼레이트 그린", description: "친환경적이고 안정적인 그린 톤" },
    elegantPurple: { name: "엘레강트 퍼플", description: "고급스럽고 창의적인 퍼플 톤" },
    warmOrange: { name: "웜 오렌지", description: "따뜻하고 활기찬 오렌지 톤" },
    professionalGray: { name: "프로페셔널 그레이", description: "차분하고 전문적인 그레이 톤" },
    vibrantRed: { name: "바이브런트 레드", description: "강렬하고 열정적인 레드 톤" },
    tealCyan: { name: "틸 시안", description: "시원하고 현대적인 틸 톤" },
  },
  virtualDocList: {
    sizeLabel: "크기: {size}",
    uploadLabel: "업로드: {date}",
    statusCompleted: "완료",
    statusProcessing: "처리중",
    statusFailed: "실패",
    statusUnknown: "알 수 없음",
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
  docDetail: {
    title: "문서 상세 정보",
    description: "문서의 메타데이터와 상태 정보를 확인합니다",
    filename: "파일명",
    documentId: "문서 ID",
    fileSize: "파일 크기",
    mimeType: "MIME 타입",
    uploadedAt: "업로드 일시",
    status: "상태",
    chunkCount: "청크 수",
    chunkCountValue: "{count}개",
    pageCount: "페이지 수",
    pageCountValue: "{count}P",
    wordCount: "단어 수",
    wordCountValue: "{count}개",
    close: "닫기",
  },
  docDelete: {
    singleTitle: "문서 삭제",
    singleDescriptionLine1: "이 문서를 삭제하시겠습니까? ",
    singleDescriptionLine2: "이 작업은 되돌릴 수 없습니다.",
    deleting: "삭제 중...",
    delete: "삭제하기",
    bulkTitle: "{count}개 문서 삭제",
    bulkDescriptionLine1: "선택한 모든 문서를 영구적으로 삭제합니다.",
    bulkDescriptionLine2: "정말 진행하시겠습니까?",
    bulkConfirm: "삭제 승인",
    allTitle: "전체 문서 삭제",
    allWarning: "위험! DB의 모든 문서 데이터가 영구적으로 삭제됩니다. 이 작업은 즉시 실행되며 복구가 불가능합니다.",
    allTypingGuide: "실행하시려면 아래 문구를 정확히 입력하세요:",
    allConfirmPhrase: "문서 삭제에 동의합니다.",
    allTypingPlaceholder: "문구를 입력하세요",
    allConfirmStep: "네, 정말 모두 삭제합니다",
    allExecuteStep: "전체 삭제 실행",
    allCancel: "지금 중단하고 돌아가기",
  },
  docToolbar: {
    searchAria: "문서 검색",
    searchPlaceholder: "문서 검색...",
    sortFieldAria: "정렬 기준",
    sortFieldPlaceholder: "정렬 기준",
    sortUploadedAt: "업로드 일시",
    sortFilename: "파일명",
    sortSize: "파일 크기",
    sortType: "파일 타입",
    sortAsc: "오름차순 정렬",
    sortDesc: "내림차순 정렬",
    viewList: "목록 보기",
    viewGrid: "격자 보기",
    bulkDelete: "선택 삭제 ({count})",
    deleteAll: "전체 삭제",
    refreshing: "문서 새로고침 중",
    refresh: "문서 새로고침",
  },
  docList: {
    columnFilename: "파일명",
    columnSize: "크기",
    columnUploadedAt: "업로드 일시",
    columnStatus: "상태",
    columnAction: "액션",
    cardDetail: "상세",
    cardDownload: "받기",
    cardDelete: "삭제",
  },
  promptHeader: {
    title: "프롬프트 관리",
    subtitle: "시스템 프롬프트를 동적으로 관리하고 페르소나를 설정합니다.",
    refresh: "새로고침",
    import: "가져오기",
    export: "내보내기",
    createNew: "새 프롬프트",
  },
  promptTable: {
    columnName: "프롬프트명",
    columnDescription: "설명",
    columnCategory: "카테고리",
    columnStatus: "상태",
    columnUpdatedAt: "수정일",
    columnAction: "작업",
    loading: "프롬프트 데이터를 불러오는 중...",
    empty: "해당하는 프롬프트가 없습니다.",
    tooltipView: "상세 보기",
    tooltipEdit: "수정",
    tooltipDuplicate: "복제",
    tooltipDelete: "삭제",
    ariaToggle: "{name} 활성 상태 전환",
    ariaView: "{name} 상세 보기",
    ariaEdit: "{name} 수정",
    ariaDuplicate: "{name} 복제",
    ariaDelete: "{name} 삭제",
  },
  promptFilter: {
    searchPlaceholder: "이름 또는 설명으로 검색...",
    categoryPlaceholder: "카테고리 선택",
    allCategories: "전체 카테고리",
    statusPlaceholder: "상태 선택",
    allStatus: "전체 상태",
    activeOnly: "활성 프롬프트",
    inactiveOnly: "비활성 프롬프트",
    totalCount: "총 {count}개",
  },
  promptDelete: {
    title: "프롬프트 삭제",
    descriptionLine1: " 프롬프트를 정말 삭제하시겠습니까?",
    descriptionLine2: "이 작업은 되돌릴 수 없습니다.",
    systemWarning: "시스템 핵심 프롬프트입니다. 삭제 시 시스템 동작이 불안정해질 수 있습니다.",
    confirmDelete: "확인 및 삭제",
  },
  promptEdit: {
    editTitle: "프롬프트 편집",
    createTitle: "새 프롬프트 생성",
    editDescription: "기존 프롬프트를 수정합니다.",
    createDescription: "새로운 시스템 프롬프트를 생성합니다.",
    inputErrorTitle: "입력 오류",
    nameLabel: "프롬프트 이름",
    namePlaceholder: "프롬프트 명칭을 입력하세요",
    systemNameLocked: "시스템 프롬프트는 이름을 변경할 수 없습니다",
    descriptionLabel: "설명",
    descriptionPlaceholder: "어떤 역할이나 페르소나인지 간단히 설명하세요",
    categoryLabel: "카테고리",
    categoryPlaceholder: "카테고리 선택",
    contentLabel: "프롬프트 내용",
    contentPlaceholder: "AI에게 전달할 시스템 지침을 입력하세요...",
    activeLabel: "활성화 상태",
    activeHelp: "저장 시 이 프롬프트를 즉시 적용합니다.",
    save: "저장하기",
  },
  promptView: {
    title: "프롬프트 상세 정보",
    description: "프롬프트의 구성 요소와 설정 내역을 확인합니다.",
    nameLabel: "프롬프트명",
    categoryLabel: "카테고리",
    descriptionLabel: "설명",
    noDescription: "설명이 없습니다.",
    createdAtLabel: "생성일",
    updatedAtLabel: "수정일",
    bodyLabel: "프롬프트 본문",
    copy: "복사",
    close: "닫기",
    edit: "프롬프트 수정",
  },
  promptImport: {
    title: "프롬프트 데이터 가져오기",
    description: "JSON 형식으로 내보낸 프롬프트 데이터를 복사하여 아래에 붙여넣어 주세요.",
    infoNotice: "내보내기 기능을 통해 저장된 파일의 JSON 본문 전체를 입력해 주세요.",
    jsonLabel: "JSON 데이터",
    overwriteLabel: "중복 시 덮어쓰기",
    overwriteHelp: "이미 동일한 이름의 프롬프트가 존재하는 경우 새로운 데이터로 교체합니다.",
    importButton: "데이터 가져오기",
  },
  promptTabs: {
    all: "전체",
    system: "시스템",
    style: "스타일",
    custom: "커스텀",
  },
  adminDashboard: {
    loadFailedToastTitle: "데이터 로딩 실패",
    loadFailedToastDesc: "대시보드 데이터를 불러오지 못했습니다.",
    connectedToastTitle: "연결 성공",
    connectedToastDesc: "실시간 모니터링 연결됨",
    disconnectedToastTitle: "연결 끊김",
    disconnectedToastDesc: "실시간 모니터링 연결 끊김",
    newSessionToastTitle: "새 세션",
    newSessionToastDesc: "세션 생성: {id}",
    rebuildIndexToastTitle: "인덱스 재구축",
    rebuildIndexToastDesc: "인덱스 재구축이 시작되었습니다.",
    rebuildIndexFailToastTitle: "인덱스 재구축 실패",
    rebuildIndexFailToastDesc: "작업을 시작할 수 없습니다.",
    logDownloadToastTitle: "로그 다운로드 완료",
    logDownloadToastDesc: "로그 파일이 생성되었습니다.",
    downloadFailToastTitle: "다운로드 실패",
    downloadFailToastDesc: "로그를 다운로드할 수 없습니다.",
    sessionLoadFailToastTitle: "로딩 실패",
    sessionLoadFailToastDesc: "세션 정보를 불러올 수 없습니다.",
    sessionDeleteToastTitle: "세션 삭제",
    sessionDeleteToastDesc: "세션이 삭제되었습니다.",
    deleteFailToastTitle: "삭제 실패",
    sessionDeleteFailToastDesc: "세션을 삭제할 수 없습니다.",
    documentDeleteToastTitle: "문서 삭제",
    documentDeleteToastDesc: "문서가 삭제되었습니다.",
    documentDeleteFailToastDesc: "문서를 삭제할 수 없습니다.",
    reprocessToastTitle: "재처리 시작",
    reprocessToastDesc: "문서 재처리가 시작되었습니다.",
    reprocessFailToastTitle: "재처리 실패",
    reprocessFailToastDesc: "작업을 시작할 수 없습니다.",
    rebuildIndexConfirm: "전체 인덱스를 재구축하시겠습니까? 이 작업은 시간이 오래 걸릴 수 있습니다.",
    sessionDeleteConfirm: "이 세션을 삭제하시겠습니까?",
    documentDeleteConfirm: "이 문서를 삭제하시겠습니까?",
    headerTitle: "관리자 관제 시스템",
    headerSubtitle: "Production Operations Center",
    activeConnections: "활성 연결: {count}",
    responseTime: "응답: {ms}ms",
    tabOverview: "개요",
    tabSessions: "세션",
    tabDocuments: "문서",
    tabPerformance: "성능",
    tabPrompts: "프롬프트",
    tabSettings: "설정",
    metricTotalSessions: "누적 활성 세션",
    metricTotalQueries: "처리된 총 쿼리",
    metricAvgResponseTime: "평균 응답 지연",
    metricRealtimeConnections: "실시간 연결",
    insightKeywordsTitle: "주요 문의 키워드 TOP 5",
    insightChunksTitle: "자주 인용된 청크 TOP 5",
    insightCountUnit: "{count}회",
    recentChatsTitle: "실시간 쿼리 피드",
    viewAll: "전체보기",
    systemToolsTitle: "시스템 작업",
    quickTestRag: "RAG 엔진 빠른 테스트",
    rebuildIndexAction: "벡터 인덱스 전체 재구축",
    exportLogs: "시스템 실행 로그 내보내기",
    globalMetricsTitle: "글로벌 지표",
    sessionsTitle: "활성 세션 관리",
    sessionsDescription: "실시간 사용자 세션 및 하이재킹 모니터링",
    statusFilterPlaceholder: "상태 필터",
    statusAll: "전체 상태",
    statusActive: "활성",
    statusIdle: "대기",
    statusExpired: "만료",
    columnSessionId: "세션 식별자",
    columnStatus: "상태",
    columnMessages: "메시지",
    columnCreatedAt: "생성 일시",
    columnLastActivity: "마지막 활동",
    columnManage: "관리",
    documentsTitle: "시맨틱 데이터 자산",
    documentsDescription: "벡터 데이터베이스에 등록된 청크화된 문서 목록",
    registerDocument: "새 문서 등록",
    columnDocumentName: "문서명",
    columnChunks: "청크",
    columnSize: "용량",
    columnDocStatus: "상태",
    columnLastUpdate: "최종 갱신",
    columnAction: "작업",
    reprocessButton: "재처리",
    deviceLoadTitle: "장치 리소스 실시간 부하",
    latencyTitle: "시계열 서비스 지연 시간 (Latency)",
    testDialogTitle: "RAG 시맨틱 엔진 테스트",
    testDialogDescription: "현재 활성화된 프롬프트와 문서 데이터를 기반으로 추론 성능을 검증합니다.",
    testQueryLabel: "테스트 쿼리 입력",
    testQueryPlaceholder: "검색할 질문을 입력하세요...",
    retrievedChunksLabel: "인용된 소스 (Retrieved Chunks)",
    llmAnswerLabel: "생성된 응답 (LLM Answer)",
    closeButton: "닫기",
    testStartButton: "테스트 시작",
    sessionDetailTitle: "세션 포렌식 정보",
    sessionForceClose: "세션 강제 종료",
    documentDetailTitle: "데이터 자산 명세",
    documentPermanentDelete: "영구 삭제",
    maintenanceTitle: "🔧 시스템 업그레이드 중",
    maintenanceDescriptionLine1: "관리자 모니터링 모듈을 더 강력하고 안전하게 개선하고 있습니다.",
    maintenanceDescriptionLine2: "잠시 후 다시 시도해 주세요.",
    maintenanceBack: "대시보드로 돌아가기",
  },
  globalSettings: {
    saveToastTitle: "글로벌 설정 저장 완료",
    saveToastDesc: "운영 설정이 저장되었고 앱 런타임 설정에 반영되었습니다.",
    resetToastTitle: "글로벌 설정 초기화",
    resetToastDesc: "운영 설정이 기본값으로 초기화되었습니다.",
    badgeOperatorPreview: "Operator Preview",
    badgeLocalStorageMvp: "localStorage MVP",
    pageTitle: "글로벌 운영 설정",
    pageSubtitle: "API 연결, 기본 모델, RAG 프로필, 기능 토글을 한 화면에서 관리합니다.",
    resetButton: "초기화",
    saveButton: "저장",
    mvpNotice: "이 브랜치는 관리자 설정 UX의 프론트 MVP입니다. 실제 운영 저장은 추후 백엔드 설정 API와 연결하면 됩니다.",
    tabConnection: "연결",
    tabRagDefaults: "RAG 기본값",
    tabFeatureToggle: "기능 토글",
    connectionCardTitle: "백엔드 연결 설정",
    connectionCardDescription: "개발·스테이징·운영 환경별 API 주소를 빠르게 바꿀 수 있게 하는 UI입니다.",
    systemNoticeLabel: "시스템 공지",
    systemNoticePlaceholder: "사용자에게 보여줄 점검/테스트 안내 문구",
    ragCardTitle: "RAG 실행 기본값",
    ragCardDescription: "데모와 PoC에서 자주 바꾸는 모델·프로필·청킹 값을 모았습니다.",
    defaultModelLabel: "기본 모델",
    ragProfileLabel: "RAG 프로필",
    featureToggleCardTitle: "운영 기능 토글",
    featureToggleCardDescription: "주요 기능을 관리자 화면에서 켜고 끄는 MVP입니다.",
    featureStreaming: "WebSocket 스트리밍",
    featureDocumentUpload: "문서 업로드",
    featurePhoneMasking: "전화번호 마스킹",
    previewCardTitle: "저장될 설정 미리보기",
    previewCardDescription: "백엔드 설정 API 연결 시 그대로 payload로 확장할 수 있습니다.",
  },
  adminSettings: {
    presetChangeToastTitle: "프리셋 변경",
    presetChangeToastDesc: "프리셋 \"{name}\"이(가) 선택되었습니다.",
    saveToastTitle: "설정 저장 완료",
    saveToastDesc: "✅ 설정이 저장되었습니다! 페이지를 새로고침하면 적용됩니다.",
    resetToastTitle: "설정 초기화",
    resetToastDesc: "✅ 설정이 초기화되었습니다. 페이지를 새로고침하면 적용됩니다.",
    exportFailToastTitle: "내보내기 실패",
    exportFailToastDesc: "프리셋을 내보낼 수 없습니다.",
    exportSuccessToastTitle: "내보내기 성공",
    exportSuccessToastDesc: "설정이 JSON 파일로 다운로드되었습니다.",
    pageTitle: "시스템 설정",
    pageSubtitle: "브랜드, 색상, 레이아웃, 기능 플래그를 관리합니다.",
    resetButton: "초기화",
    exportJsonButton: "JSON 내보내기",
    saveButton: "설정 저장",
    noticeBeforeSave: "설정 변경 후 ",
    noticeSave: "저장",
    noticeBetween: " 버튼을 누르고 ",
    noticeRefresh: "페이지를 새로고침",
    noticeAfterRefresh: "하셔야 변경 사항이 반영됩니다.",
    tabBrand: "브랜드",
    tabColors: "색상 프리셋",
    tabLayout: "레이아웃",
    tabFeatures: "기능 플래그",
    brandHeading: "🏷️ 브랜드 로고",
    brandDescription: "관리자 화면에서 로고 이미지를 업로드해 사이드바와 헤더 로고를 교체합니다.",
    logoCardTitle: "로고 이미지",
    logoCardDescription: "PNG, JPG, SVG, WebP 파일을 업로드하면 저장 후 앱 로고로 적용됩니다.",
    logoPreviewLabel: "현재 선택",
    logoEmptyPreview: "텍스트 로고 사용 중",
    logoCurrentCustom: "사용자 지정 로고",
    logoCurrentText: "기본 텍스트 로고",
    logoHelpText: "선택한 이미지는 브라우저 런타임 설정에 저장됩니다. 운영 저장소가 연결되기 전까지는 현재 브라우저 환경에서 적용됩니다.",
    logoUploadButton: "로고 업로드",
    logoRemoveButton: "로고 제거",
    logoSupportedFormats: "지원 형식: PNG, JPG, SVG, WebP / 최대 512KB",
    logoInvalidFileToastTitle: "로고 파일을 사용할 수 없습니다",
    logoInvalidFileToastDesc: "PNG, JPG, SVG, WebP 형식의 이미지만 업로드할 수 있습니다.",
    logoTooLargeToastDesc: "로고 파일은 512KB 이하로 업로드해 주세요.",
    logoReadFailToastTitle: "로고 읽기 실패",
    logoReadFailToastDesc: "파일을 읽는 중 오류가 발생했습니다. 다른 이미지를 선택해 주세요.",
    logoSelectedToastTitle: "로고 선택 완료",
    logoSelectedToastDesc: "\"{name}\" 파일이 선택되었습니다. 저장 후 새로고침하면 적용됩니다.",
    colorsHeading: "🎨 테마 프리셋 선택",
    colorsDescription: "데이터 플랫폼의 무드를 결정하는 8가지 공식 프리셋 중 하나를 선택하세요.",
    presetSelected: "선택됨",
    layoutHeading: "📐 레이아웃 정밀 설정",
    layoutDescription: "브라우저 내 공간 활용도를 조절합니다. 사이드바와 헤더의 규격을 변경할 수 있습니다.",
    sidebarWidthLabel: "사이드바 너비 (Sidebar)",
    headerHeightLabel: "헤더 높이 (Header)",
    contentPaddingLabel: "콘텐츠 여백 (Padding)",
    featuresHeading: "🚩 기능 제어 플래그",
    featuresDescription: "특정 모듈을 완전히 활성화하거나 세부 기능의 동작 여부를 결정합니다.",
    moduleGroupTitle: "📦 시스템 모듈 제어",
    moduleGroupDescription: "핵심 비즈니스 모듈 활성화 여부",
    moduleChatbot: "인텔리전트 챗봇",
    moduleDocumentManagement: "중앙 문서 관리 센터",
    modulePrompts: "AI 프롬프트 매니저",
    moduleAnalysis: "실시간 DB 통계/분석",
    moduleAdmin: "시스템 관리자 도구",
    modulePrivacy: "개인정보 보호 필터 (Privacy)",
    detailGroupTitle: "⚙️ 세부 컴포넌트 동작",
    detailGroupDescription: "활성화된 모듈 내 상세 기능 옵션",
    featureStreaming: "스트리밍 실시간 응답",
    featureHistory: "다차원 채팅 히스토리",
    featureUpload: "대용량 파일 배치 업로드",
    featureSearch: "고급 시맨틱 문서 검색",
    featureMaskPhoneNumbers: "연락처 정보 패턴 마스킹",
  },
};

// 영어 카탈로그.
const en: MenuMessages = {
  language: {
    ko: "한국어",
    en: "English",
    ja: "日本語",
    es: "Español",
    zhHant: "繁體中文",
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
    imageLoadFailed: "Failed to load image",
    loading: "Loading...",
  },
  landing: {
    prompt: "Which service would you like to use?",
    emptyTitle: "No features are enabled",
    emptyDescription: "Please contact your system administrator",
    chatbotLabel: "Start chatting",
    chatbotDescription: "Talk with the AI assistant",
    documentsLabel: "Document management",
    documentsDescription: "Manage your knowledge base documents",
    promptsLabel: "Prompt management",
    promptsDescription: "Configure the AI model's persona",
    adminLabel: "Admin",
    adminDescription: "Manage system settings",
  },
  promptCategories: {
    system: { label: "System", description: "Default system prompt" },
    style: { label: "Style", description: "Answer style prompt" },
    custom: { label: "Custom", description: "User-defined prompt" },
  },
  themePresets: {
    monotone: { name: "Monotone", description: "A clean black-and-white design with a professional feel" },
    modernBlue: { name: "Modern Blue", description: "A trustworthy blue tone suited to a corporate image" },
    corporateGreen: { name: "Corporate Green", description: "An eco-friendly and stable green tone" },
    elegantPurple: { name: "Elegant Purple", description: "A luxurious and creative purple tone" },
    warmOrange: { name: "Warm Orange", description: "A warm and vibrant orange tone" },
    professionalGray: { name: "Professional Gray", description: "A calm and professional gray tone" },
    vibrantRed: { name: "Vibrant Red", description: "An intense and passionate red tone" },
    tealCyan: { name: "Teal Cyan", description: "A cool and modern teal tone" },
  },
  virtualDocList: {
    sizeLabel: "Size: {size}",
    uploadLabel: "Uploaded: {date}",
    statusCompleted: "Completed",
    statusProcessing: "Processing",
    statusFailed: "Failed",
    statusUnknown: "Unknown",
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
  docDetail: {
    title: "Document details",
    description: "Review the document's metadata and status",
    filename: "File name",
    documentId: "Document ID",
    fileSize: "File size",
    mimeType: "MIME type",
    uploadedAt: "Uploaded at",
    status: "Status",
    chunkCount: "Chunks",
    chunkCountValue: "{count}",
    pageCount: "Pages",
    pageCountValue: "{count}P",
    wordCount: "Words",
    wordCountValue: "{count}",
    close: "Close",
  },
  docDelete: {
    singleTitle: "Delete document",
    singleDescriptionLine1: "Delete this document? ",
    singleDescriptionLine2: "This action cannot be undone.",
    deleting: "Deleting...",
    delete: "Delete",
    bulkTitle: "Delete {count} documents",
    bulkDescriptionLine1: "All selected documents will be permanently deleted.",
    bulkDescriptionLine2: "Are you sure you want to proceed?",
    bulkConfirm: "Confirm delete",
    allTitle: "Delete all documents",
    allWarning: "Warning! All document data in the database will be permanently deleted. This action runs immediately and cannot be recovered.",
    allTypingGuide: "To proceed, type the phrase below exactly:",
    allConfirmPhrase: "I agree to delete the documents.",
    allTypingPlaceholder: "Type the phrase",
    allConfirmStep: "Yes, delete them all",
    allExecuteStep: "Delete all",
    allCancel: "Stop and go back",
  },
  docToolbar: {
    searchAria: "Search documents",
    searchPlaceholder: "Search documents...",
    sortFieldAria: "Sort by",
    sortFieldPlaceholder: "Sort by",
    sortUploadedAt: "Uploaded at",
    sortFilename: "File name",
    sortSize: "File size",
    sortType: "File type",
    sortAsc: "Sort ascending",
    sortDesc: "Sort descending",
    viewList: "List view",
    viewGrid: "Grid view",
    bulkDelete: "Delete selected ({count})",
    deleteAll: "Delete all",
    refreshing: "Refreshing documents",
    refresh: "Refresh documents",
  },
  docList: {
    columnFilename: "File name",
    columnSize: "Size",
    columnUploadedAt: "Uploaded at",
    columnStatus: "Status",
    columnAction: "Actions",
    cardDetail: "Details",
    cardDownload: "Download",
    cardDelete: "Delete",
  },
  promptHeader: {
    title: "Prompt management",
    subtitle: "Dynamically manage system prompts and configure personas.",
    refresh: "Refresh",
    import: "Import",
    export: "Export",
    createNew: "New prompt",
  },
  promptTable: {
    columnName: "Prompt name",
    columnDescription: "Description",
    columnCategory: "Category",
    columnStatus: "Status",
    columnUpdatedAt: "Updated",
    columnAction: "Actions",
    loading: "Loading prompt data...",
    empty: "No matching prompts.",
    tooltipView: "View details",
    tooltipEdit: "Edit",
    tooltipDuplicate: "Duplicate",
    tooltipDelete: "Delete",
    ariaToggle: "Toggle active state for {name}",
    ariaView: "View details for {name}",
    ariaEdit: "Edit {name}",
    ariaDuplicate: "Duplicate {name}",
    ariaDelete: "Delete {name}",
  },
  promptFilter: {
    searchPlaceholder: "Search by name or description...",
    categoryPlaceholder: "Select category",
    allCategories: "All categories",
    statusPlaceholder: "Select status",
    allStatus: "All statuses",
    activeOnly: "Active prompts",
    inactiveOnly: "Inactive prompts",
    totalCount: "{count} total",
  },
  promptDelete: {
    title: "Delete prompt",
    descriptionLine1: " prompt? Are you sure you want to delete it?",
    descriptionLine2: "This action cannot be undone.",
    systemWarning: "This is a core system prompt. Deleting it may destabilize system behavior.",
    confirmDelete: "Confirm and delete",
  },
  promptEdit: {
    editTitle: "Edit prompt",
    createTitle: "Create new prompt",
    editDescription: "Edit the existing prompt.",
    createDescription: "Create a new system prompt.",
    inputErrorTitle: "Input error",
    nameLabel: "Prompt name",
    namePlaceholder: "Enter a prompt name",
    systemNameLocked: "System prompt names cannot be changed",
    descriptionLabel: "Description",
    descriptionPlaceholder: "Briefly describe the role or persona",
    categoryLabel: "Category",
    categoryPlaceholder: "Select category",
    contentLabel: "Prompt content",
    contentPlaceholder: "Enter the system instructions to send to the AI...",
    activeLabel: "Active state",
    activeHelp: "Apply this prompt immediately when saved.",
    save: "Save",
  },
  promptView: {
    title: "Prompt details",
    description: "Review the prompt's components and settings.",
    nameLabel: "Prompt name",
    categoryLabel: "Category",
    descriptionLabel: "Description",
    noDescription: "No description.",
    createdAtLabel: "Created",
    updatedAtLabel: "Updated",
    bodyLabel: "Prompt body",
    copy: "Copy",
    close: "Close",
    edit: "Edit prompt",
  },
  promptImport: {
    title: "Import prompt data",
    description: "Copy prompt data exported in JSON format and paste it below.",
    infoNotice: "Enter the full JSON body of a file saved via the export feature.",
    jsonLabel: "JSON data",
    overwriteLabel: "Overwrite on conflict",
    overwriteHelp: "If a prompt with the same name already exists, replace it with the new data.",
    importButton: "Import data",
  },
  promptTabs: {
    all: "All",
    system: "System",
    style: "Style",
    custom: "Custom",
  },
  adminDashboard: {
    loadFailedToastTitle: "Failed to load data",
    loadFailedToastDesc: "Could not load the dashboard data.",
    connectedToastTitle: "Connected",
    connectedToastDesc: "Real-time monitoring connected",
    disconnectedToastTitle: "Disconnected",
    disconnectedToastDesc: "Real-time monitoring disconnected",
    newSessionToastTitle: "New session",
    newSessionToastDesc: "Session created: {id}",
    rebuildIndexToastTitle: "Rebuild index",
    rebuildIndexToastDesc: "Index rebuild has started.",
    rebuildIndexFailToastTitle: "Index rebuild failed",
    rebuildIndexFailToastDesc: "Could not start the task.",
    logDownloadToastTitle: "Log download complete",
    logDownloadToastDesc: "The log file has been created.",
    downloadFailToastTitle: "Download failed",
    downloadFailToastDesc: "Could not download the logs.",
    sessionLoadFailToastTitle: "Load failed",
    sessionLoadFailToastDesc: "Could not load the session info.",
    sessionDeleteToastTitle: "Session deleted",
    sessionDeleteToastDesc: "The session has been deleted.",
    deleteFailToastTitle: "Delete failed",
    sessionDeleteFailToastDesc: "Could not delete the session.",
    documentDeleteToastTitle: "Document deleted",
    documentDeleteToastDesc: "The document has been deleted.",
    documentDeleteFailToastDesc: "Could not delete the document.",
    reprocessToastTitle: "Reprocessing started",
    reprocessToastDesc: "Document reprocessing has started.",
    reprocessFailToastTitle: "Reprocessing failed",
    reprocessFailToastDesc: "Could not start the task.",
    rebuildIndexConfirm: "Rebuild the entire index? This operation may take a long time.",
    sessionDeleteConfirm: "Delete this session?",
    documentDeleteConfirm: "Delete this document?",
    headerTitle: "Admin Control Center",
    headerSubtitle: "Production Operations Center",
    activeConnections: "Active connections: {count}",
    responseTime: "Response: {ms}ms",
    tabOverview: "Overview",
    tabSessions: "Sessions",
    tabDocuments: "Documents",
    tabPerformance: "Performance",
    tabPrompts: "Prompts",
    tabSettings: "Settings",
    metricTotalSessions: "Total active sessions",
    metricTotalQueries: "Total queries processed",
    metricAvgResponseTime: "Average response latency",
    metricRealtimeConnections: "Real-time connections",
    insightKeywordsTitle: "Top 5 inquiry keywords",
    insightChunksTitle: "Top 5 most cited chunks",
    insightCountUnit: "{count} times",
    recentChatsTitle: "Real-time query feed",
    viewAll: "View all",
    systemToolsTitle: "System tasks",
    quickTestRag: "Quick RAG engine test",
    rebuildIndexAction: "Rebuild entire vector index",
    exportLogs: "Export system execution logs",
    globalMetricsTitle: "Global metrics",
    sessionsTitle: "Active session management",
    sessionsDescription: "Real-time user sessions and hijacking monitoring",
    statusFilterPlaceholder: "Status filter",
    statusAll: "All statuses",
    statusActive: "Active",
    statusIdle: "Idle",
    statusExpired: "Expired",
    columnSessionId: "Session ID",
    columnStatus: "Status",
    columnMessages: "Messages",
    columnCreatedAt: "Created at",
    columnLastActivity: "Last activity",
    columnManage: "Manage",
    documentsTitle: "Semantic data assets",
    documentsDescription: "List of chunked documents registered in the vector database",
    registerDocument: "Register new document",
    columnDocumentName: "Document name",
    columnChunks: "Chunks",
    columnSize: "Size",
    columnDocStatus: "Status",
    columnLastUpdate: "Last updated",
    columnAction: "Actions",
    reprocessButton: "Reprocess",
    deviceLoadTitle: "Real-time device resource load",
    latencyTitle: "Time-series service latency (Latency)",
    testDialogTitle: "RAG semantic engine test",
    testDialogDescription: "Validate inference performance based on the currently active prompt and document data.",
    testQueryLabel: "Test query input",
    testQueryPlaceholder: "Enter a question to search...",
    retrievedChunksLabel: "Cited sources (Retrieved Chunks)",
    llmAnswerLabel: "Generated response (LLM Answer)",
    closeButton: "Close",
    testStartButton: "Start test",
    sessionDetailTitle: "Session forensics info",
    sessionForceClose: "Force-close session",
    documentDetailTitle: "Data asset specification",
    documentPermanentDelete: "Delete permanently",
    maintenanceTitle: "🔧 System upgrade in progress",
    maintenanceDescriptionLine1: "We are making the admin monitoring module more powerful and secure.",
    maintenanceDescriptionLine2: "Please try again shortly.",
    maintenanceBack: "Back to dashboard",
  },
  globalSettings: {
    saveToastTitle: "Global settings saved",
    saveToastDesc: "Operation settings have been saved and applied to the app runtime config.",
    resetToastTitle: "Global settings reset",
    resetToastDesc: "Operation settings have been reset to their defaults.",
    badgeOperatorPreview: "Operator Preview",
    badgeLocalStorageMvp: "localStorage MVP",
    pageTitle: "Global operation settings",
    pageSubtitle: "Manage API connections, default models, RAG profiles, and feature toggles in one screen.",
    resetButton: "Reset",
    saveButton: "Save",
    mvpNotice: "This branch is a frontend MVP of the admin settings UX. Actual operation storage can later be connected to a backend settings API.",
    tabConnection: "Connection",
    tabRagDefaults: "RAG defaults",
    tabFeatureToggle: "Feature toggles",
    connectionCardTitle: "Backend connection settings",
    connectionCardDescription: "A UI to quickly switch API addresses per development, staging, and production environment.",
    systemNoticeLabel: "System notice",
    systemNoticePlaceholder: "Maintenance/test notice text to show users",
    ragCardTitle: "RAG execution defaults",
    ragCardDescription: "A collection of model, profile, and chunking values frequently changed in demos and PoCs.",
    defaultModelLabel: "Default model",
    ragProfileLabel: "RAG profile",
    featureToggleCardTitle: "Operation feature toggles",
    featureToggleCardDescription: "An MVP to turn key features on and off from the admin screen.",
    featureStreaming: "WebSocket streaming",
    featureDocumentUpload: "Document upload",
    featurePhoneMasking: "Phone number masking",
    previewCardTitle: "Preview of settings to be saved",
    previewCardDescription: "Can be expanded as the payload directly when connecting a backend settings API.",
  },
  adminSettings: {
    presetChangeToastTitle: "Preset changed",
    presetChangeToastDesc: "Preset \"{name}\" has been selected.",
    saveToastTitle: "Settings saved",
    saveToastDesc: "✅ Settings have been saved! They apply after you refresh the page.",
    resetToastTitle: "Settings reset",
    resetToastDesc: "✅ Settings have been reset. They apply after you refresh the page.",
    exportFailToastTitle: "Export failed",
    exportFailToastDesc: "Could not export the preset.",
    exportSuccessToastTitle: "Export succeeded",
    exportSuccessToastDesc: "The settings have been downloaded as a JSON file.",
    pageTitle: "System settings",
    pageSubtitle: "Manage brand, colors, layout, and feature flags.",
    resetButton: "Reset",
    exportJsonButton: "Export JSON",
    saveButton: "Save settings",
    noticeBeforeSave: "After changing settings, click ",
    noticeSave: "Save",
    noticeBetween: " and ",
    noticeRefresh: "refresh the page",
    noticeAfterRefresh: " for the changes to take effect.",
    tabBrand: "Brand",
    tabColors: "Color presets",
    tabLayout: "Layout",
    tabFeatures: "Feature flags",
    brandHeading: "🏷️ Brand logo",
    brandDescription: "Upload a logo image from the admin screen and replace the sidebar and header logo.",
    logoCardTitle: "Logo image",
    logoCardDescription: "Upload a PNG, JPG, SVG, or WebP file and save it to apply it as the app logo.",
    logoPreviewLabel: "Current selection",
    logoEmptyPreview: "Using text logo",
    logoCurrentCustom: "Custom logo",
    logoCurrentText: "Default text logo",
    logoHelpText: "The selected image is stored in browser runtime settings. Until backend settings storage is connected, it applies to the current browser environment.",
    logoUploadButton: "Upload logo",
    logoRemoveButton: "Remove logo",
    logoSupportedFormats: "Supported: PNG, JPG, SVG, WebP / max 512KB",
    logoInvalidFileToastTitle: "Logo file cannot be used",
    logoInvalidFileToastDesc: "Only PNG, JPG, SVG, and WebP images can be uploaded.",
    logoTooLargeToastDesc: "Upload a logo file that is 512KB or smaller.",
    logoReadFailToastTitle: "Could not read logo",
    logoReadFailToastDesc: "An error occurred while reading the file. Choose another image.",
    logoSelectedToastTitle: "Logo selected",
    logoSelectedToastDesc: "\"{name}\" has been selected. Save and refresh to apply it.",
    colorsHeading: "🎨 Select theme preset",
    colorsDescription: "Choose one of the 8 official presets that set the mood of the data platform.",
    presetSelected: "Selected",
    layoutHeading: "📐 Layout fine-tuning",
    layoutDescription: "Adjust how space is used within the browser. You can change the sidebar and header dimensions.",
    sidebarWidthLabel: "Sidebar width (Sidebar)",
    headerHeightLabel: "Header height (Header)",
    contentPaddingLabel: "Content padding (Padding)",
    featuresHeading: "🚩 Feature control flags",
    featuresDescription: "Fully enable specific modules or decide whether detailed features operate.",
    moduleGroupTitle: "📦 System module control",
    moduleGroupDescription: "Whether to enable core business modules",
    moduleChatbot: "Intelligent chatbot",
    moduleDocumentManagement: "Central document management hub",
    modulePrompts: "AI prompt manager",
    moduleAnalysis: "Real-time DB stats/analysis",
    moduleAdmin: "System admin tools",
    modulePrivacy: "Privacy protection filter (Privacy)",
    detailGroupTitle: "⚙️ Detailed component behavior",
    detailGroupDescription: "Detailed feature options within enabled modules",
    featureStreaming: "Streaming real-time response",
    featureHistory: "Multi-dimensional chat history",
    featureUpload: "Large-file batch upload",
    featureSearch: "Advanced semantic document search",
    featureMaskPhoneNumbers: "Contact info pattern masking",
  },
};

// 로케일별 사전(모든 로케일이 동일한 키 집합을 보장한다).
// ko/en은 이 파일에 인라인, 추가 로케일(ja/es/zhHant)은 src/i18n/locales/* 모듈에서 합성한다.
export const menuMessages: Record<MenuLocale, MenuMessages> = {
  ko,
  en,
  ja,
  es,
  zhHant,
};
