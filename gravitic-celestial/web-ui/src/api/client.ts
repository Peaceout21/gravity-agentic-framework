import axios from 'axios';

export const api = axios.create({ baseURL: '/api' });

// --- Types ---
export interface Filing {
    ticker: string;
    accession_number: string;
    market: string;
    status: string;
    updated_at: string;
    filing_url?: string;
    last_error?: string;
    dead_letter_reason?: string;
    replay_count?: number;
    last_replay_at?: string;
    exchange?: string;
    issuer_id?: string;
    source?: string;
    source_event_id?: string;
    document_type?: string;
    currency?: string;
}
export interface Notification { id: number; ticker: string; title: string; body: string; is_read: boolean; notification_type: string; accession_number: string; created_at: string; }
export interface WatchlistItem { ticker: string; market: string; exchange: string; }
export interface OpsHealth { api: string; db: string; redis: string; workers: number; }
export interface OpsMetrics { queue_depths: Record<string, number>; filing_status_counts: Record<string, number>; recent_events: Record<string, number>; failed_jobs: number; recent_failures: Filing[]; }
export interface AskTemplate { id: number; title: string; description: string; }
export interface QueryResult { answer_markdown: string; citations: string[]; confidence: number; derivation_trace: string[]; relevance_label?: string; coverage_brief?: string; }
export interface HistoryEntry extends QueryResult { id?: number; question: string; ticker?: string; created_at?: string; template_id?: number; template_title?: string; }

// --- Filings ---
export const fetchFilings = (limit = 20) => api.get('/filings', { params: { limit } }).then(r => r.data as Filing[]).catch(() => [] as Filing[]);

// --- Notifications ---
export const fetchNotifications = (params: { limit?: number; unread_only?: boolean; ticker?: string; notification_type?: string }) =>
    api.get('/notifications', { params }).then(r => r.data as Notification[]).catch(() => [] as Notification[]);
export const fetchUnreadCount = () => api.get('/notifications/count').then(r => r.data.unread ?? 0).catch(() => 0);
export const markRead = (id: number) => api.post(`/notifications/${id}/read`, {}).catch(() => null);
export const markAllRead = (params?: { ticker?: string; notification_type?: string }) => api.post('/notifications/read-all', {}, { params }).catch(() => null);

// --- Watchlist ---
export const fetchWatchlist = (market?: string) => api.get('/watchlist', { params: market ? { market } : {} }).then(r => r.data as WatchlistItem[]).catch(() => [] as WatchlistItem[]);
export const addWatchlist = (tickers: string[], market: string, exchange?: string) => api.post('/watchlist', { tickers, market, exchange });
export const removeWatchlist = (tickers: string[], market: string, exchange?: string) => api.delete('/watchlist', { data: { tickers, market, exchange } });
export const fetchMarkets = () => api.get('/markets').then(r => r.data as string[]).catch(() => ['US_SEC']);
export const runIngestion = (tickers: string[], market: string, exchange?: string) => api.post('/ingest', { tickers, market, exchange }).then(r => r.data);
export const runBackfill = (tickers: string[], market: string, exchange?: string, per_ticker_limit = 8, include_existing = false, notify = true) =>
    api.post('/backfill', { tickers, market, exchange, per_ticker_limit, include_existing, notify }).then(r => r.data);

// --- Ops ---
export const fetchOpsHealth = () => api.get('/ops/health').then(r => r.data as OpsHealth).catch(() => ({ api: 'error', db: 'unknown', redis: 'unknown', workers: 0 } as OpsHealth));
export const fetchOpsMetrics = (window_minutes = 60) => api.get('/ops/metrics', { params: { window_minutes } }).then(r => r.data as OpsMetrics).catch(() => ({ queue_depths: {}, filing_status_counts: {}, recent_events: {}, failed_jobs: 0, recent_failures: [] } as OpsMetrics));
export const retryAllDeadLetter = () => api.post('/ops/retry-all-dead-letter').then(r => r.data as { status: string; enqueued_count: number });

// --- Ask ---
export const fetchTemplates = () => api.get('/ask/templates').then(r => r.data as AskTemplate[]).catch(() => [] as AskTemplate[]);
export const fetchAskHistory = (limit = 40) => api.get('/ask/history', { params: { limit } }).then(r => r.data as HistoryEntry[]).catch(() => [] as HistoryEntry[]);
export const runTemplate = (template_id: number, ticker?: string, params?: Record<string, string>) => api.post('/ask/template-run', { template_id, ticker, params }).then(r => r.data as QueryResult);
export const runQuery = (question: string, ticker?: string) => api.post('/query', { question, ticker }).then(r => r.data as QueryResult);
export const replayFiling = (accession_number: string) => api.post('/filings/replay', { accession_number, mode: 'auto' }).then(r => r.data);
export const fetchFiling = (accession: string) => api.get(`/filings/${accession}`).then(r => r.data as Filing).catch(() => null);
export const fetchTickerCount = (ticker: string) => api.get('/filings/ticker-count', { params: { ticker } }).then(r => r.data.count as number).catch(() => 0);
export const runBackfillMetadata = () => api.post('/filings/backfill-metadata').then(r => r.data).catch(() => null);
