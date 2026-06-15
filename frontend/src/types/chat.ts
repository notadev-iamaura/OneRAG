import {
    ChatMessage as BaseChatMessage,
    Source as BaseSource,
    SessionInfo as BaseSessionInfo,
    ToastMessage,
    CitationRegion as BaseCitationRegion,
    PageDimensions as BasePageDimensions,
} from './index';

export interface DocumentInfoItem {
    label: string;
    value: string;
}

export interface ApiLog {
    id: string;
    timestamp: string;
    type: 'request' | 'response';
    method: string;
    endpoint: string;
    data: unknown;
    status?: number;
    duration?: number;
}

export interface ChatTabProps {
    showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

// Re-export or extend base types if needed for chat-specific context
export type { BaseChatMessage as ChatMessage, BaseSource as Source, BaseSessionInfo as SessionInfo };
// PDF 인용 하이라이트(#55)용 타입 re-export (PdfCitationPreview/pdfCitationGeometry에서 사용)
export type { BaseCitationRegion as CitationRegion, BasePageDimensions as PageDimensions };
