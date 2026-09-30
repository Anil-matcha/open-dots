'use client';

import React, { useState, useEffect } from 'react';
import Sidebar from './Sidebar';
import ChatWindow from './ChatWindow';
import ComputerPanel from './ComputerPanel';
import Marketplace from './Marketplace';
import AuditPanel from './AuditPanel';
import AppSettingsDrawer from './AppSettingsDrawer';

import { 
  fetchBots, 
  fetchModels, 
  fetchChatHistory, 
  fetchSettings,
  createBot, 
  updateBot 
} from '../lib/api';

export default function Dashboard({ onLogout }) {
  const [bots, setBots] = useState([]);
  const [models, setModels] = useState([]);
  const [activeBotId, setActiveBotId] = useState('');
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'computer' | 'marketplace' | 'audit'
  const [messages, setMessages] = useState([]);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [defaultModel, setDefaultModel] = useState('gpt-5-mini');
  const [isNewBotOpen, setIsNewBotOpen] = useState(false);
  const [newBotName, setNewBotName] = useState('New Assistant');
  const [newBotRole, setNewBotRole] = useState('General Intelligence');
  const [newBotModel, setNewBotModel] = useState('');
  const [userName, setUserName] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('open_dots_user_name') || 'You';
    }
    return 'You';
  });

  // Initial Data Fetch
  useEffect(() => {
    async function initData() {
      try {
        const [botsData, modelsData, settingsData] = await Promise.all([fetchBots(), fetchModels(), fetchSettings()]);
        setBots(botsData);
        setModels(modelsData);
        if (settingsData?.default_model) {
          setDefaultModel(settingsData.default_model);
        }
        if (botsData.length > 0) {
          setActiveBotId(botsData[0].id);
        }
      } catch (err) {
        console.error('Initialization error:', err);
      }
    }
    initData();
  }, []);

  // Fetch chat history whenever active bot changes
  useEffect(() => {
    if (!activeBotId) return;
    fetchChatHistory(activeBotId)
      .then((history) => setMessages(history))
      .catch((err) => console.error('Failed to load history:', err));
  }, [activeBotId]);

  const activeBot = bots.find((b) => b.id === activeBotId) || bots[0];

  const handleUpdateBotModel = async (botId, newModel) => {
    try {
      const updated = await updateBot(botId, { model: newModel });
      setBots((prev) => prev.map((b) => (b.id === botId ? updated : b)));
    } catch (err) {
      console.error('Failed to update bot model:', err);
    }
  };

  const handleCreateNewBot = () => {
    // In-app modal instead of blocking prompt() dialogs: prompt() is spoofable
    // by page content and blocked by some browsers.
    setNewBotName('New Assistant');
    setNewBotRole('General Intelligence');
    setNewBotModel(defaultModel);
    setIsNewBotOpen(true);
  };

  // Close the New Bot modal with Escape, matching the old prompt() dismissal.
  useEffect(() => {
    if (!isNewBotOpen) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setIsNewBotOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isNewBotOpen]);

  const handleSubmitNewBot = async () => {
    const name = newBotName.trim();
    if (!name) return;
    const role = newBotRole.trim() || 'AI Assistant';
    const model = newBotModel.trim() || defaultModel;

    try {
      const newBot = await createBot({
        name,
        role,
        model,
        description: `Custom assistant configured to use ${model}.`,
        avatar: '🤖',
        system_prompt: `You are ${name}, a helpful AI assistant.`
      });
      setBots((prev) => [...prev, newBot]);
      setActiveBotId(newBot.id);
      setActiveTab('chat');
      setIsNewBotOpen(false);
    } catch (err) {
      console.error('Failed to create bot:', err);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#09090b] text-zinc-100 font-sans">
      {/* Sidebar Navigation & Bot Roster */}
      <Sidebar
        onLogout={onLogout}
        bots={bots}
        activeBotId={activeBotId}
        userName={userName}
        onSelectBot={(id) => {
          setActiveBotId(id);
          setActiveTab('chat');
        }}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        onOpenSettings={() => setIsSettingsOpen(!isSettingsOpen)}
        onOpenNewBot={handleCreateNewBot}
      />

      {/* Main Workspace Display Area */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden relative">
        {activeTab === 'chat' && (
          <ChatWindow
            bot={activeBot}
            models={models}
            messages={messages}
            setMessages={setMessages}
            onUpdateBotModel={handleUpdateBotModel}
            onToggleComputer={() => setActiveTab('computer')}
            defaultModel={defaultModel}
          />
        )}

        {activeTab === 'computer' && (
          <ComputerPanel bot={activeBot} onBackToChat={() => setActiveTab('chat')} />
        )}

        {activeTab === 'marketplace' && (
          <Marketplace onOpenSettings={() => setIsSettingsOpen(true)} />
        )}

        {activeTab === 'audit' && <AuditPanel />}
      </main>

      {/* Right Side App Settings Drawer Panel */}
      <AppSettingsDrawer
        models={models}
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        currentModel={defaultModel}
        onUpdateDefaultModel={async (newModel) => {
          setDefaultModel(newModel);
          setModels(await fetchModels());
        }}
        onProfileUpdate={(name) => setUserName(name || 'You')}
      />

      {/* New Bot Modal (replaces blocking prompt() dialogs) */}
      {isNewBotOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={() => setIsNewBotOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#121214] p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-sm font-semibold text-zinc-100 mb-4">Create new bot</h2>
            <label htmlFor="new-bot-name" className="block text-xs text-zinc-400 mb-1">Bot name</label>
            <input
              id="new-bot-name"
              value={newBotName}
              onChange={(e) => setNewBotName(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm mb-3 focus:outline-violet-400"
            />
            <label htmlFor="new-bot-role" className="block text-xs text-zinc-400 mb-1">Role</label>
            <input
              id="new-bot-role"
              value={newBotRole}
              onChange={(e) => setNewBotRole(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm mb-3 focus:outline-violet-400"
            />
            <label htmlFor="new-bot-model" className="block text-xs text-zinc-400 mb-1">Model</label>
            <input
              id="new-bot-model"
              value={newBotModel}
              onChange={(e) => setNewBotModel(e.target.value)}
              placeholder={defaultModel}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm focus:outline-violet-400"
            />
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setIsNewBotOpen(false)}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-zinc-300 hover:bg-zinc-800 transition"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitNewBot}
                disabled={!newBotName.trim()}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-40 transition"
              >
                Create bot
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
