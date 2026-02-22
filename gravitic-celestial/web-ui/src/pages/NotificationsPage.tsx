import { useEffect, useState } from 'react';
import { CheckCheck, RefreshCw } from 'lucide-react';
import { fetchNotifications, fetchUnreadCount, markAllRead, markRead, type Notification } from '../api/client';

function timeAgo(iso: string) {
    try {
        const d = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
        if (d < 60) return 'just now';
        if (d < 3600) return `${Math.floor(d / 60)}m ago`;
        if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
        return `${Math.floor(d / 86400)}d ago`;
    } catch { return iso; }
}

export function NotificationsPage() {
    const [notifs, setNotifs] = useState<Notification[]>([]);
    const [unread, setUnread] = useState(0);
    const [unreadOnly, setUnreadOnly] = useState(true);
    const [ticker, setTicker] = useState('');
    const [type, setType] = useState('All');
    const [limit, setLimit] = useState(50);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        setLoading(true);
        const [n, u] = await Promise.all([
            fetchNotifications({ limit, unread_only: unreadOnly, ticker: ticker.trim().toUpperCase() || undefined, notification_type: type !== 'All' ? type : undefined }),
            fetchUnreadCount(),
        ]);
        setNotifs(n); setUnread(u); setLoading(false);
    };

    useEffect(() => { load(); }, [unreadOnly, ticker, type, limit]);

    const doMarkAll = async () => {
        await markAllRead({ ticker: ticker.trim().toUpperCase() || undefined, notification_type: type !== 'All' ? type : undefined });
        load();
    };

    const doMarkOne = async (id: number) => {
        await markRead(id);
        load();
    };

    return (
        <div className="page animate-in">
            <div className="page-header">
                <div>
                    <h1>Notifications</h1>
                    <p className="page-subtitle">{unread > 0 ? `${unread} unread` : 'All caught up'}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-ghost" onClick={doMarkAll}><CheckCheck size={14} /> Mark all read</button>
                    <button className="btn btn-primary" onClick={load}><RefreshCw size={14} /> Refresh</button>
                </div>
            </div>

            {/* Filters */}
            <div className="glass-panel filter-bar">
                <label className="filter-toggle">
                    <input type="checkbox" checked={unreadOnly} onChange={e => setUnreadOnly(e.target.checked)} />
                    Unread only
                </label>
                <input className="filter-input" placeholder="Filter by ticker…" value={ticker} onChange={e => setTicker(e.target.value)} />
                <select className="filter-select" value={type} onChange={e => setType(e.target.value)}>
                    <option>All</option>
                    <option>FILING_FOUND</option>
                </select>
                <select className="filter-select" value={limit} onChange={e => setLimit(Number(e.target.value))}>
                    {[25, 50, 100].map(n => <option key={n} value={n}>Show {n}</option>)}
                </select>
            </div>

            {loading ? (
                <div className="loading"><div className="spinner" /></div>
            ) : notifs.length === 0 ? (
                <div className="glass-panel empty-state">No notifications match your filters.</div>
            ) : (
                <div className="notif-list">
                    {notifs.map(n => (
                        <div key={n.id} className={`glass-panel notif-card${!n.is_read ? ' unread' : ''}`}>
                            <div className="notif-header">
                                <span className="ticker-badge">{n.ticker}</span>
                                <span className="notif-title">{n.title}</span>
                                {!n.is_read && <span className="new-pill">NEW</span>}
                                <span className="notif-time">{timeAgo(n.created_at)}</span>
                            </div>
                            <p className="notif-body">{n.body}</p>
                            <div className="notif-meta">
                                <span>{n.notification_type}</span>
                                <span>·</span>
                                <span className="accession">{n.accession_number}</span>
                                {!n.is_read && (
                                    <button className="btn-inline" onClick={() => doMarkOne(n.id)}>Mark read</button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
