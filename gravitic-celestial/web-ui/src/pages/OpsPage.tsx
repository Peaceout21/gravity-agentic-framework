import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { MetricCard } from '../components/MetricCard';
import { fetchOpsHealth, fetchOpsMetrics, type OpsHealth, type OpsMetrics, replayFiling, retryAllDeadLetter, runBackfillMetadata } from '../api/client';

function HealthDot({ status }: { status: string }) {
    const cls = status === 'ok' ? 'ok' : status.includes('error') ? 'error' : status === 'not_configured' ? 'off' : 'warn';
    return <span className={`health-dot ${cls}`} />;
}

export function OpsPage() {
    const [health, setHealth] = useState<OpsHealth | null>(null);
    const [metrics, setMetrics] = useState<OpsMetrics | null>(null);
    const [window, setWindow] = useState(60);
    const [loading, setLoading] = useState(true);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [refreshCountdown, setRefreshCountdown] = useState(30);

    const load = async () => {
        setLoading(true);
        const [h, m] = await Promise.all([fetchOpsHealth(), fetchOpsMetrics(window)]);
        setHealth(h); setMetrics(m); setLoading(false);
    };

    useEffect(() => { load(); }, [window]);

    useEffect(() => {
        if (autoRefresh) {
            setRefreshCountdown(30);
            timerRef.current = setInterval(() => { load(); setRefreshCountdown(30); }, 30000);
            countdownRef.current = setInterval(() => setRefreshCountdown(prev => Math.max(0, prev - 1)), 1000);
        } else {
            if (timerRef.current) clearInterval(timerRef.current);
            if (countdownRef.current) clearInterval(countdownRef.current);
            setRefreshCountdown(30);
        }
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
            if (countdownRef.current) clearInterval(countdownRef.current);
        };
    }, [autoRefresh, window]);

    const doRetry = async (accession: string) => {
        try { await replayFiling(accession); load(); } catch (e) { console.error(e); alert('Failed to retry'); }
    };

    const doRetryAll = async () => {
        try {
            const res = await retryAllDeadLetter();
            alert(`Retry initiated for ${res.enqueued_count} filings.`);
            load();
        } catch (e) {
            console.error(e);
            alert('Failed to initiate bulk retry');
        }
    };

    const doBackfillMeta = async () => {
        await runBackfillMetadata();
        alert('Backfill metadata submitted.');
    };

    const statusColor = (s: string) => s === 'ok' ? 'success' : s.includes('error') ? 'danger' : s === 'not_configured' ? 'neutral' : 'warning';

    return (
        <div className="page animate-in">
            <div className="page-header">
                <div>
                    <h1>Ops Dashboard</h1>
                    <p className="page-subtitle">Pipeline health, queue depths, and failure triage</p>
                </div>
                <div className="header-actions" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    {autoRefresh && <span className="text-muted small">Next refresh: {refreshCountdown}s</span>}
                    <label className="filter-toggle" style={{ margin: 0 }}>
                        <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
                        Auto-refresh
                        {autoRefresh && <span className="health-dot ok" style={{ marginLeft: 6 }} />}
                    </label>
                    <button className="btn btn-primary" onClick={load}><RefreshCw size={14} /> Refresh</button>
                </div>
            </div>

            {/* Health cards */}
            <h2 className="section-title">System Health</h2>
            {health && (
                <div className="metrics-grid">
                    {[
                        { label: 'API', value: health.api.toUpperCase(), status: health.api },
                        { label: 'Database', value: health.db === 'ok' ? 'OK' : 'ERROR', status: health.db },
                        { label: 'Redis', value: health.redis.replace('_', ' ').toUpperCase(), status: health.redis },
                        { label: 'Workers', value: health.workers, status: health.workers > 0 ? 'ok' : 'off' },
                    ].map(({ label, value, status }) => (
                        <div key={label} className={`glass-panel metric-card ${statusColor(status)}`}>
                            <div className="metric-card-top">
                                <span className="metric-label">{label}</span>
                                <HealthDot status={status} />
                            </div>
                            <div className="metric-value">{value}</div>
                        </div>
                    ))}
                </div>
            )}

            <div className="two-col-grid">
                {/* Window selector */}
                <div className="glass-panel filter-bar" style={{ marginTop: '1.5rem', marginBottom: '1.5rem' }}>
                    <label className="filter-label">Time window</label>
                    {[15, 30, 60, 120, 360].map(w => (
                        <button key={w} className={`window-btn${window === w ? ' active' : ''}`} onClick={() => setWindow(w)}>{w}m</button>
                    ))}
                </div>

                {/* Maintenance */}
                <div className="glass-panel filter-bar" style={{ marginTop: '1.5rem', marginBottom: '1.5rem', justifyContent: 'flex-start' }}>
                    <label className="filter-label" style={{ marginRight: '1rem' }}>Maintenance Actions</label>
                    <button className="btn window-btn" onClick={doBackfillMeta}>Backfill Metadata</button>
                </div>
            </div>

            {loading ? (
                <div className="loading"><div className="spinner" /></div>
            ) : metrics && (
                <>
                    {/* Queue depths */}
                    <h2 className="section-title">Queue Depths</h2>
                    {Object.keys(metrics.queue_depths).length === 0 ? (
                        <div className="glass-panel empty-state">No queue data. Redis may not be configured.</div>
                    ) : (
                        <div className="metrics-grid">
                            {Object.entries(metrics.queue_depths).map(([q, depth]) => (
                                <MetricCard key={q} title={q} value={depth} subtitle="pending jobs" colorCombo={Number(depth) > 50 ? 'danger' : Number(depth) > 10 ? 'warning' : 'primary'} />
                            ))}
                        </div>
                    )}

                    {/* Filing pipeline */}
                    <h2 className="section-title" style={{ marginTop: '2rem' }}>Filing Pipeline Status</h2>
                    {Object.keys(metrics.filing_status_counts).length === 0 ? (
                        <div className="glass-panel empty-state">No filings processed yet.</div>
                    ) : (
                        <div className="metrics-grid">
                            {Object.entries(metrics.filing_status_counts).sort().map(([status, count]) => {
                                const c = status === 'ANALYZED' ? 'success' : status === 'DEAD_LETTER' ? 'danger' : status === 'ANALYZED_NOT_INDEXED' ? 'warning' : 'neutral';
                                return <MetricCard key={status} title={status.replace(/_/g, ' ')} value={count} subtitle="filings" colorCombo={c as any} />;
                            })}
                        </div>
                    )}

                    {/* Recent events */}
                    <h2 className="section-title" style={{ marginTop: '2rem' }}>Event Activity (last {window}m)</h2>
                    {Object.keys(metrics.recent_events).length === 0 ? (
                        <div className="glass-panel empty-state">No events in the selected window.</div>
                    ) : (
                        <div className="metrics-grid">
                            {Object.entries(metrics.recent_events).sort().map(([topic, count]) => (
                                <MetricCard key={topic} title={topic} value={count} subtitle="events" colorCombo="primary" />
                            ))}
                        </div>
                    )}
                    {metrics.failed_jobs > 0 && (
                        <div className="error-msg" style={{ marginTop: '1rem' }}>⚠ {metrics.failed_jobs} failed jobs in dead-letter queues</div>
                    )}

                    {/* Recent failures */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '2rem', marginBottom: '1rem' }}>
                        <h2 className="section-title" style={{ margin: 0 }}>Recent Failures</h2>
                        {metrics.recent_failures.some(f => f.status === 'DEAD_LETTER') && (
                            <button className="btn btn-warning" style={{ fontSize: '0.75rem', padding: '0.25rem 0.75rem' }} onClick={doRetryAll}>
                                Retry All Dead-Letter
                            </button>
                        )}
                    </div>
                    {metrics.recent_failures.length === 0 ? (
                        <div className="glass-panel" style={{ padding: '1.25rem', color: 'var(--status-ok)' }}>✓ No recent failures. Pipeline is healthy.</div>
                    ) : (
                        <div className="glass-panel filings-table-wrap">
                            <table>
                                <thead><tr><th>Ticker</th><th>Accession</th><th>Status</th><th>Updated</th><th>Actions</th></tr></thead>
                                <tbody>
                                    {metrics.recent_failures.map((f, i) => (
                                        <tr key={i}>
                                            <td><span className="ticker-badge">{f.ticker}</span></td>
                                            <td><span className="accession">{f.accession_number}</span></td>
                                            <td><span className="status-error">{f.status}</span></td>
                                            <td className="text-muted">{f.updated_at}</td>
                                            <td>
                                                <button className="btn window-btn" style={{ padding: '0.15rem 0.5rem', fontSize: '0.7rem' }} onClick={() => doRetry(f.accession_number)}>
                                                    Retry
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
