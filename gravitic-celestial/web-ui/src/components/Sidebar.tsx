import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Bell, Bookmark, MessageSquare, Server } from 'lucide-react';

const links = [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/notifications', label: 'Notifications', icon: Bell },
    { to: '/watchlist', label: 'Watchlist', icon: Bookmark },
    { to: '/ask', label: 'Ask', icon: MessageSquare },
    { to: '/ops', label: 'Ops', icon: Server },
];

export const Sidebar: React.FC<{ unread: number }> = ({ unread }) => (
    <aside className="sidebar">
        <div className="sidebar-brand">
            <span className="brand-icon">G</span>
            <span className="brand-name">Gravity</span>
        </div>
        <nav className="sidebar-nav">
            {links.map(({ to, label, icon: Icon }) => (
                <NavLink
                    key={to}
                    to={to}
                    end={to === '/'}
                    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                >
                    <Icon size={18} />
                    <span>{label}</span>
                    {label === 'Notifications' && unread > 0 && (
                        <span className="unread-pill">{unread}</span>
                    )}
                </NavLink>
            ))}
        </nav>
        <div className="sidebar-footer">
            <span className="sidebar-version">v2.0 · SEA + US</span>
        </div>
    </aside>
);
