import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { AccessControl } from './AccessControl';
import { hasAdminAccess } from '../utils/accessControl';

interface ProtectedRouteProps {
  children: React.ReactNode;
  title?: string;
}

export function ProtectedRoute({ children, title }: ProtectedRouteProps) {
  const [isAccessGranted, setIsAccessGranted] = useState<boolean>(() => hasAdminAccess());
  const [showAccessControl, setShowAccessControl] = useState<boolean>(() => !hasAdminAccess());
  const location = useLocation();

  useEffect(() => {
    // 접근 권한 확인
    const hasAccess = hasAdminAccess();
    setIsAccessGranted(hasAccess);
    setShowAccessControl(!hasAccess);
  }, [location]);

  const handleAccessGranted = () => {
    setIsAccessGranted(true);
    setShowAccessControl(false);
  };

  const handleCancel = () => {
    setShowAccessControl(false);
    // 챗봇 페이지로 리다이렉트
    window.location.href = '/bot';
  };

  if (isAccessGranted) {
    return <>{children}</>;
  }

  return (
    <AccessControl
      isOpen={showAccessControl}
      onAccessGranted={handleAccessGranted}
      onCancel={handleCancel}
      title={title}
    />
  );
}