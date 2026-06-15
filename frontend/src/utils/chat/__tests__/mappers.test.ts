import { describe, it, expect } from 'vitest';
import { pickFirstString, mapHistoryEntryToChatMessage } from '../mappers';
import { ChatHistoryEntry } from '../../../types';

describe('mappers', () => {
    describe('pickFirstString', () => {
        it('should return the first non-empty string', () => {
            expect(pickFirstString(null, undefined, '', 'first', 'second')).toBe('first');
        });

        it('should return undefined if no valid strings are found', () => {
            expect(pickFirstString(null, undefined, '')).toBeUndefined();
        });

        it('should ignore strings with only whitespace', () => {
            expect(pickFirstString('   ', 'valid')).toBe('valid');
        });
    });

    describe('mapHistoryEntryToChatMessage', () => {
        it('should map user role entry correctly', () => {
            const entry: ChatHistoryEntry = {
                id: '123',
                role: 'user',
                message: 'User Question',
                timestamp: '2024-01-01T10:00:00Z'
            };
            const result = mapHistoryEntryToChatMessage(entry, 0);
            expect(result.role).toBe('user');
            expect(result.content).toBe('User Question');
            expect(result.id).toBe('123');
        });

        it('should map assistant role entry correctly with multiple content candidates', () => {
            const entry: ChatHistoryEntry = {
                id: 456,
                role: 'assistant',
                answer: 'Assistant Answer',
                response: 'Fallback'
            };
            const result = mapHistoryEntryToChatMessage(entry, 1);
            expect(result.role).toBe('assistant');
            expect(result.content).toBe('Assistant Answer');
            expect(result.id).toBe('456');
        });

        it('should infer role based on index if role is missing', () => {
            // Even index -> user
            const entry1: ChatHistoryEntry = { message: 'Q' };
            const result1 = mapHistoryEntryToChatMessage(entry1, 0);
            expect(result1.role).toBe('user');

            // Odd index -> assistant
            const entry2: ChatHistoryEntry = { message: 'A' };
            const result2 = mapHistoryEntryToChatMessage(entry2, 1);
            expect(result2.role).toBe('assistant');
        });

        it('should include sources if present', () => {
            const sources = [{ id: 1, document: 'doc', relevance: 0.9, content_preview: 'preview' }];
            const entry: ChatHistoryEntry = {
                role: 'assistant',
                answer: 'Ans',
                sources: sources
            };
            const result = mapHistoryEntryToChatMessage(entry, 1);
            expect(result.sources).toEqual(sources);
        });

        it('should fallback ID to timestamp or generated string', () => {
            const entry: ChatHistoryEntry = { message: 'msg' };
            const result = mapHistoryEntryToChatMessage(entry, 2);
            expect(result.id).toBe('user-2');

            const entryTs: ChatHistoryEntry = { message: 'msg', timestamp: 'ts-id' };
            const resultTs = mapHistoryEntryToChatMessage(entryTs, 2);
            expect(resultTs.id).toBe('ts-id');
        });

        // #47: role 대신 type 필드로도 역할을 추론해야 함
        it('should infer role from entry.type when role is missing', () => {
            const entry: ChatHistoryEntry = { type: 'assistant', answer: 'Ans' };
            const result = mapHistoryEntryToChatMessage(entry, 0);
            expect(result.role).toBe('assistant');
        });

        // #47: 어시스턴트 메시지에 트레이스 메트릭이 매핑되어야 함
        it('should map trace metrics (processing_time/tokens_used/model_info) onto assistant message', () => {
            const entry: ChatHistoryEntry = {
                role: 'assistant',
                answer: 'Ans',
                processing_time: 1.23,
                tokens_used: 456,
                model_info: { provider: 'google', model: 'gemini-2.0' },
            };
            const result = mapHistoryEntryToChatMessage(entry, 1);
            expect(result.processing_time).toBe(1.23);
            expect(result.tokens_used).toBe(456);
            expect(result.model_info).toEqual({ provider: 'google', model: 'gemini-2.0' });
        });

        // #47: 트레이스 메트릭이 없으면 메시지에 해당 필드를 추가하지 않아야 함
        it('should not attach trace metrics when entry has none', () => {
            const entry: ChatHistoryEntry = { role: 'user', message: 'Q' };
            const result = mapHistoryEntryToChatMessage(entry, 0);
            expect(result.processing_time).toBeUndefined();
            expect(result.tokens_used).toBeUndefined();
            expect(result.model_info).toBeUndefined();
        });
    });
});
