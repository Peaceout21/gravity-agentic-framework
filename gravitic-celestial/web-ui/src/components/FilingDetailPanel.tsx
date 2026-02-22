import { useEffect, useState } from 'react';
import { X, ExternalLink, Loader, FileText } from 'lucide-react';
import { fetchFiling, runQuery, type Filing } from '../api/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function FilingDetailPanel({ accession, onClose }: { accession: string | null; onClose: () => void }) {
    const [filing, setFiling] = useState<Filing | null>(null);
    const [summary, setSummary] = useState<string>('');
    const [loading, setLoading] = useState(false);
    const [summaryLoading, setSummaryLoading] = useState(false);

    useEffect(() => {
        if (!accession) return;
        setLoading(true);
        setSummary('');
        setFiling(null);

        fetchFiling(accession).then(f => {
            setFiling(f);
            setLoading(false);
            if (f && f.status === 'ANALYZED') {
                setSummaryLoading(true);
                runQuery('Provide a concise 3-bullet summary of the most important updates in the latest filing.', f.ticker)
                    .then(res => setSummary(res.answer_markdown))
                    .catch(() => setSummary('Failed to generate summary.'))
                    .finally(() => setSummaryLoading(false));
            }
        }).catch(() => setLoading(false));
    }, [accession]);

    if (!accession) return null;

    return (
        <div className="drilldown-overlay" onClick={onClose}>
            <div className="drilldown-panel" onClick={e => e.stopPropagation()}>
                <div className="panel-header">
                    <h2>Filing Details</h2>
                    <button className="btn-icon" onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}><X size={18} /></button>
                </div>

                <div className="panel-content">
                    {loading ? (
                        <div className="loading"><Loader className="spinner" size={24} /></div>
                    ) : !filing ? (
                        <div className="empty-state">Filing not found.</div>
                    ) : (
                        <>
                            <div className="glass-panel metric-card" style={{ background: 'rgba(88, 101, 242, 0.1)', borderColor: 'rgba(88, 101, 242, 0.2)' }}>
                                <div className="metric-card-top">
                                    <span className="metric-label">Accession Number</span>
                                    <span className="health-dot ok"></span>
                                </div>
                                <div className="metric-value" style={{ fontSize: '1.25rem' }}>{filing.accession_number}</div>
                                <div className="text-muted small" style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                                    <span className="ticker-badge">{filing.ticker}</span>
                                    <span>• {filing.market}</span>
                                </div>
                            </div>

                            {filing.filing_url && (
                                <a href={filing.filing_url} target="_blank" rel="noreferrer" className="btn btn-primary" style={{ display: 'inline-flex', marginTop: '1.5rem', textDecoration: 'none', width: '100%', justifyContent: 'center' }}>
                                    <ExternalLink size={14} style={{ marginRight: '0.5rem' }} /> View Source Document
                                </a>
                            )}

                            <h3 className="section-title" style={{ marginTop: '2.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}><FileText size={16} /> AI Summary</h3>
                            {summaryLoading ? (
                                <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'var(--text-muted)' }}>
                                    <Loader className="spinner" size={16} /> Distilling filing insights...
                                </div>
                            ) : summary ? (
                                <div className="ai-answer glass-panel" style={{ padding: '1.5rem', fontSize: '0.9rem', lineHeight: 1.6 }}>
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
                                </div>
                            ) : (
                                <div className="glass-panel empty-state">No summary available. Filing may not be fully analyzed or RAG failed to retrieve context.</div>
                            )}

                            {filing.status !== 'ANALYZED' && (
                                <div className="error-msg" style={{ marginTop: '2rem' }}>
                                    Pipeline Status: <strong>{filing.status}</strong>
                                    {filing.last_error && <p className="small text-muted" style={{ marginTop: '0.5rem' }}>{filing.last_error}</p>}
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
