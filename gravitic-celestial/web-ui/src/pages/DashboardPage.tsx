import { useEffect, useState } from 'react';
import { Globe, RefreshCw } from 'lucide-react';
import { MetricCard } from '../components/MetricCard';
import { fetchFilings, fetchUnreadCount } from '../api/client';
import type { Filing } from '../api/client';
import { FilingDetailPanel } from '../components/FilingDetailPanel';

function timeAgo(iso: string) {
    try {
        const d = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
        if (d < 60) return 'just now';
        if (d < 3600) return `${Math.floor(d / 60)}m ago`;
        if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
        return `${Math.floor(d / 86400)}d ago`;
    } catch { return iso; }
}

function statusClass(s: string) {
    if (s === 'ANALYZED') return 'status-analyzed';
    if (s === 'INGESTED') return 'status-ingested';
    if (['DEAD_LETTER', 'ANALYZED_NOT_INDEXED'].includes(s)) return 'status-error';
    return 'status-default';
}

export function DashboardPage() {
    const [unread, setUnread] = useState(0);
    const [filings, setFilings] = useState<Filing[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [selectedFiling, setSelectedFiling] = useState<string | null>(null);

    const load = async () => {
        const [u, f] = await Promise.all([fetchUnreadCount(), fetchFilings(20)]);
        setUnread(u); setFilings(f); setLoading(false); setRefreshing(false);
    };

    useEffect(() => { load(); }, []);

    const analyzed = filings.filter(f => f.status === 'ANALYZED').length;
    const seaCount = filings.filter(f => f.market === 'SEA_LOCAL').length;

    return (
        <div className="page animate-in">
            <div className="page-header">
                <div>
                    <h1>Dashboard</h1>
                    <p className="page-subtitle">Filing intelligence at a glance</p>
                </div>
                <button className="btn btn-primary" onClick={() => { setRefreshing(true); load(); }} disabled={refreshing}>
                    <RefreshCw size={14} style={{ animation: refreshing ? 'spin 0.75s linear infinite' : 'none' }} />
                    {refreshing ? 'Syncing…' : 'Refresh'}
                </button>
            </div>

            {loading ? (
                <div className="loading"><div className="spinner" /> Loading…</div>
            ) : (
                <>
                    <div className="metrics-grid">
                        <MetricCard title="Unread Alerts" value={unread} subtitle={unread > 0 ? 'Requires attention' : 'All caught up'} colorCombo={unread > 0 ? 'warning' : 'success'} />
                        <MetricCard title="Filings Tracked" value={filings.length} subtitle={`${analyzed} analyzed`} colorCombo="primary" />
                        <MetricCard title="SEA Markets" value={seaCount} subtitle="Multi-lingual PDFs" colorCombo="sea" />
                        <MetricCard title="System Health" value="Optimal" subtitle="All agents active" colorCombo="success" />
                    </div>

                    <h2 className="section-title">Recent Filings</h2>
                    <div className="glass-panel filings-table-wrap">
                        <table>
                            <thead>
                                <tr><th>Ticker</th><th>Market</th><th>Status</th><th>Updated</th><th>Accession</th></tr>
                            </thead>
                            <tbody>
                                {filings.length === 0 ? (
                                    <tr><td colSpan={5}><div className="empty-state">No filings yet. Run ingestion from the Watchlist page.</div></td></tr>
                                ) : filings.map((f, i) => (
                                    <tr key={i} className="clickable" onClick={() => setSelectedFiling(f.accession_number)}>
                                        <td><span className="ticker-badge">{f.ticker}</span></td>
                                        <td>{f.market === 'SEA_LOCAL' ? <span className="market-sea"><Globe size={13} /> SEA</span> : <span className="market-sec">US SEC</span>}</td>
                                        <td><span className={statusClass(f.status)}>{f.status}</span></td>
                                        <td className="text-muted">{timeAgo(f.updated_at)}</td>
                                        <td><span className="accession" style={{ userSelect: 'all' }}>{f.accession_number}</span></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}

            <FilingDetailPanel accession={selectedFiling} onClose={() => setSelectedFiling(null)} />
        </div>
    );
}
