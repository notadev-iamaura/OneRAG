/* eslint-disable no-restricted-syntax */
import React from 'react';
import { useIsDarkMode } from '../../hooks/useIsDarkMode';

/**
 * 모노톤 챗봇 아이콘 컴포넌트
 *
 * 현대적이고 미니멀한 모노톤 디자인의 챗봇 아이콘
 * 다크모드를 지원하며 보라색 사용하지 않음
 */
interface ChatbotIconProps {
  width?: number | string;
  height?: number | string;
  className?: string;
  animated?: boolean;
}

export const ChatbotIcon: React.FC<ChatbotIconProps> = ({
  width = 24,
  height = 24,
  className,
  animated = false,
}) => {
  const isDark = useIsDarkMode();

  const mainColor = isDark ? 'rgba(255, 255, 255, 0.9)' : 'rgba(0, 0, 0, 0.8)';
  const secondaryColor = isDark ? 'rgba(255, 255, 255, 0.6)' : 'rgba(0, 0, 0, 0.5)';
  const lightColor = isDark ? 'rgba(255, 255, 255, 0.3)' : 'rgba(0, 0, 0, 0.3)';
  const eyeColor = isDark ? '#000000' : '#ffffff';

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      {/* 챗봇 머리 (둥근 사각형) */}
      <rect
        x="5"
        y="7"
        width="14"
        height="12"
        rx="3"
        fill={mainColor}
      />

      {/* 안테나 */}
      <g>
        <line
          x1="12"
          y1="7"
          x2="12"
          y2="4"
          stroke={secondaryColor}
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <circle
          cx="12"
          cy="3"
          r="1.5"
          fill={secondaryColor}
        >
          {animated && (
            <animate
              attributeName="opacity"
              values="0.5;1;0.5"
              dur="2s"
              repeatCount="indefinite"
            />
          )}
        </circle>
      </g>

      {/* 눈 */}
      <g>
        <circle
          cx="9"
          cy="11"
          r="1.5"
          fill={eyeColor}
        >
          {animated && (
            <animate
              attributeName="r"
              values="1.5;1.3;1.5"
              dur="3s"
              repeatCount="indefinite"
            />
          )}
        </circle>
        <circle
          cx="15"
          cy="11"
          r="1.5"
          fill={eyeColor}
        >
          {animated && (
            <animate
              attributeName="r"
              values="1.5;1.3;1.5"
              dur="3s"
              repeatCount="indefinite"
            />
          )}
        </circle>
      </g>

      {/* 입 (미소 짓는 모양) */}
      <path
        d="M9 14.5 Q12 16 15 14.5"
        stroke={eyeColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />

      {/* 몸통 */}
      <rect
        x="8"
        y="19"
        width="8"
        height="3"
        rx="1.5"
        fill={lightColor}
        opacity="0.8"
      />

      {/* 팔 (양쪽) */}
      <g opacity="0.9">
        <rect
          x="4"
          y="12"
          width="2"
          height="6"
          rx="1"
          fill={secondaryColor}
        />
        <rect
          x="18"
          y="12"
          width="2"
          height="6"
          rx="1"
          fill={secondaryColor}
        />
      </g>

      {/* AI 인디케이터 (작은 점들) */}
      <g opacity="0.6">
        <circle cx="7" cy="15" r="0.5" fill={secondaryColor}>
          {animated && (
            <animate
              attributeName="opacity"
              values="0.3;1;0.3"
              dur="1.5s"
              repeatCount="indefinite"
            />
          )}
        </circle>
        <circle cx="17" cy="15" r="0.5" fill={secondaryColor}>
          {animated && (
            <animate
              attributeName="opacity"
              values="0.3;1;0.3"
              dur="1.5s"
              begin="0.5s"
              repeatCount="indefinite"
            />
          )}
        </circle>
      </g>
    </svg>
  );
};

export default ChatbotIcon;
