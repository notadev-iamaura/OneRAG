/**
 * Performance optimization utilities for MVP
 * 성능 최적화 유틸리티 (MVP용 간단한 구현)
 */

/**
 * 이미지 지연 로딩을 위한 Intersection Observer
 */
export const lazyLoadImages = () => {
  if ('IntersectionObserver' in window) {
    const imageObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const img = entry.target as HTMLImageElement;
          img.src = img.dataset.src || '';
          observer.unobserve(img);
        }
      });
    });

    document.querySelectorAll('img[data-src]').forEach(img => {
      imageObserver.observe(img);
    });
  }
};

/**
 * 컴포넌트 마운트 시 지연 실행
 * @param callback 실행할 함수
 * @param delay 지연 시간 (기본값: 0)
 */
export const deferExecution = (callback: () => void, delay: number = 0) => {
  if (window.requestIdleCallback) {
    window.requestIdleCallback(() => {
      setTimeout(callback, delay);
    });
  } else {
    setTimeout(callback, delay);
  }
};

/**
 * 메모리 누수 방지를 위한 이벤트 리스너 관리
 */
export class EventManager {
  private listeners: Array<{
    element: Element | Window;
    event: string;
    handler: EventListener;
  }> = [];

  addEventListener(
    element: Element | Window,
    event: string,
    handler: EventListener
  ) {
    element.addEventListener(event, handler);
    this.listeners.push({ element, event, handler });
  }

  removeAllListeners() {
    this.listeners.forEach(({ element, event, handler }) => {
      element.removeEventListener(event, handler);
    });
    this.listeners = [];
  }
}

/**
 * 간단한 메모이제이션 함수
 * @param fn 메모이제이션할 함수
 * @param maxSize 캐시 최대 크기
 */
export const memoize = <T extends (...args: unknown[]) => unknown>(
  fn: T,
  maxSize: number = 10
): T => {
  const cache = new Map<string, ReturnType<T>>();
  
  return ((...args: Parameters<T>) => {
    const key = JSON.stringify(args);
    
    const cached = cache.get(key);
    if (cached !== undefined || cache.has(key)) {
      return cached as ReturnType<T>;
    }
    
    const result = fn(...args) as ReturnType<T>;
    cache.set(key, result);
    
    // 캐시 크기 제한
    if (cache.size > maxSize) {
      const firstKey = cache.keys().next().value;
      if (firstKey !== undefined) {
        cache.delete(firstKey);
      }
    }
    
    return result;
  }) as T;
};

/**
 * 배치 처리를 위한 간단한 큐
 */
export class BatchQueue<T> {
  private queue: T[] = [];
  private processing = false;
  private batchSize: number;
  private processFn: (items: T[]) => Promise<void>;
  private delay: number;

  constructor(
    batchSize: number,
    delay: number,
    processFn: (items: T[]) => Promise<void>
  ) {
    this.batchSize = batchSize;
    this.delay = delay;
    this.processFn = processFn;
  }

  add(item: T) {
    this.queue.push(item);
    if (!this.processing) {
      this.process();
    }
  }

  private async process() {
    this.processing = true;

    while (this.queue.length > 0) {
      const batch = this.queue.splice(0, this.batchSize);
      await this.processFn(batch);
      await new Promise(resolve => setTimeout(resolve, this.delay));
    }

    this.processing = false;
  }
}

/**
 * 가상 스크롤을 위한 간단한 헬퍼
 */
export const calculateVisibleItems = <T>(
  items: T[],
  containerHeight: number,
  itemHeight: number,
  scrollTop: number,
  buffer: number = 5
) => {
  const startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - buffer);
  const endIndex = Math.min(
    items.length,
    Math.ceil((scrollTop + containerHeight) / itemHeight) + buffer
  );

  return {
    visibleItems: items.slice(startIndex, endIndex),
    startIndex,
    endIndex,
    totalHeight: items.length * itemHeight,
  };
};