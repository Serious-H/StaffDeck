import { type CSSProperties, useState } from 'react';

import AppSidebar from '@/components/AppSidebar';
import { SidebarProvider } from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';

import { CHAT_MAIN_CLASS } from './chatPageStyles';
import { sessionHasUnreadReply } from './chatHelpers';
import { useChatSession } from './useChatSession';
import ChatHeader from './components/ChatHeader';
import MessageList from './components/MessageList';
import Composer from './components/Composer';
import ChatDialogs from './components/ChatDialogs';
import SessionWorkspaceFilesDrawer from './components/SessionWorkspaceFilesDrawer';

export default function ChatPage() {
  const chat = useChatSession();
  const [sessionFilesOpen, setSessionFilesOpen] = useState(false);

  return (
    <SidebarProvider
      open={!chat.sidebarCollapsed}
      onOpenChange={(open) => {
        if (open === chat.sidebarCollapsed) chat.toggleSidebar();
      }}
      style={
        {
          '--sidebar-width': '220px',
          '--sidebar-width-icon': '72px',
        } as CSSProperties
      }
      className="h-screen min-h-0 bg-[#fcfcfc] text-[#18181a]"
    >
      <AppSidebar
        variant="chat"
        sessions={chat.visibleSidebarSessions}
        sessionsLoading={chat.sessionsLoading}
        agents={chat.agents}
        scopeTeams={chat.teams}
        activeSessionId={chat.sessionId}
        sessionFilter={chat.sessionAgentFilter}
        onSessionFilterChange={chat.setSessionAgentFilter}
        sessionFilterOptions={chat.sessionFilterOptions}
        isSessionUnread={(session) => sessionHasUnreadReply(session, chat.sessionReadTimes, chat.sessionId)}
        onOpenSession={chat.openSession}
        onNewConversation={() => {
          const selectedAgent = chat.sessionAgentFilter === 'all'
            ? chat.displayedAgent
            : chat.agents.find((agent) => agent.id === chat.sessionAgentFilter);
          if (selectedAgent) chat.openDraftForAgent(selectedAgent.id);
          else chat.openGallery();
        }}
        onOpenGallery={chat.openGallery}
        handoffCount={chat.handoffs.length}
        onOpenHandoffs={chat.openHandoffInbox}
        onRenameSession={chat.openRename}
        onDeleteSession={chat.requestDelete}
        onOpenAdmin={chat.openAdmin}
      />
      <main className={cn(CHAT_MAIN_CLASS, 'flex-1')}>
        <ChatHeader
          chat={chat}
          sessionFilesOpen={sessionFilesOpen}
          onToggleSessionFiles={() => setSessionFilesOpen((open) => !open)}
        />
        <MessageList chat={chat} />
        <Composer chat={chat} />
      </main>
      <SessionWorkspaceFilesDrawer
        open={sessionFilesOpen}
        sessionId={chat.sessionId}
        tenantId={chat.tenantId}
        onClose={() => setSessionFilesOpen(false)}
      />
      <ChatDialogs chat={chat} />
    </SidebarProvider>
  );
}
