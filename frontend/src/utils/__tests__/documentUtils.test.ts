/**
 * 문서 유틸리티 함수 테스트
 *
 * sortDocuments, formatFileSize 순수 함수를 검증합니다.
 * getFileIcon, getFileTypeBadge는 DocumentsTab.tsx에 존재하지 않으므로 스킵합니다.
 */
import { describe, it, expect } from 'vitest';
import type { Document } from '../../types';
import { sortDocuments, formatFileSize } from '../documentUtils';

// 테스트용 문서 데이터 팩토리
const createDoc = (overrides: Partial<Document> = {}): Document => ({
  id: 'doc-1',
  filename: 'test.pdf',
  originalName: 'test.pdf',
  size: 1024,
  mimeType: 'application/pdf',
  uploadedAt: '2026-01-15T10:00:00Z',
  status: 'completed',
  ...overrides,
});

describe('documentUtils', () => {
  // ============================================================
  // sortDocuments 테스트 (8개: 4 필드 × asc/desc)
  // ============================================================
  describe('sortDocuments', () => {
    const docA = createDoc({
      id: 'a',
      originalName: 'alpha.pdf',
      filename: 'alpha.pdf',
      size: 100,
      uploadedAt: '2026-01-01T00:00:00Z',
    });
    const docB = createDoc({
      id: 'b',
      originalName: 'beta.docx',
      filename: 'beta.docx',
      size: 500,
      uploadedAt: '2026-02-01T00:00:00Z',
    });
    const docC = createDoc({
      id: 'c',
      originalName: 'charlie.xlsx',
      filename: 'charlie.xlsx',
      size: 300,
      uploadedAt: '2026-03-01T00:00:00Z',
    });
    const docs = [docB, docC, docA]; // 의도적으로 순서 섞기

    // --- filename 정렬 ---
    it('filename 기준 오름차순 정렬 (asc)', () => {
      const result = sortDocuments(docs, 'filename', 'asc');
      expect(result.map((d) => d.id)).toEqual(['a', 'b', 'c']);
    });

    it('filename 기준 내림차순 정렬 (desc)', () => {
      const result = sortDocuments(docs, 'filename', 'desc');
      expect(result.map((d) => d.id)).toEqual(['c', 'b', 'a']);
    });

    // --- size 정렬 ---
    it('size 기준 오름차순 정렬 (asc)', () => {
      const result = sortDocuments(docs, 'size', 'asc');
      expect(result.map((d) => d.id)).toEqual(['a', 'c', 'b']);
    });

    it('size 기준 내림차순 정렬 (desc)', () => {
      const result = sortDocuments(docs, 'size', 'desc');
      expect(result.map((d) => d.id)).toEqual(['b', 'c', 'a']);
    });

    // --- uploadedAt 정렬 ---
    it('uploadedAt 기준 오름차순 정렬 (asc)', () => {
      const result = sortDocuments(docs, 'uploadedAt', 'asc');
      expect(result.map((d) => d.id)).toEqual(['a', 'b', 'c']);
    });

    it('uploadedAt 기준 내림차순 정렬 (desc)', () => {
      const result = sortDocuments(docs, 'uploadedAt', 'desc');
      expect(result.map((d) => d.id)).toEqual(['c', 'b', 'a']);
    });

    // --- type(확장자) 정렬 ---
    it('type(확장자) 기준 오름차순 정렬 (asc)', () => {
      const result = sortDocuments(docs, 'type', 'asc');
      // docx < pdf < xlsx (알파벳 순)
      expect(result.map((d) => d.id)).toEqual(['b', 'a', 'c']);
    });

    it('type(확장자) 기준 내림차순 정렬 (desc)', () => {
      const result = sortDocuments(docs, 'type', 'desc');
      // xlsx > pdf > docx (역순)
      expect(result.map((d) => d.id)).toEqual(['c', 'a', 'b']);
    });

    // --- 엣지 케이스 ---
    it('빈 배열 입력 시 빈 배열 반환', () => {
      const result = sortDocuments([], 'filename', 'asc');
      expect(result).toEqual([]);
    });

    it('원본 배열을 변이시키지 않음 (불변성)', () => {
      const original = [docB, docC, docA];
      const originalCopy = [...original];
      sortDocuments(original, 'filename', 'asc');
      expect(original.map((d) => d.id)).toEqual(originalCopy.map((d) => d.id));
    });

    it('originalName이 없을 때 filename으로 폴백하여 정렬', () => {
      const docNoOriginal = createDoc({
        id: 'x',
        originalName: '',
        filename: 'zulu.txt',
        size: 50,
      });
      const result = sortDocuments([docA, docNoOriginal], 'filename', 'asc');
      // alpha.pdf < zulu.txt
      expect(result.map((d) => d.id)).toEqual(['a', 'x']);
    });
  });

  // ============================================================
  // formatFileSize 테스트 (4개)
  // ============================================================
  describe('formatFileSize', () => {
    it('0 바이트를 "0 Bytes"로 포맷', () => {
      expect(formatFileSize(0)).toBe('0 Bytes');
    });

    it('512 바이트를 "512 Bytes"로 포맷', () => {
      expect(formatFileSize(512)).toBe('512 Bytes');
    });

    it('1536 바이트(1.5KB)를 "1.5 KB"로 포맷', () => {
      expect(formatFileSize(1536)).toBe('1.5 KB');
    });

    it('2,411,724 바이트(약 2.3MB)를 "2.3 MB"로 포맷', () => {
      // 2.3 * 1024 * 1024 = 2,411,724.8
      expect(formatFileSize(2411725)).toBe('2.3 MB');
    });
  });
});
