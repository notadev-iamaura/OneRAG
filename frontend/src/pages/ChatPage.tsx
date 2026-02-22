import React from 'react';
import { ChatTab } from '../components/ChatTab';
import { useToast } from '@/hooks/use-toast';
import { ToastMessage } from '../types';

export default function ChatPage() {
  const { toast } = useToast();

  // 토스트 메시지 표시 (ChatTab에서 prop으로 전달받음)
  const showToast = (message: Omit<ToastMessage, 'id'>) => {
    toast({
      title: message.type === 'error' ? '오류' : message.type === 'success' ? '성공' : '알림',
      description: message.message,
      variant: message.type === 'error' ? 'destructive' : 'default',
    });
  };

  return (
    <div className="h-full flex flex-col bg-background">
      <ChatTab showToast={showToast} />
    </div>
  );
}
