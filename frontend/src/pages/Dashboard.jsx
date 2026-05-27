// File: frontend/src/pages/Dashboard.jsx
import { useState, useEffect } from 'react'
import api from '../api'

const SCOPE_LABELS = {
  scope1: { label: 'Scope 1 — Fuel', color: 'bg-red-100 text-red-700' },
  scope2: { label: 'Scope 2 — Electricity', color: 'bg-blue-100 text-blue-700' },
  scope3: { label: 'Scope 3 — Travel', color: 'bg-purple-100 text-purple-700' },
}
const STATUS_COLORS = {
  pending:  'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
  flagged:  'bg-orange-100 text-orange-700',
}

export default function Dashboard() {
  const [records, setRecords]   = useState([])
  const [summary, setSummary]   = useState(null)
  const [filters, setFilters]   = useState({ scope: '', status: '' })
  const [selected, setSelected] = useState(new Set())
  const [loading, setLoading]   = useState(false)

  const fetchRecords = async () => {
    setLoading(true)
    const params = new URLSearchParams({ org_id: 1, ...filters })
    const res = await api.get(`/records/?${params}`)
    setRecords(res.data.results || [])
    setLoading(false)
  }

  const fetchSummary = async () => {
    const res = await api.get('/summary/?org_id=1')
    setSummary(res.data)
  }

  useEffect(() => { fetchRecords(); fetchSummary() }, [filters])

  const reviewOne = async (id, status) => {
    await api.post(`/records/${id}/review/`, { status })
    fetchRecords()
    fetchSummary()
  }

  const bulkReview = async (status) => {
    await api.post('/records/bulk-review/', {
      record_ids: [...selected], status
    })
    setSelected(new Set())
    fetchRecords()
    fetchSummary()
  }

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Review Dashboard</h1>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Total CO₂e', value: `${(summary.co2e_summary.total_co2e/1000).toFixed(1)} tCO₂e`, color: 'bg-gray-800 text-white' },
            { label: 'Scope 1', value: `${((summary.co2e_summary.scope1_co2e||0)/1000).toFixed(1)} t`, color: 'bg-red-600 text-white' },
            { label: 'Scope 2', value: `${((summary.co2e_summary.scope2_co2e||0)/1000).toFixed(1)} t`, color: 'bg-blue-600 text-white' },
            { label: 'Scope 3', value: `${((summary.co2e_summary.scope3_co2e||0)/1000).toFixed(1)} t`, color: 'bg-purple-600 text-white' },
          ].map(c => (
            <div key={c.label} className={`rounded-xl p-5 ${c.color}`}>
              <p className="text-sm opacity-80">{c.label}</p>
              <p className="text-2xl font-bold">{c.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select
          value={filters.scope}
          onChange={e => setFilters(f => ({ ...f, scope: e.target.value }))}
          className="border rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Scopes</option>
          <option value="scope1">Scope 1</option>
          <option value="scope2">Scope 2</option>
          <option value="scope3">Scope 3</option>
        </select>
        <select
          value={filters.status}
          onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}
          className="border rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="flagged">Flagged</option>
        </select>

        {selected.size > 0 && (
          <div className="flex gap-2 ml-auto">
            <span className="text-sm text-gray-600 self-center">{selected.size} selected</span>
            <button onClick={() => bulkReview('approved')}
              className="bg-green-600 text-white px-3 py-1 rounded text-sm">
              Approve All
            </button>
            <button onClick={() => bulkReview('rejected')}
              className="bg-red-600 text-white px-3 py-1 rounded text-sm">
              Reject All
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="p-3 w-8"><input type="checkbox" onChange={e =>
                setSelected(e.target.checked ? new Set(records.map(r=>r.id)) : new Set())
              }/></th>
              <th className="p-3 text-left">Scope</th>
              <th className="p-3 text-left">Date</th>
              <th className="p-3 text-left">Site / Detail</th>
              <th className="p-3 text-right">CO₂e (kg)</th>
              <th className="p-3 text-center">Status</th>
              <th className="p-3 text-center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">Loading…</td></tr>
            )}
            {!loading && records.map(rec => (
              <tr key={rec.id} className="border-b hover:bg-gray-50">
                <td className="p-3">
                  <input type="checkbox" checked={selected.has(rec.id)}
                    onChange={() => toggleSelect(rec.id)} />
                </td>
                <td className="p-3">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${SCOPE_LABELS[rec.scope]?.color}`}>
                    {SCOPE_LABELS[rec.scope]?.label}
                  </span>
                </td>
                <td className="p-3 text-gray-600">{rec.activity_date || '—'}</td>
                <td className="p-3">
                  {rec.scope === 'scope1' && <span>{rec.fuel_type} · {rec.site_name}</span>}
                  {rec.scope === 'scope2' && <span>{rec.meter_id} · {rec.site_name}</span>}
                  {rec.scope === 'scope3' && <span>{rec.travel_type} · {rec.origin}→{rec.destination}</span>}
                </td>
                <td className="p-3 text-right font-mono">
                  {rec.co2e_kg ? Number(rec.co2e_kg).toFixed(2) : '—'}
                </td>
                <td className="p-3 text-center">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[rec.review_status]}`}>
                    {rec.review_status}
                  </span>
                </td>
                <td className="p-3 text-center">
                  {rec.review_status === 'pending' && (
                    <div className="flex gap-1 justify-center">
                      <button onClick={() => reviewOne(rec.id, 'approved')}
                        className="bg-green-100 text-green-700 px-2 py-1 rounded text-xs hover:bg-green-200">
                        ✓
                      </button>
                      <button onClick={() => reviewOne(rec.id, 'flagged')}
                        className="bg-orange-100 text-orange-700 px-2 py-1 rounded text-xs hover:bg-orange-200">
                        ⚑
                      </button>
                      <button onClick={() => reviewOne(rec.id, 'rejected')}
                        className="bg-red-100 text-red-700 px-2 py-1 rounded text-xs hover:bg-red-200">
                        ✗
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}