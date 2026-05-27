// File: frontend/src/App.jsx
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import Upload from './pages/Upload'
import Dashboard from './pages/Dashboard'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-white border-b px-8 py-4 flex gap-6 items-center shadow-sm">
          <span className="font-bold text-gray-800 text-lg">🌱 Breathe ESG</span>
          <Link to="/"         className="text-sm text-gray-600 hover:text-blue-600">Upload</Link>
          <Link to="/dashboard" className="text-sm text-gray-600 hover:text-blue-600">Review Dashboard</Link>
        </nav>
        <main className="py-8">
          <Routes>
            <Route path="/"          element={<Upload />} />
            <Route path="/dashboard" element={<Dashboard />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}