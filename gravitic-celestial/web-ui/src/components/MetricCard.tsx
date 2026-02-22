import React from 'react';

interface MetricCardProps {
    title: string;
    value: string | number;
    subtitle?: string;
    colorCombo?: 'primary' | 'success' | 'warning' | 'danger' | 'sea' | 'neutral';
}

export const MetricCard: React.FC<MetricCardProps> = ({ title, value, subtitle, colorCombo = 'primary' }) => (
    <div className={`glass-panel metric-card ${colorCombo}`}>
        <div className="metric-label">{title}</div>
        <div className="metric-value">{value}</div>
        {subtitle && <div className="metric-subtitle">{subtitle}</div>}
    </div>
);
