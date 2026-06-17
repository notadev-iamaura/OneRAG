import React from 'react';
import PromptManager from '../components/PromptManager';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { useMenuMessages } from '../i18n/useMenuLocale';

export default function PromptsPage() {
  const { messages } = useMenuMessages();

  return (
    <ProtectedRoute title={messages.pages.promptAccessTitle}>
      <div className="container mx-auto max-w-[1400px] py-6 animate-in fade-in duration-500">
        <PromptManager />
      </div>
    </ProtectedRoute>
  );
}
