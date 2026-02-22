import { useEffect, useState } from 'react';
import { Plus, Trash2, Play, History } from 'lucide-react';
import { addWatchlist, fetchMarkets, fetchWatchlist, removeWatchlist, runBackfill, runIngestion } from '../api/client';
import type { WatchlistItem } from '../api/client';

type Msg = { type: 'success' | 'error'; text: string } | null;

export function WatchlistPage() {
    const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
    const [markets, setMarkets] = useState<string[]>(['US_SEC']);
    const [market, setMarket] = useState('US_SEC');
    const [exchange, setExchange] = useState('');
    const [addInput, setAddInput] = useState('');
    const [selected, setSelected] = useState<string[]>([]);
    const [bfTickers, setBfTickers] = useState('');
    const [bfLimit, setBfLimit] = useState(8);
    const [bfNotify, setBfNotify] = useState(true);
    const [ingTickers, setIngTickers] = useState('');
    const [msg, setMsg] = useState<Msg>(null);
    const [busy, setBusy] = useState('');

    function toast(type: 'success' | 'error', text: string) {
        setMsg({ type, text });
        setTimeout(() => setMsg(null), 4000);
    }

    async function load() {
        try {
            const [wl, mk] = await Promise.all([
                fetchWatchlist(market),
                fetchMarkets(),
            ]);
            const safeWl = Array.isArray(wl) ? wl : [];
            const safeMk = Array.isArray(mk) ? mk : ['US_SEC'];
            setWatchlist(safeWl);
            setMarkets(safeMk);
            const joined = safeWl.map((w: WatchlistItem) => w.ticker).join(', ');
            setBfTickers(joined);
            setIngTickers(joined);
        } catch (e) {
            console.error(e);
            toast('error', 'Failed to refresh watchlist');
            setWatchlist([]);
            setMarkets(['US_SEC']);
        }
    }

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [market]);

    async function doAdd() {
        const tickers = addInput.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
        if (!tickers.length) return;
        try {
            await addWatchlist(tickers, market, exchange || undefined);
            toast('success', `Added: ${tickers.join(', ')}`);
            setAddInput('');
            load();
        } catch (e: unknown) {
            const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            toast('error', detail || 'Failed to add');
        }
    }

    async function doRemove() {
        if (!selected.length) return;
        try {
            await removeWatchlist(selected, market, exchange || undefined);
            toast('success', `Removed: ${selected.join(', ')}`);
            setSelected([]);
            load();
        } catch (e: unknown) {
            const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            toast('error', detail || 'Failed to remove');
        }
    }

    async function doIngest() {
        const tickers = ingTickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
        if (!tickers.length) { toast('error', 'Enter tickers'); return; }
        setBusy('ingest');
        try {
            const r = await runIngestion(tickers, market, exchange || undefined);
            toast('success', `Processed ${(r as { filings_processed?: number }).filings_processed ?? 0} filings`);
        } catch (e: unknown) {
            const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            toast('error', detail || 'Ingestion failed');
        }
        setBusy('');
    }

    async function doBackfill() {
        const tickers = bfTickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
        if (!tickers.length) { toast('error', 'Enter tickers'); return; }
        setBusy('backfill');
        try {
            const r = await runBackfill(tickers, market, exchange || undefined, bfLimit, false, bfNotify) as { mode?: string; job_id?: string; filings_processed?: number; analyzed?: number };
            if (r.mode === 'async') toast('success', `Job submitted: ${r.job_id}`);
            else toast('success', `Complete: ${r.filings_processed ?? 0} processed, ${r.analyzed ?? 0} analyzed`);
        } catch (e: unknown) {
            const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            toast('error', detail || 'Backfill failed');
        }
        setBusy('');
    }

    function toggleSelect(ticker: string, checked: boolean) {
        setSelected(prev => checked ? [...prev, ticker] : prev.filter(t => t !== ticker));
    }

    return (
        <div className="page animate-in">
            <div className="page-header">
                <div>
                    <h1>Watchlist &amp; Backfill</h1>
                    <p className="page-subtitle">Manage tickers and load historical filings</p>
                </div>
            </div>

            {msg && <div className={`toast ${msg.type}`}>{msg.text}</div>}

            {/* Market Selector */}
            <div className="glass-panel filter-bar" style={{ marginBottom: '1.5rem' }}>
                <label className="filter-label">Market</label>
                <select className="filter-select" value={market} onChange={e => setMarket(e.target.value)}>
                    {markets.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                <input className="filter-input" placeholder="Exchange (optional)" value={exchange} onChange={e => setExchange(e.target.value)} />
            </div>

            {/* Current Watchlist */}
            <h2 className="section-title">Your Watchlist</h2>
            <div className="glass-panel section-card" style={{ marginBottom: '1.5rem' }}>
                {watchlist.length === 0 ? (
                    <p className="text-muted">No tickers watched for {market}. Add some below.</p>
                ) : (
                    <div className="watchlist-grid">
                        {watchlist.map(w => (
                            <label key={w.ticker} className={`wl-item${selected.includes(w.ticker) ? ' checked' : ''}`}>
                                <input
                                    type="checkbox"
                                    checked={selected.includes(w.ticker)}
                                    onChange={e => toggleSelect(w.ticker, e.target.checked)}
                                />
                                <span className="ticker-badge">{w.ticker}</span>
                                <span className="text-muted small">{w.exchange || w.market}</span>
                            </label>
                        ))}
                    </div>
                )}
            </div>

            {/* Add / Remove */}
            <div className="two-col-grid" style={{ marginBottom: '2rem' }}>
                <div className="glass-panel section-card">
                    <h3 className="card-heading"><Plus size={15} style={{ verticalAlign: 'middle' }} /> Add Tickers</h3>
                    <input className="field-input" placeholder="MSFT, AAPL, GOOG" value={addInput} onChange={e => setAddInput(e.target.value)} />
                    <button className="btn btn-primary mt-1" onClick={doAdd}><Plus size={14} /> Add to watchlist</button>
                </div>
                <div className="glass-panel section-card">
                    <h3 className="card-heading"><Trash2 size={15} style={{ verticalAlign: 'middle' }} /> Remove Tickers</h3>
                    <p className="text-muted small">Check tickers above, then remove</p>
                    <button className="btn btn-danger mt-1" onClick={doRemove} disabled={!selected.length}>
                        <Trash2 size={14} /> Remove{selected.length > 0 ? ` (${selected.length})` : ''}
                    </button>
                </div>
            </div>

            {/* Ingestion */}
            <h2 className="section-title">Run Ingestion Cycle</h2>
            <div className="glass-panel section-card" style={{ marginBottom: '2rem' }}>
                <p className="text-muted" style={{ marginBottom: '0.75rem' }}>Check for the latest filings matching your watchlist.</p>
                <input className="field-input" placeholder="MSFT, AAPL" value={ingTickers} onChange={e => setIngTickers(e.target.value)} />
                <button className="btn btn-primary mt-1" onClick={doIngest} disabled={busy === 'ingest'}>
                    <Play size={14} /> {busy === 'ingest' ? 'Running…' : 'Run Ingestion'}
                </button>
            </div>

            {/* Backfill */}
            <h2 className="section-title">Historical Backfill</h2>
            <div className="glass-panel section-card">
                <p className="text-muted" style={{ marginBottom: '0.75rem' }}>Load and analyze historical filings.</p>
                <div className="two-col-grid">
                    <div>
                        <label className="field-label">Tickers</label>
                        <input className="field-input" value={bfTickers} onChange={e => setBfTickers(e.target.value)} />
                    </div>
                    <div>
                        <label className="field-label">Filings per ticker</label>
                        <input className="field-input" type="number" min={1} max={50} value={bfLimit} onChange={e => setBfLimit(Number(e.target.value))} />
                    </div>
                </div>
                <label className="filter-toggle" style={{ marginTop: '0.75rem' }}>
                    <input type="checkbox" checked={bfNotify} onChange={e => setBfNotify(e.target.checked)} />
                    Send notifications for results
                </label>
                <button className="btn btn-primary mt-1" onClick={doBackfill} disabled={busy === 'backfill'}>
                    <History size={14} /> {busy === 'backfill' ? 'Running…' : 'Start Backfill'}
                </button>
            </div>
        </div>
    );
}
