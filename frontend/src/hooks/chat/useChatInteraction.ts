import { useState, useRef, useEffect, useCallback } from 'react';
import { useMediaQuery } from '../useMediaQuery';
import { Source as SourceType, SourceDetail, ToastMessage, ChatMessage } from '../../types';
import { chatAPI } from '../../services/api';
import { logger } from '../../utils/logger';

interface UseChatInteractionProps {
    messages: ChatMessage[];
    showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

export const useChatInteraction = ({ messages, showToast }: UseChatInteractionProps) => {
    // 스크롤 Ref
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // 상태 관리
    const [modalOpen, setModalOpen] = useState(false);
    const [selectedChunk, setSelectedChunk] = useState<SourceType | null>(null);
    // 청크 상세(전체 원문) lazy 조회 상태
    const [sourceDetail, setSourceDetail] = useState<SourceDetail | null>(null);
    const [sourceDetailLoading, setSourceDetailLoading] = useState(false);
    const [sourceDetailError, setSourceDetailError] = useState<string | null>(null);
    // stale-response 가드: 연속 클릭 시 늦게 도착한 응답이 다른 청크 모달을 덮어쓰는 race를 차단한다.
    const sourceDetailRequestIdRef = useRef(0);
    const [showScrollButton, setShowScrollButton] = useState(false);
    const [leftPanelTab, setLeftPanelTab] = useState(0);
    const [expandedLogs, setExpandedLogs] = useState<Set<string>>(new Set());
    const [isDebugExpanded, setIsDebugExpanded] = useState<boolean>(false);
    const [messageAnimations, setMessageAnimations] = useState<Set<string>>(new Set());

    // 반응형 개발자 도구 상태
    const isMediumScreen = useMediaQuery('(max-width: 900px)'); // md 사이즈 이하

    const [showDevTools, setShowDevTools] = useState<boolean>(() => {
        if (typeof window !== 'undefined') {
            return window.innerWidth >= 1024; // lg 사이즈 이상에서만 기본 표시
        }
        return true;
    });

    // 반응형 처리: 화면이 좁아지면 개발자 도구 자동 숨기기
    useEffect(() => {
        if (isMediumScreen && showDevTools) {
            setShowDevTools(false);
        }
    }, [isMediumScreen, showDevTools]);

    const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
        const target = e.currentTarget;
        const isNearBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
        setShowScrollButton(!isNearBottom);
    }, []);

    // 스크롤 함수
    const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({
                behavior,
                block: 'end'
            });
        }
    }, []);

    // Effect for auto-scrolling on new messages
    useEffect(() => {
        if (!showScrollButton) {
            scrollToBottom();
        }
    }, [messages, showScrollButton, scrollToBottom]);

    // 메시지 애니메이션 및 스크롤 트리거
    useEffect(() => {
        const timeoutId = setTimeout(() => {
            // 모든 메시지에 애니메이션 적용 (초기 로드 시)
            const allMessageIds = new Set(messages.map(msg => msg.id));
            setMessageAnimations(allMessageIds);
        }, 100);

        return () => clearTimeout(timeoutId);
    }, [messages]);

    // 클립보드 복사
    const copyToClipboard = useCallback(async (text: string, successMessage: string = '복사되었습니다') => {
        try {
            await navigator.clipboard.writeText(text);
            showToast({
                type: 'success',
                message: successMessage,
            });
        } catch (err) {
            logger.error('복사 실패:', err);
            showToast({
                type: 'error',
                message: '복사에 실패했습니다',
            });
        }
    }, [showToast]);

    // 모달 핸들러: 청크 클릭 시 전체 원문을 lazy 조회한다(stale 응답 가드 포함).
    const handleChunkClick = useCallback(async (source: SourceType) => {
        // 이번 요청을 최신 요청으로 표시한다.
        const requestId = sourceDetailRequestIdRef.current + 1;
        sourceDetailRequestIdRef.current = requestId;

        setSelectedChunk(source);
        setSourceDetail(null);
        setSourceDetailError(null);
        setModalOpen(true);

        // 식별자가 없으면 상세 조회를 건너뛴다(모달은 content_preview로 표시 — graceful).
        if (!source.source_id || !source.document_id) {
            setSourceDetailLoading(false);
            return;
        }

        setSourceDetailLoading(true);
        try {
            const response = await chatAPI.getSourceDetail(source);
            // 가드: await 동안 더 최신 클릭이 발생했다면 이 응답은 버린다.
            if (sourceDetailRequestIdRef.current !== requestId) return;
            setSourceDetail(response.data);
        } catch (error) {
            if (sourceDetailRequestIdRef.current !== requestId) return;
            // 백엔드 미지원/오류 시: 에러를 기록하되 모달은 content_preview로 graceful fallback.
            logger.warn('소스 상세 조회 실패 (미리보기로 대체):', error);
            setSourceDetailError('전체 원문을 불러올 수 없어 미리보기를 표시합니다.');
        } finally {
            if (sourceDetailRequestIdRef.current === requestId) {
                setSourceDetailLoading(false);
            }
        }
    }, []);

    const handleCloseModal = useCallback(() => {
        // in-flight 요청 무효화: 닫은 뒤 늦게 도착한 응답이 상태를 되살리지 않게 한다.
        sourceDetailRequestIdRef.current += 1;
        setModalOpen(false);
        setSelectedChunk(null);
        setSourceDetail(null);
        setSourceDetailLoading(false);
        setSourceDetailError(null);
    }, []);

    const toggleLogExpansion = (logId: string) => {
        setExpandedLogs((prev) => {
            const newSet = new Set(prev);
            if (newSet.has(logId)) {
                newSet.delete(logId);
            } else {
                newSet.add(logId);
            }
            return newSet;
        });
    };

    return {
        messagesEndRef,
        scrollToBottom,
        modalOpen,
        selectedChunk,
        sourceDetail,
        sourceDetailLoading,
        sourceDetailError,
        handleChunkClick,
        handleCloseModal,
        leftPanelTab,
        setLeftPanelTab,
        expandedLogs,
        toggleLogExpansion,
        isDebugExpanded,
        setIsDebugExpanded,
        messageAnimations,
        showDevTools,
        setShowDevTools,
        copyToClipboard,
        showScrollButton,
        handleScroll,
    };
};
