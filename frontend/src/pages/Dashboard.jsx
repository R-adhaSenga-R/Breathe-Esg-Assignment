import { useState, useEffect, useCallback } from 'react'
import api from '../api'

const SCOPE_LABELS = {
  scope1: { label: 'Scope 1 — Fuel',        color: 'bg-red-100 text-red-700' },
  scope2: { label: 'Scope 2 — Electricity', color: 'bg-blue-100 text-blue-700' },
  scope3: { label: 'Scope 3 — Travel',      color: 'bg-purple-100 text-purple-700' },
}
const STATUS_COLORS = {
  pending:  'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
  flagged:  'bg-orange-100 text-orange-700',
}

// ── Raw Data Drill-Down Modal ──────────────────────────────────────────────────
function RawDataModal({ recordId, onClose }) {
  const [raw, setRaw]       = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/records/${recordId}/raw/`)
      .then(res => setRaw(res.data))
      .catch(() => setRaw({ error: 'Could not load raw data.' }))
      .finally(() => setLoading(false))
  }, [recordId])

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="text-lg font-bold">Raw Source Data</h2>
            {raw && !raw.error && (
              <p className="text-xs text-gray-500 mt-0.5">
                Record #{raw.raw_id} · Row {raw.row_index} · {raw.source_type}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-2xl leading-none"
          >
            ×
          </button>
        </div>
        <div className="overflow-auto p-6 flex-1">
          {loading && <p className="text-gray-400 text-center py-8">Loading…</p>}
          {!loading && raw && (
            <pre className="text-xs bg-gray-50 rounded-xl p-4 whitespace-pre-wrap break-all font-mono">
              {JSON.stringify(raw.raw_data, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Review Comment Modal ───────────────────────────────────────────────────────
function ReviewModal({ recordId, action, onClose, onSubmit }) {
  const [comment, setComment] = useState('')
  const actionColors = {
    approved: 'bg-green-600 hover:bg-green-700',
    rejected: 'bg-red-600 hover:bg-red-700',
    flagged:  'bg-orange-500 hover:bg-orange-600',
  }
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
        <h2 className="text-lg font-bold mb-1 capitalize">{action} Record</h2>
        <p className="text-sm text-gray-500 mb-4">Add an optional comment for the audit trail.</p>
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Reason or note (optional)…"
          className="w-full border rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-400"
          rows={3}
          autoFocus
        />
        <div className="flex gap-2 mt-4">
          <button
            onClick={() => onSubmit(recordId, action, comment)}
            className={`flex-1 text-white rounded-lg py-2 text-sm font-semibold ${actionColors[action]}`}
          >
            Confirm {action}
          </button>
          <button
            onClick={onClose}
            className="flex-1 border rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [records, setRecords]     = useState([])
  const [summary, setSummary]     = useState(null)
  const [filters, setFilters]     = useState({ scope: '', status: '' })
  const [selected, setSelected]   = useState(new Set())
  const [loading, setLoading]     = useState(false)
  const [pagination, setPagination] = useState({ count: 0, next: null, previous: null, page: 1 })
  const [drilldownId, setDrilldownId] = useState(null)
  const [reviewModal, setReviewModal] = useState(null) // { recordId, action }

  const fetchRecords = useCallback(async (page = 1) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ org_id: 1, page, ...filters })
      const res = await api.get(`/records/?${params}`)
      setRecords(res.data.results || [])
      setPagination(prev => ({
        ...prev,
        count:    res.data.count    || 0,
        next:     res.data.next,
        previous: res.data.previous,
        page,
      }))
    } catch (err) {
      console.error('Error fetching records:', err)
    } finally {
      setLoading(false)
    }
  }, [filters])

  const fetchSummary = useCallback(async () => {
    try {
      const res = await api.get('/summary/?org_id=1')
      setSummary(res.data)
    } catch (err) {
      console.error('Error fetching summary:', err)
    }
  }, [])

  useEffect(() => {
    fetchRecords(1)
    fetchSummary()
  }, [filters])

  const submitReview = async (id, status, comment = '') => {
    await api.post(`/records/${id}/review/`, { status, comment })
    setReviewModal(null)
    fetchRecords(pagination.page)
    fetchSummary()
  }

  const bulkReview = async (status) => {
    await api.post('/records/bulk-review/', { record_ids: [...selected], status })
    setSelected(new Set())
    fetchRecords(pagination.page)
    fetchSummary()
  }

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const pageStart = (pagination.page - 1) * 50 + 1
  const pageEnd   = Math.min(pagination.page * 50, pagination.count)

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {drilldownId && (
        <RawDataModal recordId={drilldownId} onClose={() => setDrilldownId(null)} />
      )}
      {reviewModal && (
        <ReviewModal
          recordId={reviewModal.recordId}
          action={reviewModal.action}
          onClose={() => setReviewModal(null)}
          onSubmit={submitReview}
        />
      )}

      <h1 className="text-2xl font-bold mb-6">Review Dashboard</h1>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Total CO₂e', value: `${((summary.co2e_summary.total_co2e||0)/1000).toFixed(1)} tCO₂e`, color: 'bg-gray-800 text-white' },
            { label: 'Scope 1',    value: `${((summary.co2e_summary.scope1_co2e||0)/1000).toFixed(1)} t`,    color: 'bg-red-600 text-white' },
            { label: 'Scope 2',    value: `${((summary.co2e_summary.scope2_co2e||0)/1000).toFixed(1)} t`,    color: 'bg-blue-600 text-white' },
            { label: 'Scope 3',    value: `${((summary.co2e_summary.scope3_co2e||0)/1000).toFixed(1)} t`,    color: 'bg-purple-600 text-white' },
          ].map(c => (
            <div key={c.label} className={`rounded-xl p-5 ${c.color}`}>
              <p className="text-sm opacity-80">{c.label}</p>
              <p className="text-2xl font-bold">{c.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters + bulk actions */}
      <div className="flex flex-wrap gap-3 mb-4 items-center">
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

        {/* Record count */}
        {!loading && pagination.count > 0 && (
          <span className="text-sm text-gray-500 ml-1">
            Showing {pageStart}–{pageEnd} of {pagination.count.toLocaleString()} records
          </span>
        )}

        {selected.size > 0 && (
          <div className="flex gap-2 ml-auto">
            <span className="text-sm text-gray-600 self-center">{selected.size} selected</span>
            <button onClick={() => bulkReview('approved')}
              className="bg-green-600 text-white px-3 py-1 rounded text-sm hover:bg-green-700">
              Approve All
            </button>
            <button onClick={() => bulkReview('rejected')}
              className="bg-red-600 text-white px-3 py-1 rounded text-sm hover:bg-red-700">
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
              <th className="p-3 w-8">
                <input type="checkbox" onChange={e =>
                  setSelected(e.target.checked ? new Set(records.map(r => r.id)) : new Set())
                } />
              </th>
              <th className="p-3 text-left">Scope</th>
              <th className="p-3 text-left">Date</th>
              <th className="p-3 text-left">Site / Detail</th>
              <th className="p-3 text-right">Qty (normalised)</th>
              <th className="p-3 text-right">CO₂e (kg)</th>
              <th className="p-3 text-center">Status</th>
              <th className="p-3 text-center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={8} className="text-center py-12 text-gray-400">Loading…</td>
              </tr>
            )}

            {/* Empty state */}
            {!loading && records.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center py-16">
                  <p className="text-gray-400 text-base">No records found</p>
                  <p className="text-gray-300 text-sm mt-1">
                    {filters.scope || filters.status
                      ? 'Try clearing the filters above'
                      : 'Upload a data file to get started'}
                  </p>
                </td>
              </tr>
            )}

            {!loading && records.map(rec => (
              <tr
                key={rec.id}
                className="border-b hover:bg-gray-50 cursor-pointer"
                onClick={() => setDrilldownId(rec.id)}
                title="Click to view raw source data"
              >
                <td className="p-3" onClick={e => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected.has(rec.id)}
                    onChange={() => toggleSelect(rec.id)}
                  />
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
                <td className="p-3 text-right font-mono text-xs text-gray-500">
                  {rec.quantity_normalized
                    ? `${Number(rec.quantity_normalized).toLocaleString()} ${rec.quantity_normalized_unit || ''}`
                    : '—'}
                </td>
                <td className="p-3 text-right font-mono">
                  {rec.co2e_kg ? Number(rec.co2e_kg).toFixed(2) : '—'}
                </td>
                <td className="p-3 text-center">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[rec.review_status]}`}>
                    {rec.review_status}
                  </span>
                </td>
                <td className="p-3 text-center" onClick={e => e.stopPropagation()}>
                  {rec.review_status === 'pending' && (
                    <div className="flex gap-1 justify-center">
                      <button
                        onClick={() => setReviewModal({ recordId: rec.id, action: 'approved' })}
                        className="bg-green-100 text-green-700 px-2 py-1 rounded text-xs hover:bg-green-200"
                        title="Approve"
                      >✓</button>
                      <button
                        onClick={() => setReviewModal({ recordId: rec.id, action: 'flagged' })}
                        className="bg-orange-100 text-orange-700 px-2 py-1 rounded text-xs hover:bg-orange-200"
                        title="Flag for review"
                      >⚑</button>
                      <button
                        onClick={() => setReviewModal({ recordId: rec.id, action: 'rejected' })}
                        className="bg-red-100 text-red-700 px-2 py-1 rounded text-xs hover:bg-red-200"
                        title="Reject"
                      >✗</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pagination.count > 50 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <button
            disabled={!pagination.previous}
            onClick={() => fetchRecords(pagination.page - 1)}
            className="px-4 py-2 border rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
          >
            ← Previous
          </button>
          <span className="text-gray-500">
            Page {pagination.page} of {Math.ceil(pagination.count / 50)}
          </span>
          <button
            disabled={!pagination.next}
            onClick={() => fetchRecords(pagination.page + 1)}
            className="px-4 py-2 border rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}
