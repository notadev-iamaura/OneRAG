/**
 * Lazy Loading 이미지 컴포넌트
 * Intersection Observer를 사용한 성능 최적화
 */
import React, { useState, useRef, useEffect } from 'react';
import { Loader2, ImageOff } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useMenuMessages } from '../i18n/useMenuLocale';

interface LazyImageProps {
  src: string;
  alt: string;
  className?: string;
  width?: string | number;
  height?: string | number;
  placeholder?: string;
  onLoad?: () => void;
  onError?: () => void;
}

export const LazyImage: React.FC<LazyImageProps> = ({
  src,
  alt,
  className,
  width,
  height,
  placeholder,
  onLoad,
  onError,
}) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [isInView, setIsInView] = useState(false);
  const [hasError, setHasError] = useState(false);
  const imgRef = useRef<HTMLDivElement>(null);
  // i18n: 이미지 로드 실패 메시지
  const { messages } = useMenuMessages();

  useEffect(() => {
    if (!imgRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsInView(true);
            observer.disconnect();
          }
        });
      },
      {
        rootMargin: '50px', // 뷰포트에서 50px 전에 미리 로드
      }
    );

    observer.observe(imgRef.current);

    return () => {
      observer.disconnect();
    };
  }, []);

  const handleLoad = () => {
    setIsLoaded(true);
    onLoad?.();
  };

  const handleError = () => {
    setHasError(true);
    onError?.();
  };

  return (
    <div
      ref={imgRef}
      style={{ width, height }}
      className={cn(
        "relative overflow-hidden bg-muted/40 flex items-center justify-center transition-all duration-300",
        className
      )}
    >
      {!isLoaded && !hasError && isInView && (
        <div className="absolute inset-0 flex items-center justify-center bg-muted/30">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground/40" />
        </div>
      )}

      {hasError && (
        <div className="flex flex-col items-center justify-center gap-2 p-4 text-muted-foreground/60 text-xs font-medium bg-muted/20 w-full h-full">
          <ImageOff className="h-8 w-8 opacity-20" />
          <span>{messages.common.imageLoadFailed}</span>
        </div>
      )}

      {isInView && !hasError && (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          onLoad={handleLoad}
          onError={handleError}
          className={cn(
            "w-full h-full object-cover transition-opacity duration-500 ease-in-out",
            isLoaded ? "opacity-100" : "opacity-0"
          )}
        />
      )}

      {placeholder && !isInView && !hasError && (
        <img
          src={placeholder}
          alt={`${alt} placeholder`}
          className="w-full h-full object-cover blur-md opacity-50 scale-105"
        />
      )}
    </div>
  );
};

export default LazyImage;

