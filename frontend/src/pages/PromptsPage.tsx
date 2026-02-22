import React from 'react';
import PromptManager from '../components/PromptManager';
import { ProtectedRoute } from '../components/ProtectedRoute';

export default function PromptsPage() {

  return (
    <ProtectedRoute title="프롬프트 관리 접근">
      <div className="container mx-auto max-w-[1400px] py-6 animate-in fade-in duration-500">
        <PromptManager />
      </div>
    </ProtectedRoute>
  );
}
