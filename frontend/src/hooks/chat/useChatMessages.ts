/**
 * 채팅 메시지 상태 관리 훅
 *
 * 메시지 전송, 상태 관리, 스트리밍/REST 분기 처리를 담당합니다.
 * Feature Flag(chatbot.streaming)에 따라 WebSocket 스트리밍 또는 REST API를 사용합니다.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { ChatMessage, ApiLog, ToastMessage, SessionInfo, Source } from '../../types';
import {
    StreamingMessage,
    RagProgressState,
    RagProgressPhase,
} from '../../types/chatStreaming';
import { chatAPI } from '../../services/api';
import { logger } from '../../utils/logger';
import { createClientId } from '../../utils/clientId';
import { useIsFeatureEnabled } from '../../core/useFeature';
import { useChatStreaming } from './useChatStreaming';

// SSE 타이프라이터 설정: 백엔드가 청크를 한꺼번에 flush해도 점진적으로 보이도록
// 수신 버퍼(pendingContent)와 표시 버퍼(displayedContent)를 분리해 일정 간격으로 흘려보낸다.
const SSE_TYPEWRITER_INTERVAL_MS = 20;
const SSE_TYPEWRITER_MIN_CHARS = 4;
const SSE_TYPEWRITER_MAX_CHARS = 28;

/** RAG 진행 단계별 한국어 라벨(범용 처리 — i18n 카탈로그 미사용). */
const RAG_PROGRESS_LABELS: Record<RagProgressPhase, string> = {
    idle: '',
    searching: '문서를 검색하고 있습니다...',
    retrieval_done: '검색을 완료하고 답변을 준비합니다...',
    generating: '답변을 생성하고 있습니다...',
    completed: '완료',
    error: '오류가 발생했습니다.',
};

/** phase에 맞는 라벨을 채워 RagProgressState를 만든다. */
const withProgressLabel = (state: Omit<RagProgressState, 'label' | 'updatedAt'>): RagProgressState => ({
    ...state,
    label: RAG_PROGRESS_LABELS[state.phase],
    updatedAt: new Date().toISOString(),
});

const buildInitialRagProgress = (): RagProgressState => withProgressLabel({ phase: 'idle' });

interface UseChatMessagesProps {
    sessionId: string;
    initialMessages: ChatMessage[];
    synchronizeSessionId: (newSessionId: string, context?: string) => boolean;
    refreshSessionInfo?: (targetSessionId?: string) => Promise<void>;
    setSessionInfo?: React.Dispatch<React.SetStateAction<SessionInfo | null>>;
    showToast: (message: Omit<ToastMessage, 'id'>) => void;
    setApiLogs: React.Dispatch<React.SetStateAction<ApiLog[]>>;
}

interface UseChatMessagesReturn {
    messages: ChatMessage[];
    setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
    input: string;
    setInput: React.Dispatch<React.SetStateAction<string>>;
    loading: boolean;
    setLoading: React.Dispatch<React.SetStateAction<boolean>>;
    // 선택적 인자로 보낼 메시지를 직접 지정할 수 있다(임베드 host send 등).
    // 미지정 시 기존처럼 input 상태값을 전송한다.
    handleSend: (directMessage?: string) => Promise<void>;
    handleStop: () => void;
    // 스트리밍 관련 상태
    isStreaming: boolean;
    streamingMessage: StreamingMessage | null;
    isStreamingEnabled: boolean;
    isStreamingConnected: boolean;
    // SSE 스트리밍 상태
    isSseStreaming: boolean;
    ragProgress: RagProgressState;
}

