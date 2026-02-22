import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { DashboardPage } from './pages/DashboardPage'
import { NotificationsPage } from './pages/NotificationsPage'
import { WatchlistPage } from './pages/WatchlistPage'
import { AskPage } from './pages/AskPage'
import { OpsPage } from './pages/OpsPage'
import { fetchUnreadCount } from './api/client'

function App() {
  const [unread, setUnread] = useState(0)
  useEffect(() => {
    fetchUnreadCount().then(setUnread)
    const interval = setInterval(() => fetchUnreadCount().then(setUnread), 30000)
    return () => clearInterval(interval)
  }, [])

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar unread={unread} />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/ops" element={<OpsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
