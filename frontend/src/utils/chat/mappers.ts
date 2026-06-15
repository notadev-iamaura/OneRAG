import { ChatHistoryEntry, ChatMessage } from '../../types';

export const pickFirstString = (...values: Array<string | null | undefined>): string | undefined =>
    values.find((value): value is string => typeof value === 'string' && value.trim().length > 0);

export const mapHistoryEntryToChatMessage = (entry: ChatHistoryEntry, index: number): ChatMessage => {
    // 백엔드 히스토리는 role 또는 type 중 하나로 역할을 표현하므로 둘 다 후보로 본다.
    const roleCandidate = entry.role ?? entry.type;
    const role: 'user' | 'assistant' =
        roleCandidate === 'assistant' || roleCandidate === 'user'
            ? roleCandidate
            : index % 2 === 0
                ? 'user'
                : 'assistant';

    const roleSpecificCandidates = role === 'assistant'
        ? [
            entry.answer,
            entry.response,
            entry.assistant_message,
            entry.content,
            entry.message,
        ]
        : [
            entry.message,
            entry.question,
            entry.prompt,
            entry.user_message,
            entry.content,
        ];

    const content = pickFirstString(...roleSpecificCandidates, entry.response, entry.answer) || '';
    const timestamp = pickFirstString(entry.timestamp, entry.created_at, entry.updated_at) || new Date().toISOString();
    // idSource: entry.id가 number일 수도, string일 수도 있음
    const idSource = entry.id ?? entry.timestamp ?? `${role}-${index}`;
    const id = typeof idSource === 'string' ? idSource : idSource.toString();
    const sources = Array.isArray(entry.sources) && entry.sources.length > 0 ? entry.sources : undefined;

    const message: ChatMessage = {
        id,
        role,
        content,
        timestamp,
    };

    if (sources) {
        message.sources = sources;
    }

    // 백엔드 히스토리가 메시지별 트레이스 메트릭을 제공하면 메시지에 보존한다.
    // (RAG Trace 패널이 전역 로그가 아닌 메시지 값을 우선 표시하도록 — 방 전환 시 고정 버그 방지)
    if (typeof entry.processing_time === 'number') {
        message.processing_time = entry.processing_time;
    }
    if (typeof entry.tokens_used === 'number') {
        message.tokens_used = entry.tokens_used;
    }
    if (entry.model_info) {
        message.model_info = entry.model_info;
    }

    return message;
};
