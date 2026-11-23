import { describe, it, expect } from 'vitest';
import { formatSourcePreview, formatSourceRelevance, formatFullContent, formatModelConfigValue, formatTimestamp } from '../formatters';

describe('formatters', () => {
    it('keeps explicit score units and preserves legacy fractional, percentage and raw displays', () => {
        const base = { id: 1, document: 'doc', content_preview: 'quote' };
        expect(formatSourceRelevance({ ...base, relevance: 0.5, relevance_unit: 'percent' })?.text).toBe('0.5%');
        expect(formatSourceRelevance({ ...base, relevance: 0.8, relevance_unit: 'fraction' })?.text).toBe('80%');
        expect(formatSourceRelevance({ ...base, relevance: 0.8 })?.text).toBe('80%');
        expect(formatSourceRelevance({ ...base, relevance: 33.9 })?.text).toBe('33.9%');
        expect(formatSourceRelevance({ ...base, source_type: 'rag', relevance: 0.5, score: 0.5 })?.text).toBe('0.5%');
        expect(formatSourceRelevance({ ...base, relevance: 0.016, relevance_unit: 'raw' })).toEqual({ text: '0.016', percent: null });
        expect(formatSourceRelevance({ ...base, relevance: 0, relevance_unit: 'percent' })?.text).toBe('0%');
        expect(formatSourceRelevance({ ...base, relevance: 0, relevance_unit: 'unavailable' })).toBeNull();
        expect(formatSourceRelevance({ ...base, relevance: null })).toBeNull();
        expect(formatSourceRelevance(base)).toBeNull();
    });
    describe('formatSourcePreview', () => {
        it('should return default message if text is empty', () => {
            expect(formatSourcePreview(undefined)).toBe('미리보기를 제공하지 않는 문서입니다.');
            expect(formatSourcePreview('')).toBe('미리보기를 제공하지 않는 문서입니다.');
        });

        it('should truncate long text and add ellipsis', () => {
            const longText = 'a'.repeat(300);
            const result = formatSourcePreview(longText, 50);
            expect(result.length).toBeLessThanOrEqual(51); // 50 + …
            expect(result.endsWith('…')).toBe(true);
        });

        it('should clean up table artifacts for preview', () => {
            const input = '<table><tr><td>Data</td></tr></table>';
            const result = formatSourcePreview(input);
            expect(result).toContain('Data');
            expect(result).not.toContain('────────────────────');
            // It replaces '📊 테이블' with '📊'
            expect(result).toContain('📊');
        });

        it('should not truncate if text is shorter than limit', () => {
            const text = 'Short text';
            expect(formatSourcePreview(text, 100)).toBe('Short text');
        });
    });

    describe('formatFullContent', () => {
        it('should return error message if content is empty', () => {
            expect(formatFullContent(undefined)).toBe('내용을 불러올 수 없습니다.');
            expect(formatFullContent('')).toBe('내용을 불러올 수 없습니다.');
        });

        it('should format text and preserve distinct table structures', () => {
            const input = '<table><tr><td>Val</td></tr></table>';
            const result = formatFullContent(input);
            expect(result).toContain('📊 테이블');
            expect(result).toContain('────────────────────');
            expect(result).toContain('Val');
        });
    });

    describe('formatModelConfigValue', () => {
        it('should format null', () => {
            expect(formatModelConfigValue(null)).toBe('null');
        });

        it('should format primitives (string, number, boolean)', () => {
            expect(formatModelConfigValue('test')).toBe('test');
            expect(formatModelConfigValue(123)).toBe('123');
            expect(formatModelConfigValue(true)).toBe('true');
        });

        it('should format arrays', () => {
            expect(formatModelConfigValue([1, 'a', true])).toBe('1, a, true');
        });

        it('should format objects to JSON', () => {
            const obj = { key: 'value' };
            expect(formatModelConfigValue(obj)).toBe('{"key":"value"}');
        });
    });

    describe('formatTimestamp', () => {
        it('should format valid ISO string to time string', () => {
            // The output depends on the timezone of the test runner, but we expect it to contain :
            const result = formatTimestamp('2024-01-01T14:30:00Z');
            expect(result).toMatch(/\d{2}:\d{2}/);
        });

        it('should handle different time strings', () => {
            // Checks if it runs without error
            expect(formatTimestamp('2025-01-01T09:00:00')).toBeTruthy();
        });
    });
});
