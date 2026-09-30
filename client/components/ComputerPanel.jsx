'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FiActivity,
  FiAlertCircle,
  FiArrowLeft,
  FiCpu,
  FiHardDrive,
  FiMonitor,
  FiPause,
  FiPlay,
  FiRefreshCw,
  FiSquare,
  FiTerminal,
} from 'react-icons/fi';

import {
  fetchComputerScreenshot,
  fetchComputerStatus,
  pauseComputer,
  resetComputer,
  startComputer,
  stopComputer,
} from '../lib/api';

const ACTIVE_STATES = new Set(['running', 'paused']);

function stateClasses(state) {
  if (state === 'running') return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
  if (state === 'paused') return 'bg-amber-500/20 text-amber-300 border-amber-500/30';
  if (state === 'starting' || state === 'resetting') return 'bg-blue-500/20 text-blue-300 border-blue-500/30';
  return 'bg-slate-800 text-slate-300 border-slate-700';
}
function prettyState(state) {
  return (state || 'stopped').replace(/_/g, ' ');
}

export default function ComputerPanel({ bot, onBackToChat }) {
  const [computer, setComputer] = useState(null);
  const [screen, setScreen] = useState(null);
  const [activeTab, setActiveTab] = useState('display');
  const [loading, setLoading] = useState(true);
  const [loadingAction, setLoadingAction] = useState('');
  const [error, setError] = useState('');

  const botId = bot?.id;
  const state = computer?.state || 'stopped';
  const isActive = ACTIVE_STATES.has(state);

  const refresh = useCallback(async (includeScreen = true) => {
    if (!botId) return;
    try {
      const statusPayload = await fetchComputerStatus(botId);
      const nextComputer = statusPayload.status;
      setComputer(nextComputer);
      if (includeScreen && ACTIVE_STATES.has(nextComputer.state)) {
        const screenPayload = await fetchComputerScreenshot(botId);
        setScreen(screenPayload.result || null);
      } else if (!ACTIVE_STATES.has(nextComputer.state)) {
        setScreen(null);
      }
      setError('');
    } catch (err) {
      setError(err.message || 'Computer provider is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    let disposed = false;
    setComputer(null);
    setScreen(null);
    setError('');
    setLoading(true);

    async function load() {
      if (!botId || disposed) return;
      try {
        const statusPayload = await fetchComputerStatus(botId);
        if (disposed) return;
        setComputer(statusPayload.status);
        if (ACTIVE_STATES.has(statusPayload.status.state)) {
          const screenPayload = await fetchComputerScreenshot(botId);
          if (!disposed) setScreen(screenPayload.result || null);
        }
      } catch (err) {
        if (!disposed) setError(err.message || 'Computer provider is unavailable.');
      } finally {
        if (!disposed) setLoading(false);
      }
    }

    load();
    const interval = window.setInterval(() => {
      if (!disposed) refresh(true);
    }, 4000);

    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [botId, refresh]);

  const runAction = async (name, operation) => {
    if (!botId) return;
    setLoadingAction(name);
    setError('');
    try {
      await operation(botId);
      await refresh(true);
    } catch (err) {
      setError(err.message || `Computer ${name} failed.`);
    } finally {
      setLoadingAction('');
    }
  };

  const capabilities = useMemo(() => computer?.capabilities || [], [computer]);

  if (!bot) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-950/80 p-6 text-sm text-slate-400">
        Select a bot to view its computer provider.
      </div>
    );
  }

  const actionBusy = Boolean(loadingAction);

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-slate-950/80 p-6 space-y-6">
      <div className="flex items-center justify-between glass-panel p-4 rounded-2xl border border-slate-800">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onBackToChat}
            className="w-9 h-9 rounded-xl border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 flex items-center justify-center transition"
            aria-label="Back to chat"
          >
            <FiArrowLeft />
          </button>
          <div className="w-10 h-10 rounded-xl bg-purple-600/20 text-purple-400 border border-purple-500/30 flex items-center justify-center text-xl">
            <FiMonitor />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-slate-100 flex items-center gap-2">
              Computer provider
              <span className={`text-[10px] px-2 py-0.5 rounded font-mono border flex items-center gap-1 capitalize ${stateClasses(state)}`}>
                <FiActivity className={state === 'running' ? 'animate-pulse' : ''} /> {prettyState(state)}
              </span>
            </h2>
            <p className="text-xs text-slate-400 truncate">
              Lifecycle for <span className="text-slate-200 font-semibold">{bot.name || 'Agent'}</span> through the governed provider boundary.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {state === 'running' ? (
            <button
              onClick={() => runAction('pause', pauseComputer)}
              disabled={actionBusy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-amber-500/20 text-amber-300 border-amber-500/30 hover:bg-amber-500/30 disabled:opacity-50 transition"
            >
              <FiPause /> {loadingAction === 'pause' ? 'Pausing…' : 'Pause'}
            </button>
          ) : (
            <button
              onClick={() => runAction('start', startComputer)}
              disabled={actionBusy || state === 'starting' || state === 'resetting'}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-emerald-500/20 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/30 disabled:opacity-50 transition"
            >
              <FiPlay /> {loadingAction === 'start' ? (state === 'paused' ? 'Resuming…' : 'Starting…') : (state === 'paused' ? 'Resume' : 'Start')}
            </button>
          )}
          <button
            onClick={() => runAction('reset', resetComputer)}
            disabled={actionBusy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <FiRefreshCw className={loadingAction === 'reset' ? 'animate-spin' : ''} /> Reset
          </button>
          <button
            onClick={() => runAction('stop', stopComputer)}
            disabled={actionBusy || state === 'stopped'}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <FiSquare /> Stop
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-200">
          <FiAlertCircle /> {error}
        </div>
      )}

      <div className="flex-1 grid grid-cols-3 gap-6 min-h-0">
        <div className="col-span-2 glass-panel rounded-2xl border border-slate-800 flex flex-col overflow-hidden shadow-2xl relative">
          <div className="p-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
              <span className={`w-2.5 h-2.5 rounded-full ${isActive ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'}`} />
              Screen state · {computer?.width || 1920}x{computer?.height || 1080} @ {computer?.fps || 30}FPS
            </div>
            <span className="text-[10px] font-mono text-slate-500">
              {computer?.computer_id || 'not-created'}
            </span>
          </div>

          <div className="flex items-center gap-1 px-3 pt-3">
            {[
              ['display', 'Display'],
              ['activity', 'Activity'],
            ].map(([tab, label]) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1.5 rounded-lg text-[11px] font-semibold transition ${activeTab === tab ? 'bg-blue-500/15 text-blue-300' : 'text-slate-500 hover:text-slate-300'}`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="flex-1 bg-slate-950 flex items-center justify-center relative p-6 min-h-0">
            {activeTab === 'display' ? (
              screen?.available ? (
                screen.data ? (
                  <div className="w-full h-full rounded-xl border border-slate-800 bg-black flex items-center justify-center relative overflow-hidden shadow-2xl">
                    <img
                      src={`data:image/${['jpeg', 'png', 'webp'].includes(screen.format) ? screen.format : 'jpeg'};base64,${screen.data}`}
                      alt={`Computer frame ${screen.frame_id || ''}`}
                      className="max-w-full max-h-full object-contain"
                    />
                    <span className="absolute top-3 right-3 rounded bg-black/70 px-2 py-1 text-[10px] font-mono text-slate-300">
                      {screen.frame_id}
                    </span>
                  </div>
                ) : (
                  <div className="w-full h-full rounded-xl border border-slate-800/80 bg-gradient-to-br from-slate-900 via-slate-950 to-blue-950/40 p-4 flex flex-col justify-between shadow-2xl relative overflow-hidden">
                    <div className="flex items-center justify-between text-xs text-slate-400 border-b border-slate-800/60 pb-2">
                      <span className="font-mono text-cyan-400">Provider frame metadata</span>
                      <span>{screen.frame_id}</span>
                    </div>
                    <div className="font-mono text-xs space-y-2 my-auto">
                      <p className="text-emerald-400">✓ Computer is {screen.state}</p>
                      <p className="text-slate-400">Provider: {screen.provider}</p>
                      <p className="text-slate-400">Generation: {screen.generation}</p>
                      <p className="text-amber-400">{screen.message}</p>
                      <p className="text-slate-500 animate-pulse">Polling for the next frame…</p>
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-slate-500 pt-2 border-t border-slate-800/60">
                      <span>Actual pixels require the selected Docker or remote runtime.</span>
                      <span>{screen.width}x{screen.height}</span>
                    </div>
                  </div>
                )
              ) : (
                <div className="w-full h-full rounded-xl border border-dashed border-slate-800 flex flex-col items-center justify-center text-center p-8">
                  <FiMonitor className="text-4xl text-slate-700 mb-4" />
                  <p className="text-sm font-semibold text-slate-300">No screen frame available</p>
                  <p className="text-xs text-slate-500 mt-2 max-w-sm">
                    Start the selected provider to receive screen metadata or a live frame.
                  </p>
                </div>
              )
            ) : (
              <div className="w-full h-full rounded-xl border border-slate-800 bg-slate-950 p-5 font-mono text-xs space-y-2 overflow-auto">
                <p className="text-slate-500">[provider] {computer?.provider || 'unconfigured'} adapter</p>
                <p className="text-slate-400">[state] {prettyState(state)}</p>
                <p className="text-slate-400">[health] {computer?.health || 'unknown'}</p>
                <p className="text-slate-400">[operation] {computer?.last_operation || 'none'}</p>
                <p className="text-slate-500">[screen] {screen?.frame_id || 'no frame'}</p>
                <p className="text-blue-400">[note] All lifecycle calls are recorded by the action gateway.</p>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4 flex flex-col">
          <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
            <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
              <FiCpu className="text-blue-400" /> Provider status
            </h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between text-slate-400"><span>Provider</span><span className="text-slate-200 font-mono">{computer?.provider || 'unconfigured'}</span></div>
              <div className="flex justify-between text-slate-400"><span>State</span><span className="text-slate-200 capitalize">{prettyState(state)}</span></div>
              <div className="flex justify-between text-slate-400"><span>Health</span><span className="text-slate-200 capitalize">{computer?.health || 'unknown'}</span></div>
              <div className="flex justify-between text-slate-400"><span>Generation</span><span className="text-slate-200 font-mono">{computer?.generation ?? 0}</span></div>
              <div className="flex justify-between text-slate-400"><span>Last operation</span><span className="text-slate-200 font-mono">{computer?.last_operation || 'none'}</span></div>
            </div>
          </div>

          <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3 flex-1 flex flex-col min-h-0">
            <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
              <FiTerminal className="text-purple-400" /> Contract capabilities
            </h3>
            {loading ? (
              <p className="text-xs text-slate-500">Loading provider…</p>
            ) : (
              <div className="flex-1 bg-slate-950 p-3 rounded-xl border border-slate-800 space-y-2 overflow-y-auto">
                {capabilities.map((capability) => (
                  <div key={capability} className="flex items-center justify-between text-[11px] font-mono">
                    <span className="text-slate-400">{capability}</span>
                    <span className="text-emerald-400">declared</span>
                  </div>
                ))}
                {!capabilities.length && <p className="text-[11px] text-slate-600">No provider has been created yet.</p>}
              </div>
            )}
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <FiHardDrive /> Runtime state is local and ephemeral in this milestone.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
