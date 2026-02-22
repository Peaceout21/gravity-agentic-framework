import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Send, X } from 'lucide-react';
import { fetchTemplates, runQuery, runTemplate, fetchTickerCount, fetchAskHistory } from '../api/client';
import type { AskTemplate, HistoryEntry } from '../api/client';

const PERIODS = ['Latest quarter', 'Last two quarters', 'Latest annual', 'Trailing twelve months'];


function ConfidenceBadge({ confidence }: { confidence: number }) {
    if (typeof confidence !== 'number' || isNaN(confidence)) return <span className="conf-badge conf-low">Confidence: Low</span>;
    const pct = Math.round(confidence * 100);
    const cls = confidence >= 0.7 ? 'conf-high' : confidence >= 0.4 ? 'conf-med' : 'conf-low';
    return <span className={`conf-badge ${cls}`}>Confidence: {pct}%</span>;
}

function AnswerCard({ entry, onClose }: { entry: HistoryEntry; onClose?: () => void }) {
    return (
        <div className="glass-panel answer-card animate-in">
            <div className="answer-header">
                <div>
                    {entry.ticker && <span className="ticker-badge">{entry.ticker}</span>}
                    <span className="answer-question">{entry.question}</span>
                </div>
                {onClose && <button className="btn-icon" onClick={onClose}><X size={14} /></button>}
            </div>
            {entry.relevance_label && <p className="answer-meta">{entry.relevance_label}{entry.coverage_brief ? ` · ${entry.coverage_brief}` : ''}</p>}
            <ConfidenceBadge confidence={entry.confidence} />
            {entry.confidence < 0.4 && <div className="conf-warning">⚠ Low confidence — verify against source filings</div>}
            {entry.derivation_trace?.length > 0 && (
                <details className="derivation">
                    <summary>How this was derived</summary>
                    <ul>{entry.derivation_trace.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </details>
            )}
            <div className="answer-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.answer_markdown}</ReactMarkdown>
            </div>
            {entry.citations?.length > 0 && (
                <p className="answer-citations">Sources: {entry.citations.join(', ')}</p>
            )}
        </div>
    );
}

export function AskPage() {
    const [tab, setTab] = useState<'templates' | 'freeform'>('freeform');
    const [templates, setTemplates] = useState<AskTemplate[]>([]);
    const [templateId, setTemplateId] = useState<number | null>(null);
    const [templateTicker, setTemplateTicker] = useState('');
    const [period, setPeriod] = useState(PERIODS[0]);
    const [question, setQuestion] = useState('');
    const [ticker, setTicker] = useState('');
    const [history, setHistory] = useState<HistoryEntry[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [tickerCount, setTickerCount] = useState<number | null>(null);
    const [templateTickerCount, setTemplateTickerCount] = useState<number | null>(null);
    const bottomRef = useRef<HTMLDivElement>(null);

    useEffect(() => { fetchTemplates().then(setTemplates); }, []);
    useEffect(() => { fetchAskHistory().then(setHistory); }, []);
    useEffect(() => { if (templates.length && !templateId) setTemplateId(templates[0].id); }, [templates]);
    useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [history]);

    useEffect(() => {
        const t = ticker.trim();
        if (!t) { setTickerCount(null); return; }
        const timer = setTimeout(() => { fetchTickerCount(t).then(setTickerCount); }, 600);
        return () => clearTimeout(timer);
    }, [ticker]);

    useEffect(() => {
        const t = templateTicker.trim();
        if (!t) { setTemplateTickerCount(null); return; }
        const timer = setTimeout(() => { fetchTickerCount(t).then(setTemplateTickerCount); }, 600);
        return () => clearTimeout(timer);
    }, [templateTicker]);

    const selectedTemplate = templates.find(t => t.id === templateId);

    const doRunTemplate = async () => {
        if (!templateId) return;
        setLoading(true); setError('');
        try {
            const params: Record<string, string> = {};
            if (period !== PERIODS[0]) params['period'] = period.toLowerCase();
            const result = await runTemplate(templateId, templateTicker.trim() || undefined, Object.keys(params).length ? params : undefined);
            setHistory(prev => [...prev, { ...result, question: selectedTemplate?.title || 'Template', ticker: templateTicker.trim().toUpperCase() || undefined }]);
        } catch (e: any) { setError(e.response?.data?.detail || 'Template run failed'); }
        setLoading(false);
    };

    const doAsk = async () => {
        if (!question.trim()) return;
        setLoading(true); setError('');
        try {
            const result = await runQuery(question.trim(), ticker.trim() || undefined);
            setHistory(prev => [...prev, { ...result, question: question.trim(), ticker: ticker.trim().toUpperCase() || undefined }]);
            setQuestion('');
        } catch (e: any) { setError(e.response?.data?.detail || 'Query failed'); }
        setLoading(false);
    };

    return (
        <div className="page animate-in">
            <div className="page-header">
                <div>
                    <h1>Ask about Filings</h1>
                    <p className="page-subtitle">AI-powered answers with citations from analysed filings</p>
                </div>
                {history.length > 0 && <button className="btn btn-ghost" onClick={() => setHistory([])}>Clear history</button>}
            </div>

            {/* Tabs */}
            <div className="tab-bar">
                <button className={`tab-btn${tab === 'freeform' ? ' active' : ''}`} onClick={() => setTab('freeform')}>Freeform Q&amp;A</button>
                <button className={`tab-btn${tab === 'templates' ? ' active' : ''}`} onClick={() => setTab('templates')}>Templates</button>
            </div>

            {/* Input area */}
            <div className="glass-panel section-card">
                {tab === 'freeform' ? (
                    <>
                        <textarea
                            className="field-textarea"
                            rows={3}
                            placeholder="What was Microsoft's revenue growth last quarter? How did Apple's margins compare year-over-year?"
                            value={question}
                            onChange={e => setQuestion(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) doAsk(); }}
                        />
                        <div className="ask-row">
                            <input className="filter-input" placeholder="Ticker context (optional)" value={ticker} onChange={e => setTicker(e.target.value)} />
                            <button className="btn btn-primary" onClick={doAsk} disabled={loading || !question.trim()}>
                                <Send size={14} /> {loading ? 'Analysing…' : 'Ask'}
                            </button>
                        </div>
                        {tickerCount === 0 && (
                            <div className="error-msg" style={{ marginTop: '0.75rem' }}>⚠ No filings indexed for {ticker.toUpperCase()}. Run ingestion first.</div>
                        )}
                    </>
                ) : (
                    <>
                        {templates.length === 0 ? <p className="text-muted">No templates configured.</p> : (
                            <>
                                <div className="two-col-grid">
                                    <div>
                                        <label className="field-label">Template</label>
                                        <select className="filter-select w-full" value={templateId ?? ''} onChange={e => setTemplateId(Number(e.target.value))}>
                                            {templates.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
                                        </select>
                                        {selectedTemplate?.description && <p className="text-muted small mt-1">{selectedTemplate.description}</p>}
                                    </div>
                                    <div>
                                        <label className="field-label">Period</label>
                                        <select className="filter-select w-full" value={period} onChange={e => setPeriod(e.target.value)}>
                                            {PERIODS.map(p => <option key={p}>{p}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div className="ask-row" style={{ marginTop: '0.75rem' }}>
                                    <input className="filter-input" placeholder="Ticker" value={templateTicker} onChange={e => setTemplateTicker(e.target.value)} />
                                    <button className="btn btn-primary" onClick={doRunTemplate} disabled={loading || !templateId}>
                                        <Send size={14} /> {loading ? 'Running…' : 'Run template'}
                                    </button>
                                </div>
                                {templateTickerCount === 0 && (
                                    <div className="error-msg" style={{ marginTop: '0.75rem' }}>⚠ No filings indexed for {templateTicker.toUpperCase()}. Run ingestion first.</div>
                                )}
                            </>
                        )}
                    </>
                )}
                {error && <div className="error-msg">{error}</div>}
            </div>

            {/* History */}
            {history.length === 0 && !loading && (
                <div className="glass-panel section-card" style={{ marginTop: '1.5rem' }}>
                    <h3 className="card-heading">Getting started</h3>
                    <ul className="tips-list">
                        <li>What was Microsoft's revenue last quarter?</li>
                        <li>How did Apple's gross margin compare year-over-year?</li>
                        <li>Summarize the key guidance from the latest GOOG earnings</li>
                        <li>What risks did Tesla highlight in their most recent 10-K?</li>
                    </ul>
                    <p className="text-muted small" style={{ marginTop: '0.75rem' }}>Use Ctrl+Enter (or ⌘+Enter) to submit quickly.</p>
                </div>
            )}

            <div className="answer-list">
                {history.map((entry, i) => (
                    <AnswerCard key={i} entry={entry} onClose={() => setHistory(prev => prev.filter((_, j) => j !== i))} />
                ))}
            </div>
            <div ref={bottomRef} />
        </div>
    );
}