export const useChatMessages = ({
    sessionId,
    initialMessages,
    synchronizeSessionId,
    refreshSessionInfo,
    setSessionInfo,
    showToast,
    setApiLogs
}: UseChatMessagesProps): UseChatMessagesReturn => {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    // 스트리밍 전송 활성 상태 추적 (백그라운드 연결 에러 vs 실제 전송 에러 구분)
    const isStreamingSendActiveRef = useRef(false);

    // SSE 스트리밍 상태/진행단계
    const [isSseStreaming, setIsSseStreaming] = useState(false);
    const [ragProgress, setRagProgress] = useState<RagProgressState>(buildInitialRagProgress);

    // SSE 중단 제어: abort 시 REST 재생성을 막기 위한 플래그/컨트롤러/플레이스홀더 ID 추적.
    const sseAbortControllerRef = useRef<AbortController | null>(null);
    const sseAbortedRef = useRef(false);
    const ssePlaceholderIdRef = useRef<string | null>(null);

    // Feature Flag 체크
    const isStreamingEnabled = useIsFeatureEnabled('chatbot', 'streaming');

    /**
     * 스트리밍 메시지 완료 콜백
     */
    const handleStreamingComplete = useCallback((message: ChatMessage) => {
        isStreamingSendActiveRef.current = false;
        setMessages((prev) => [...prev, message]);
        setLoading(false);

        // 세션 정보 갱신 (refreshSessionInfo가 제공된 경우에만)
        if (refreshSessionInfo) {
            refreshSessionInfo(sessionId).catch((error) => {
                logger.warn('세션 정보 갱신 실패:', error);
            });
        }

        logger.log('✅ 스트리밍 메시지 완료:', message.id);
    }, [sessionId, refreshSessionInfo]);

    /**
     * 스트리밍 에러 콜백
     */
    const handleStreamingError = useCallback((error: string) => {
        // 백그라운드 WebSocket 연결 실패는 사용자에게 표시하지 않음
        // (스트리밍 전송 중이 아닌 경우 = 백그라운드 재연결 실패)
        if (!isStreamingSendActiveRef.current) {
            logger.warn('백그라운드 스트리밍 연결 에러 (무시):', error);
            return;
        }

        isStreamingSendActiveRef.current = false;
        setLoading(false);
        showToast({ type: 'error', message: error });

        // 에러 메시지 추가
        const errorMsg: ChatMessage = {
            id: createClientId('msg-error'),
            role: 'assistant',
            content: '죄송합니다. 오류가 발생했습니다. 다시 시도해주세요.',
            timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorMsg]);

        logger.error('❌ 스트리밍 에러:', error);
    }, [showToast]);

    // 스트리밍 훅
    const streaming = useChatStreaming({
        sessionId,
        onMessageComplete: handleStreamingComplete,
        onError: handleStreamingError,
    });

    // 초기 메시지 로드 시 동기화
    useEffect(() => {
        if (initialMessages && initialMessages.length > 0) {
            setMessages(initialMessages);
        } else if (initialMessages && initialMessages.length === 0) {
            // 새 세션 등이면 초기화
            setMessages([]);
        }
    }, [initialMessages]);

    // 스트리밍 연결 관리
    useEffect(() => {
        // 스트리밍 활성화 + 유효한 세션 ID + fallback 세션이 아닐 때만 연결
        if (isStreamingEnabled && sessionId && !sessionId.startsWith('fallback-')) {
            streaming.connect().catch((error) => {
                logger.warn('스트리밍 연결 실패, REST API로 폴백:', error);
            });
        }

        // 클린업: 컴포넌트 언마운트 시 연결 해제
        return () => {
            if (isStreamingEnabled) {
                streaming.disconnect();
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isStreamingEnabled, sessionId]);

    /**
     * REST API로 메시지 전송 (기존 로직)
     */
    const sendViaRestAPI = async (messageContent: string) => {
        // API 요청 로그
        const requestLog: ApiLog = {
            id: createClientId('api-request'),
            timestamp: new Date().toISOString(),
            type: 'request',
            method: 'POST',
            endpoint: '/api/chat',
            data: {
                message: messageContent,
                session_id: sessionId,
            },
        };
        setApiLogs((prev) => [...prev, requestLog]);

        const startTime = Date.now();

        try {
            const response = await chatAPI.sendMessage(messageContent, sessionId);

            // 세션 ID 동기화
            const backendSessionId = response.data.session_id;
            synchronizeSessionId(backendSessionId, '메시지 응답 불일치 감지');

            // API 응답 로그
            const responseLog: ApiLog = {
                id: createClientId('api-response'),
                timestamp: new Date().toISOString(),
                type: 'response',
                method: 'POST',
                endpoint: '/api/chat',
                data: response.data,
                status: 200,
                duration: Date.now() - startTime,
            };
            setApiLogs((prev) => [...prev, responseLog]);

            const assistantMessage: ChatMessage = {
                id: createClientId('msg-assistant'),
                role: 'assistant',
                content: response.data.answer,
                timestamp: new Date().toISOString(),
                sources: response.data.sources,
                // 라이브 REST 응답의 트레이스 메트릭을 메시지에 보존(방 전환 시 메트릭 고정 버그 방지).
                processing_time: response.data.processing_time,
                tokens_used: response.data.tokens_used,
                model_info: response.data.model_info,
            };

            setMessages((prev) => [...prev, assistantMessage]);

            // 세션 정보 갱신
            const currentSessionId = backendSessionId || sessionId;
            // 세션 정보 갱신 (refreshSessionInfo가 제공된 경우에만)
            if (refreshSessionInfo) {
                try {
                    await refreshSessionInfo(currentSessionId);
                } catch (sessionInfoError) {
                    logger.warn('세션 정보 갱신 실패 (Fallback 적용):', sessionInfoError);

                    // 백엔드에서 세션 정보를 가져올 수 없으면 기존 방식 사용 (Fallback logic)
                    if (setSessionInfo) {
                        const fallbackSessionInfo: SessionInfo = {
                            session_id: currentSessionId,
                            messageCount: messages.length + 2,
                            tokensUsed: response.data.tokens_used || 0,
                            processingTime: response.data.processing_time || 0,
                            modelInfo: response.data.model_info || {
                                provider: 'unknown',
                                model: 'unknown',
                                generation_time: 0,
                                model_config: {}
                            },
                            timestamp: new Date().toISOString()
                        };
                        setSessionInfo(fallbackSessionInfo);
                    }
                }
            }

        } catch (error: unknown) {
            logger.error('메시지 전송 오류:', error);
            const apiError = error as { response?: { data?: { message?: string }; status?: number }; message?: string };

            // API 에러 로그
            const errorLog: ApiLog = {
                id: createClientId('api-error'),
                timestamp: new Date().toISOString(),
                type: 'response',
                method: 'POST',
                endpoint: '/api/chat',
                data: apiError?.response?.data || { error: apiError?.message || 'Unknown error' },
                status: apiError?.response?.status || 0,
                duration: Date.now() - startTime,
            };
            setApiLogs((prev) => [...prev, errorLog]);

            const errorMessage = apiError?.response?.data?.message || '메시지 전송에 실패했습니다.';

            showToast({
                type: 'error',
                message: errorMessage,
            });

            // 에러 메시지(UI용) 추가
            const errorMsg: ChatMessage = {
                id: createClientId('msg-error'),
                role: 'assistant',
                content: '죄송합니다. 오류가 발생했습니다. 다시 시도해주세요.',
                timestamp: new Date().toISOString(),
            };

            setMessages((prev) => [...prev, errorMsg]);
        }
    };

    /**
     * SSE(POST /chat/stream)로 메시지 전송.
     *
     * - placeholder 어시스턴트 메시지를 먼저 삽입하고, chunk가 도착할 때마다 내용을 점진적으로 채운다.
     * - 수신 버퍼(pendingContent)와 표시 버퍼(displayedContent)를 분리해 타이프라이터처럼 흘려보낸다.
     * - metadata→retrieval_done, 첫 chunk→generating, done→completed로 RagProgress를 전이한다.
     * - 사용자가 중단(abort)하면 이후 도착하는 chunk/done은 무시하고 REST 폴백을 하지 않는다.
     *
     * @returns 성공 여부(false면 호출부에서 REST 폴백을 시도한다. 단, abort된 경우는 폴백하지 않는다)
     */
    const sendViaSSE = async (messageContent: string): Promise<boolean> => {
        const placeholderId = createClientId('msg-sse');
        ssePlaceholderIdRef.current = placeholderId;
        sseAbortedRef.current = false;

        const abortController = new AbortController();
        sseAbortControllerRef.current = abortController;

        // placeholder 어시스턴트 메시지 삽입(빈 내용 → chunk로 채워짐)
        const placeholder: ChatMessage = {
            id: placeholderId,
            role: 'assistant',
            content: '',
            timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, placeholder]);
        setIsSseStreaming(true);
        setRagProgress(withProgressLabel({ phase: 'searching' }));

        // 누적 상태(전체 수신 내용/소스/트레이스)
        const accumulated: {
            content: string;
            sources?: Source[];
            processingTime?: number;
            tokensUsed?: number;
        } = { content: '' };

        // 표시/수신 버퍼와 타이프라이터 타이머
        let displayedContent = '';
        let pendingContent = '';
        let doneReceived = false;
        let typewriterTimer: ReturnType<typeof setTimeout> | null = null;

        // visualDrain: 표시 버퍼가 모두 비워질 때까지 기다렸다가 sources를 부착하기 위한 약속.
        let visualDrainResolved = false;
        let resolveVisualDrain: (() => void) | null = null;
        const visualDrainPromise = new Promise<void>((resolve) => {
            resolveVisualDrain = resolve;
        });
        const resolveVisualDrainOnce = () => {
            if (!visualDrainResolved) {
                visualDrainResolved = true;
                resolveVisualDrain?.();
            }
        };

        // placeholder 메시지의 표시 내용을 갱신한다(중단된 경우는 갱신하지 않음).
        const applyDisplayedContent = () => {
            if (sseAbortedRef.current) return;
            setMessages((prev) => prev.map((m) => (m.id === placeholderId ? { ...m, content: displayedContent } : m)));
        };

        // 표시 버퍼에서 적응형 길이만큼 잘라 흘려보낸다.
        const drainTypewriterSlice = () => {
            if (sseAbortedRef.current) {
                pendingContent = '';
                resolveVisualDrainOnce();
                return;
            }
            if (pendingContent.length === 0) {
                // 모든 청크를 수신·표시 완료했다면 visualDrain 해제
                if (doneReceived) {
                    resolveVisualDrainOnce();
                }
                return;
            }
            // pending이 많을수록 한 번에 더 많이 흘려보내 지연을 막는다(MIN~MAX 사이).
            const sliceLength = Math.min(
                pendingContent.length,
                Math.max(SSE_TYPEWRITER_MIN_CHARS, Math.min(SSE_TYPEWRITER_MAX_CHARS, Math.ceil(pendingContent.length / 8)))
            );
            displayedContent += pendingContent.slice(0, sliceLength);
            pendingContent = pendingContent.slice(sliceLength);
            applyDisplayedContent();

            if (pendingContent.length === 0 && doneReceived) {
                resolveVisualDrainOnce();
            }
        };

        // 일정 간격으로 표시 버퍼를 흘려보내는 루프
        const scheduleTypewriter = () => {
            if (typewriterTimer || sseAbortedRef.current || pendingContent.length === 0) {
                return;
            }
            typewriterTimer = setTimeout(() => {
                typewriterTimer = null;
                drainTypewriterSlice();
                scheduleTypewriter();
            }, SSE_TYPEWRITER_INTERVAL_MS);
        };

        try {
            await chatAPI.streamMessage(messageContent, sessionId, {
                signal: abortController.signal,
                onEvent: (event) => {
                    // metadata: 검색 결과 수신 → retrieval_done 단계로 전이
                    if (sseAbortedRef.current) return;
                    if (event.event === 'metadata') {
                        setRagProgress(withProgressLabel({
                            phase: 'retrieval_done',
                            searchResults: event.search_results,
                            rerankingApplied: event.reranking_applied,
                        }));
                    }
                },
                onChunk: (event) => {
                    if (sseAbortedRef.current) return;
                    const isFirstChunk = accumulated.content.length === 0;
                    accumulated.content += event.data;
                    pendingContent += event.data;
                    if (isFirstChunk) {
                        // 첫 토큰 수신 시 생성 단계로 전이
                        setRagProgress((prev) => withProgressLabel({
                            phase: 'generating',
                            searchResults: prev.searchResults,
                            rerankingApplied: prev.rerankingApplied,
                        }));
                        // 첫 슬라이스를 즉시 흘려보내 응답 시작을 빠르게 노출
                        drainTypewriterSlice();
                    }
                    scheduleTypewriter();
                },
                onDone: (event) => {
                    if (sseAbortedRef.current) return;
                    doneReceived = true;
                    accumulated.sources = event.sources;
                    accumulated.processingTime = event.processing_time;
                    accumulated.tokensUsed = event.tokens_used;
                    // 남은 표시 버퍼가 있으면 타이프라이터가 마저 흘려보내고, 없으면 즉시 해제
                    if (pendingContent.length === 0) {
                        resolveVisualDrainOnce();
                    } else {
                        scheduleTypewriter();
                    }
                    // 세션 ID 동기화
                    if (event.session_id) {
                        synchronizeSessionId(event.session_id, 'SSE done 이벤트 세션 동기화');
                    }
                },
                onError: (event) => {
                    if (sseAbortedRef.current) return;
                    logger.error('SSE 스트리밍 에러:', event);
                    setRagProgress(withProgressLabel({ phase: 'error' }));
                    throw new Error(event.message || 'SSE 스트리밍 오류');
                },
            });

            // 중단된 경우: placeholder 정리는 handleStop에서 처리, REST 폴백 금지
            if (sseAbortedRef.current) {
                return true;
            }

            // 표시 버퍼가 모두 비워질 때까지 대기 후 sources/트레이스 부착(출처 카드 조기 노출 방지)
            await visualDrainPromise;
            if (typewriterTimer) {
                clearTimeout(typewriterTimer);
                typewriterTimer = null;
            }

            // 최종 메시지에 전체 내용 + 소스 + 트레이스 부착
            setMessages((prev) => prev.map((m) => (m.id === placeholderId ? {
                ...m,
                content: accumulated.content,
                sources: accumulated.sources,
                processing_time: accumulated.processingTime,
                tokens_used: accumulated.tokensUsed,
            } : m)));
            setRagProgress(withProgressLabel({ phase: 'completed' }));

            // 세션 정보 갱신
            if (refreshSessionInfo) {
                refreshSessionInfo(sessionId).catch((error) => {
                    logger.warn('세션 정보 갱신 실패(SSE):', error);
                });
            }
            return true;
        } catch (error) {
            if (typewriterTimer) {
                clearTimeout(typewriterTimer);
                typewriterTimer = null;
            }
            // 중단으로 인한 예외(AbortError)면 폴백하지 않는다.
            if (sseAbortedRef.current) {
                return true;
            }
            logger.warn('SSE 전송 실패, REST 폴백 예정:', error);
            // 실패 시 placeholder 제거 후 false 반환(호출부가 REST 폴백)
            setMessages((prev) => prev.filter((m) => m.id !== placeholderId));
            setRagProgress(withProgressLabel({ phase: 'error' }));
            return false;
        } finally {
            setIsSseStreaming(false);
            sseAbortControllerRef.current = null;
            if (ssePlaceholderIdRef.current === placeholderId) {
                ssePlaceholderIdRef.current = null;
            }
        }
    };

    /**
     * 메시지 전송 (스트리밍/REST 분기)
     */
    const handleSend = async (directMessage?: string) => {
        // 임베드 host가 메시지를 직접 전달한 경우(directMessage) 그것을 사용하고,
        // 아니면 기존처럼 입력창(input) 상태값을 사용한다.
        const rawMessage = directMessage ?? input;
        const messageContent = rawMessage.trim();
        if (!messageContent || loading) return;

        const userMessage: ChatMessage = {
            id: createClientId('msg-user'),
            role: 'user',
            content: messageContent,
            timestamp: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, userMessage]);
        // 입력창에서 보낸 경우에만 입력창을 비운다(host send는 입력창과 무관).
        setInput('');
        setLoading(true);

        // 폴백 체인: WebSocket(연결됨) → SSE(스트리밍 활성·WS 미연결) → REST(비스트리밍 통짜).
        const isFallbackSession = sessionId.startsWith('fallback-');
        const canUseWebSocket = isStreamingEnabled && streaming.isConnected && !isFallbackSession;
        // SSE는 스트리밍이 켜져 있으나 WS가 연결되지 않은 경우의 중간 티어.
        const canUseSSE = isStreamingEnabled && !streaming.isConnected && !isFallbackSession;

        // SSE/REST 폴백 공통: SSE 실패 시 REST로, 단 abort된 경우는 폴백 금지.
        const runSseThenRestFallback = async () => {
            const sseOk = await sendViaSSE(messageContent);
            // 사용자가 중단했다면 통짜 답변 재생성을 막는다.
            if (sseAbortedRef.current) {
                return;
            }
            if (!sseOk) {
                logger.warn('SSE 폴백 → REST API로 메시지 전송');
                await sendViaRestAPI(messageContent);
            }
        };

        if (canUseWebSocket) {
            // WebSocket 스트리밍 사용
            isStreamingSendActiveRef.current = true;
            logger.log('📡 WebSocket 스트리밍으로 메시지 전송');

            // API 로그 (WebSocket)
            const wsRequestLog: ApiLog = {
                id: createClientId('api-ws-request'),
                timestamp: new Date().toISOString(),
                type: 'request',
                method: 'WS',
                endpoint: '/chat-ws',
                data: {
                    message: messageContent,
                    session_id: sessionId,
                },
            };
            setApiLogs((prev) => [...prev, wsRequestLog]);

            const messageId = streaming.sendStreamingMessage(messageContent);

            if (!messageId) {
                // WS 전송 실패 시 SSE → REST 폴백 체인으로 진행
                isStreamingSendActiveRef.current = false;
                logger.warn('WebSocket 전송 실패, SSE/REST로 폴백');
                await runSseThenRestFallback();
                setLoading(false);
            }
            // 스트리밍 성공 시 loading은 콜백에서 처리됨
        } else if (canUseSSE) {
            // SSE 중간 티어 (WS 미연결 시 점진 렌더)
            logger.log('📨 SSE 스트리밍으로 메시지 전송');
            await runSseThenRestFallback();
            setLoading(false);
        } else {
            // REST API 사용 (비스트리밍 통짜)
            logger.log('🔄 REST API로 메시지 전송');
            await sendViaRestAPI(messageContent);
            setLoading(false);
        }
    };

    /**
     * 전송 중단
     */
    const handleStop = useCallback(() => {
        setLoading(false);

        // SSE 중단: 플래그 선설정 후 abort → 이후 도착하는 chunk/done 무시 + REST 폴백 금지.
        if (isSseStreaming || sseAbortControllerRef.current) {
            sseAbortedRef.current = true;
            sseAbortControllerRef.current?.abort();
            // 빈 placeholder 메시지는 제거(중단 시 통짜 재생성 방지 + 빈 말풍선 제거)
            const placeholderId = ssePlaceholderIdRef.current;
            if (placeholderId) {
                setMessages((prev) => prev.filter((m) => !(m.id === placeholderId && m.content.length === 0)));
            }
            setIsSseStreaming(false);
            setRagProgress(buildInitialRagProgress());
        }

        // WS 중단: stop()은 Core 훅 반환에 없으므로 disconnect()로 안전하게 정지(선재 버그 동시 수정).
        if (isStreamingEnabled) {
            streaming.disconnect();
        }
        logger.log('⏹️ 전송 중단됨');
    }, [isStreamingEnabled, isSseStreaming, streaming]);

    return {
        messages,
        setMessages,
        input,
        setInput,
        loading,
        setLoading,
        handleSend,
        handleStop,
        // 스트리밍 관련 상태
        isStreaming: streaming.streamingState === 'streaming',
        streamingMessage: streaming.streamingMessage,
        isStreamingEnabled,
        isStreamingConnected: streaming.isConnected,
        // SSE 스트리밍 상태
        isSseStreaming,
        ragProgress,
    };
};
