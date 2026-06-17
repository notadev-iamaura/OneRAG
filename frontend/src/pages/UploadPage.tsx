import React, { useState } from 'react';
import {
  UploadCloud,
  FileText,
  Settings,
} from 'lucide-react';
import { UploadTab } from '../components/UploadTab';
import { DocumentsTab } from '../components/DocumentsTab';
import { ChatSettingsManager } from '../components/ChatSettingsManager';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { ToastMessage } from '../types';
import { useToast } from '@/hooks/use-toast';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMenuMessages } from '../i18n/useMenuLocale';

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState("upload");
  const { toast } = useToast();
  const { messages } = useMenuMessages();

  // 토스트 메시지 표시
  const showToast = (message: Omit<ToastMessage, 'id'>) => {
    toast({
      variant: message.type === 'error' ? 'destructive' : 'default',
      title: message.type === 'success' ? messages.common.toastSuccess : message.type === 'error' ? messages.common.toastError : messages.common.toastInfo,
      description: message.message,
    });
  };

  return (
    <ProtectedRoute title={messages.pages.documentAccessTitle}>
      <div className="container max-w-7xl mx-auto py-6 space-y-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <div className="border-b border-border/40 bg-background/50 backdrop-blur-sm sticky top-16 z-30 -mx-4 px-4 md:mx-0 md:px-0 rounded-t-2xl">
            <TabsList className="h-14 w-full justify-start bg-transparent p-0 gap-2">
              <TabsTrigger
                value="upload"
                className="h-14 data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-6 gap-2 font-bold transition-all hover:bg-muted/50"
              >
                <UploadCloud className="w-5 h-5" />
                {messages.pages.documentUploadTab}
              </TabsTrigger>
              <TabsTrigger
                value="documents"
                className="h-14 data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-6 gap-2 font-bold transition-all hover:bg-muted/50"
              >
                <FileText className="w-5 h-5" />
                {messages.pages.documentManagementTab}
              </TabsTrigger>
              <TabsTrigger
                value="settings"
                className="h-14 data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-6 gap-2 font-bold transition-all hover:bg-muted/50"
              >
                <Settings className="w-5 h-5" />
                {messages.pages.chatSettingsTab}
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="mt-6">
            <TabsContent value="upload" className="animate-in fade-in-50 duration-300">
              <UploadTab showToast={showToast} />
            </TabsContent>
            <TabsContent value="documents" className="animate-in fade-in-50 duration-300">
              <DocumentsTab showToast={showToast} />
            </TabsContent>
            <TabsContent value="settings" className="animate-in fade-in-50 duration-300">
              <ChatSettingsManager
                onSave={() => {
                  showToast({
                    type: 'success',
                    message: messages.pages.chatSettingsSaved,
                  });
                }}
              />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </ProtectedRoute>
  );
}