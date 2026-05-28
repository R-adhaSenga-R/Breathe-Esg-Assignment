import { useState, useCallback } from 'react'
import api from '../api'

const SOURCE_OPTIONS = [
  { value: 'sap',     label: 'SAP Fuel & Procurement',  badge: 'Scope 1' },
  { value: 'utility', label: 'Utility Electricity',     badge: 'Scope 2' },
  { value: 'travel',  label: 'Corporate Travel',        badge: 'Scope 3' },
]

export default function Upload() {
  const [file, setFile]             = useState(null)
  const [sourceType, setSourceType] = useState('sap')
  const [loading, setLoading]       = useState(false)
  const [result, setResult]         = useState(null)
  const [error, setError]           = useState(null)
  const [dragOver, setDragOver]     = useState(false)
  const [recentUploads, setRecentUploads] = useState([]) // { batch_id, filename, rows, timestamp }

  const orgId = 1

  const acceptFile = (f) => {
    if (!f) return
    setFile(f)
    setResult(null)
    setError(null)
  }

  // Drag and drop handlers
  const onDragOver = useCallback((e) => {
    e.preventDefault()
    setDragOver(true)
  }, [])

  const onDragLeave = useCallback(() => {
    setDragOver(false)
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped) acceptFile(dropped)
  }, [])

  const handleUpload = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)

    const formData = new FormData()
    formData.append('file', file)
    formData.append('source_type', sourceType)
    formData.append('org_id', orgId)

    try {
      const res = await api.post('/upload/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(res.data)

      if (res.data.success) {
        setRecentUploads(prev => [
          {
            batch_id  : res.data.batch_id,
            filename  : file.name,
            rows      : res.data.rows_normalized,
            source    : sourceType,
            timestamp : new Date().toLocaleTimeString(),
          },
          ...prev.slice(0, 4),   // keep last 5
        ])
        setFile(null)
      }
    } catch (err) {
      const detail = err.response?.data || { error: err.message || 'Upload failed' }
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-6">Upload Data File</h1>

      <div className="bg-white rounded-xl shadow p-6 space-y-5">

        {/* Source type selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Data Source
          </label>
          <div className="grid grid-cols-3 gap-2">
            {SOURCE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setSourceType(opt.value)}
                className={`rounded-lg border p-3 text-left transition ${
                  sourceType === opt.value
                    ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <span className="block text-xs font-semibold text-gray-800">{opt.label}</span>
                <span className={`inline-block mt-1 text-xs px-1.5 py-0.5 rounded font-medium ${
                  opt.value === 'sap'     ? 'bg-red-100 text-red-700' :
                  opt.value === 'utility' ? 'bg-blue-100 text-blue-700' :
                                            'bg-purple-100 text-purple-700'
                }`}>{opt.badge}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Drag-and-drop file zone */}
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={`relative border-2 border-dashed rounded-xl transition ${
            dragOver
              ? 'border-blue-400 bg-blue-50 scale-[1.01]'
              : file
              ? 'border-green-400 bg-green-50'
              : 'border-gray-300 hover:border-blue-300'
          }`}
        >
          <label htmlFor="fileInput" className="block p-10 text-center cursor-pointer">
            <input
              id="fileInput"
              type="file"
              className="hidden"
              accept=".csv,.xlsx,.xls,.json,.jsonl,.pdf,.txt,.ods"
              onChange={e => acceptFile(e.target.files[0])}
            />
            {file ? (
              <div>
                <p className="text-green-700 font-semibold text-base">{file.name}</p>
                <p className="text-green-500 text-sm mt-1">
                  {(file.size / 1024).toFixed(1)} KB · Click to change
                </p>
              </div>
            ) : (
              <div>
                <p className="text-gray-500 text-base">
                  {dragOver ? 'Drop to upload' : 'Drag & drop or click to select'}
                </p>
                <p className="text-gray-400 text-sm mt-1">CSV, Excel, PDF, JSON, ODS</p>
              </div>
            )}
          </label>
        </div>

        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-3 font-semibold
                     hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {loading ? 'Uploading & Parsing…' : 'Upload'}
        </button>
      </div>

      {/* Success result */}
      {result && (
        <div className={`mt-6 rounded-xl p-5 ${
          result.success
            ? 'bg-green-50 border border-green-200'
            : 'bg-red-50 border border-red-200'
        }`}>
          <p className="font-bold text-lg mb-2">
            {result.success ? '✅ Upload Successful' : '❌ Upload Failed'}
          </p>
          <p className="text-sm">Rows parsed: <strong>{result.rows_parsed}</strong></p>
          <p className="text-sm">Rows normalised: <strong>{result.rows_normalized}</strong></p>

          {result.duplicate_warning && (
            <p className="mt-2 text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2 border border-amber-200">
              ⚠️ {result.duplicate_warning}
            </p>
          )}

          {result.warnings?.length > 0 && (
            <div className="mt-3">
              <p className="font-medium text-yellow-800 text-sm">Warnings:</p>
              <ul className="list-disc list-inside text-sm text-yellow-700 mt-1">
                {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {result.success && (
            <a
              href={`/?batch_id=${result.batch_id}`}
              className="inline-block mt-3 text-sm text-blue-600 hover:underline font-medium"
            >
              View batch #{result.batch_id} in dashboard →
            </a>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mt-6 bg-red-50 border border-red-200 rounded-xl p-5">
          <p className="font-bold text-red-800 mb-2">Upload Error</p>
          <pre className="text-sm text-red-700 whitespace-pre-wrap">
            {JSON.stringify(error, null, 2)}
          </pre>
        </div>
      )}

      {/* Recent uploads */}
      {recentUploads.length > 0 && (
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-gray-600 mb-3 uppercase tracking-wide">
            Recent Uploads (this session)
          </h2>
          <div className="space-y-2">
            {recentUploads.map((u, i) => (
              <div key={i} className="flex items-center justify-between bg-white rounded-xl px-4 py-3 shadow-sm border text-sm">
                <div>
                  <span className="font-medium text-gray-800">{u.filename}</span>
                  <span className="ml-2 text-gray-400 text-xs">{u.timestamp}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-gray-500">{u.rows} records</span>
                  <a
                    href={`/?batch_id=${u.batch_id}`}
                    className="text-blue-500 hover:underline text-xs"
                  >
                    View →
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
