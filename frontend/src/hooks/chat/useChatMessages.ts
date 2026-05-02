/**
 * 채팅 메시지 상태 관리 훅
 *
 * 메시지 전송, 상태 관리, 스트리밍/REST 분기 처리를 담당합니다.
 * Feature Flag(chatbot.streaming)에 따라 WebSocket 스트리밍 또는 REST API를 사용합니다.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { ChatMessage, ApiLog, ToastMessage, SessionInfo } from '../../types';
import { StreamingMessage } from '../../types/chatStreaming';
import { chatAPI } from '../../services/api';
import { logger } from '../../utils/logger';
import { useIsFeatureEnabled } from '../../core/useFeature';
import { useChatStreaming } from './useChatStreaming';

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
    handleSend: () => Promise<void>;
    handleStop: () => void;
    // 스트리밍 관련 상태
    isStreaming: boolean;
    streamingMessage: StreamingMessage | null;
    isStreamingEnabled: boolean;
    isStreamingConnected: boolean;
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
            id: (Date.now() + 1).toString(),
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
            id: Date.now().toString(),
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
                id: (Date.now() + 1).toString(),
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
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: response.data.answer,
                timestamp: new Date().toISOString(),
                sources: response.data.sources,
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
                id: (Date.now() + 2).toString(),
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
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: '죄송합니다. 오류가 발생했습니다. 다시 시도해주세요.',
                timestamp: new Date().toISOString(),
            };

            setMessages((prev) => [...prev, errorMsg]);
        }
    };

    /**
     * 메시지 전송 (스트리밍/REST 분기)
     */
    const handleSend = async () => {
        if (!input.trim() || loading) return;

        const userMessage: ChatMessage = {
            id: Date.now().toString(),
            role: 'user',
            content: input,
            timestamp: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, userMessage]);
        const messageContent = input;
        setInput('');
        setLoading(true);

        // 스트리밍 사용 가능 여부 확인
        const canUseStreaming = isStreamingEnabled &&
            streaming.isConnected &&
            !sessionId.startsWith('fallback-');

        if (canUseStreaming) {
            // WebSocket 스트리밍 사용
            isStreamingSendActiveRef.current = true;
            logger.log('📡 WebSocket 스트리밍으로 메시지 전송');

            // API 로그 (WebSocket)
            const wsRequestLog: ApiLog = {
                id: Date.now().toString(),
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
                // 전송 실패 시 스트리밍 상태 리셋 후 REST API로 폴백
                isStreamingSendActiveRef.current = false;
                logger.warn('스트리밍 전송 실패, REST API로 폴백');
                await sendViaRestAPI(messageContent);
                setLoading(false);
            }
            // 스트리밍 성공 시 loading은 콜백에서 처리됨
        } else {
            // REST API 사용
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
        if (isStreamingEnabled) {
            streaming.stop();
            // stop()은 이벤트 리스너를 보존하므로, 다음 메시지 전송 시 재연결 후 스트리밍 정상 동작
        }
        logger.log('⏹️ 전송 중단됨');
    }, [isStreamingEnabled, streaming]);

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
    };
};
