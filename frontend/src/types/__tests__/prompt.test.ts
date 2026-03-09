/**
 * 프롬프트 타입 정의 테스트
 *
 * TDD 방식으로 먼저 테스트를 작성하고, 이후 타입 정의를 구현합니다.
 * types/prompt.ts에서 타입과 상수가 올바르게 export되는지 검증합니다.
 */
import { describe, it, expect } from 'vitest';
import type {
  Prompt,
  CreatePromptRequest,
  UpdatePromptRequest,
  PromptListResponse,
  PromptExport,
  PromptImportRequest,
} from '../prompt';
import {
  PROMPT_CATEGORIES,
  PROMPT_STYLES,
} from '../prompt';

describe('프롬프트 타입 정의 (types/prompt.ts)', () => {
  describe('Prompt 인터페이스', () => {
    it('프롬프트의 모든 필수 필드가 정의되어야 함', () => {
      const prompt: Prompt = {
        id: 'prompt-001',
        name: 'test-prompt',
        content: '테스트 프롬프트 내용입니다.',
        description: '테스트 설명',
        category: 'system',
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      };

      expect(prompt.id).toBe('prompt-001');
      expect(prompt.name).toBe('test-prompt');
      expect(prompt.content).toBe('테스트 프롬프트 내용입니다.');
      expect(prompt.description).toBe('테스트 설명');
      expect(prompt.category).toBe('system');
      expect(prompt.is_active).toBe(true);
      expect(prompt.created_at).toBe('2026-01-01T00:00:00Z');
      expect(prompt.updated_at).toBe('2026-01-01T00:00:00Z');
    });

    it('metadata는 선택적 필드여야 함', () => {
      const promptWithMeta: Prompt = {
        id: 'prompt-002',
        name: 'meta-prompt',
        content: '메타데이터 포함 프롬프트',
        description: '메타 설명',
        category: 'custom',
        is_active: false,
        metadata: { key: 'value', count: 42 },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      };

      expect(promptWithMeta.metadata).toEqual({ key: 'value', count: 42 });
    });

    it('category는 system, style, custom 중 하나여야 함', () => {
      const categories: Prompt['category'][] = ['system', 'style', 'custom'];
      expect(categories).toHaveLength(3);
      expect(categories).toContain('system');
      expect(categories).toContain('style');
      expect(categories).toContain('custom');
    });
  });

  describe('CreatePromptRequest 인터페이스', () => {
    it('생성 요청의 필수 필드가 정의되어야 함', () => {
      const request: CreatePromptRequest = {
        name: 'new-prompt',
        content: '새 프롬프트 내용입니다.',
        description: '새 프롬프트 설명',
        category: 'style',
      };

      expect(request.name).toBe('new-prompt');
      expect(request.content).toBe('새 프롬프트 내용입니다.');
      expect(request.description).toBe('새 프롬프트 설명');
      expect(request.category).toBe('style');
    });

    it('is_active와 metadata는 선택적 필드여야 함', () => {
      const request: CreatePromptRequest = {
        name: 'optional-fields',
        content: '선택적 필드 테스트',
        description: '테스트 설명',
        category: 'custom',
        is_active: true,
        metadata: { version: 1 },
      };

      expect(request.is_active).toBe(true);
      expect(request.metadata).toEqual({ version: 1 });
    });
  });

  describe('UpdatePromptRequest 인터페이스', () => {
    it('모든 필드가 선택적이어야 함', () => {
      // 빈 객체도 유효해야 함
      const emptyRequest: UpdatePromptRequest = {};
      expect(emptyRequest).toEqual({});
    });

    it('부분 업데이트가 가능해야 함', () => {
      const partialUpdate: UpdatePromptRequest = {
        name: 'updated-name',
        is_active: false,
      };

      expect(partialUpdate.name).toBe('updated-name');
      expect(partialUpdate.is_active).toBe(false);
      expect(partialUpdate.content).toBeUndefined();
    });
  });

  describe('PromptListResponse 인터페이스', () => {
    it('페이지네이션 정보와 프롬프트 배열을 포함해야 함', () => {
      const response: PromptListResponse = {
        prompts: [],
        total: 0,
        page: 1,
        page_size: 10,
      };

      expect(response.prompts).toEqual([]);
      expect(response.total).toBe(0);
      expect(response.page).toBe(1);
      expect(response.page_size).toBe(10);
    });
  });

  describe('PromptExport 인터페이스', () => {
    it('내보내기 데이터 구조가 올바라야 함', () => {
      const exportData: PromptExport = {
        prompts: [],
        exported_at: '2026-01-01T00:00:00Z',
        total: 0,
      };

      expect(exportData.prompts).toEqual([]);
      expect(exportData.exported_at).toBe('2026-01-01T00:00:00Z');
      expect(exportData.total).toBe(0);
    });
  });

  describe('PromptImportRequest 인터페이스', () => {
    it('가져오기 요청 구조가 올바라야 함', () => {
      const importData: PromptImportRequest = {
        prompts: [],
        exported_at: '2026-01-01T00:00:00Z',
        total: 0,
      };

      expect(importData.prompts).toEqual([]);
      expect(importData.exported_at).toBe('2026-01-01T00:00:00Z');
      expect(importData.total).toBe(0);
    });
  });

  describe('PROMPT_CATEGORIES 상수', () => {
    it('3개의 카테고리가 정의되어야 함', () => {
      expect(PROMPT_CATEGORIES).toHaveLength(3);
    });

    it('각 카테고리에 value, label, description이 있어야 함', () => {
      for (const category of PROMPT_CATEGORIES) {
        expect(category).toHaveProperty('value');
        expect(category).toHaveProperty('label');
        expect(category).toHaveProperty('description');
      }
    });

    it('system, style, custom 카테고리를 포함해야 함', () => {
      const values = PROMPT_CATEGORIES.map((c) => c.value);
      expect(values).toContain('system');
      expect(values).toContain('style');
      expect(values).toContain('custom');
    });

    it('한국어 label을 사용해야 함', () => {
      const labels = PROMPT_CATEGORIES.map((c) => c.label);
      expect(labels).toContain('시스템');
      expect(labels).toContain('스타일');
      expect(labels).toContain('커스텀');
    });
  });

  describe('PROMPT_STYLES 상수', () => {
    it('5개의 스타일이 정의되어야 함', () => {
      expect(PROMPT_STYLES).toHaveLength(5);
    });

    it('각 스타일에 value, label, description이 있어야 함', () => {
      for (const style of PROMPT_STYLES) {
        expect(style).toHaveProperty('value');
        expect(style).toHaveProperty('label');
        expect(style).toHaveProperty('description');
      }
    });

    it('system, detailed, concise, professional, educational 스타일을 포함해야 함', () => {
      const values = PROMPT_STYLES.map((s) => s.value);
      expect(values).toContain('system');
      expect(values).toContain('detailed');
      expect(values).toContain('concise');
      expect(values).toContain('professional');
      expect(values).toContain('educational');
    });
  });

  describe('하위 호환성 (promptService.ts re-export)', () => {
    it('promptService에서도 동일한 타입을 import할 수 있어야 함', async () => {
      // 동적 import로 promptService의 re-export 검증
      const promptServiceModule = await import('../../services/promptService');
      expect(promptServiceModule.PROMPT_CATEGORIES).toBeDefined();
      expect(promptServiceModule.PROMPT_STYLES).toBeDefined();
      expect(promptServiceModule.PROMPT_CATEGORIES).toEqual(PROMPT_CATEGORIES);
      expect(promptServiceModule.PROMPT_STYLES).toEqual(PROMPT_STYLES);
    });
  });
});
