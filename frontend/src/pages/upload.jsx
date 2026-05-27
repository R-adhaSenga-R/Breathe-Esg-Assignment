// File: frontend/src/pages/Upload.jsx
import { useState } from 'react'
import api from '../api'

export default function Upload() {
  const [file, setFile]           = useState(null)
  const [sourceType, setSourceType] = useState('sap')
  const [loading, setLoading]     = useState(false)
  const [result, setResult]       = useState(null)
  const [error, setError]         = useState(null)

  const orgId = 1 // Active organization ID

  const handleUpload = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)

    const formData = new FormData()
    formData.append('file', file)
    formData.append('source_type', sourceType)
    formData.append('org_id', orgId)

    console.log('Sending upload with org_id:', orgId, 'source_type:', sourceType)

    try {
      const res = await fetch('http://localhost:8000/api/upload/', {
        method: 'POST',
        credentials: 'include',   // 👈 needed for session auth
        body: formData,
      })

      console.log('Response status:', res.status)   // 400? 403? 404? 500?
      const data = await res.json()
      console.log('Response body:', data)           // full error detail here

      if (!res.ok) {
        setError(data)
        return
      }
      setResult(data)
    } catch (err) {
      console.error('Network/fetch error:', err)
      setError({ error: err.message || 'Network or fetch error occurred' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-6">Upload Data File</h1>

      <div className="bg-white rounded-xl shadow p-6 space-y-4">
        {/* Source type selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Data Source
          </label>
          <select
            value={sourceType}
            onChange={e => setSourceType(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="sap">SAP Fuel & Procurement (Scope 1)</option>
            <option value="utility">Utility Electricity (Scope 2)</option>
            <option value="travel">Corporate Travel (Scope 3)</option>
          </select>
        </div>

        {/* File drop zone */}
        {/* Replace the entire drop zone div with this */}
<label
  htmlFor="fileInput"
  className="block border-2 border-dashed border-gray-300 rounded-xl p-10 text-center cursor-pointer hover:border-blue-400 transition"
>
  <input
    id="fileInput"
    type="file"
    className="hidden"
    accept=".csv,.xlsx,.xls,.json,.jsonl,.pdf,.txt,.ods"
    onChange={e => {
      console.log('File selected:', e.target.files[0])   // confirm in browser console
      setFile(e.target.files[0])
    }}
  />
  {file
    ? <p className="text-green-600 font-medium">{file.name}</p>
    : <p className="text-gray-500">Click to select file<br/>
        <span className="text-sm">CSV, Excel, PDF, JSON, ODS supported</span>
      </p>
  }
</label>

        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-3 font-semibold
                     hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Uploading & Parsing…' : 'Upload'}
        </button>
      </div>

      {/* Result */}
      {result && (
        <div className={`mt-6 rounded-xl p-5 ${result.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
          <p className="font-bold text-lg mb-2">
            {result.success ? '✅ Upload Successful' : '❌ Upload Failed'}
          </p>
          <p>Rows parsed: <strong>{result.rows_parsed}</strong></p>
          <p>Rows normalized: <strong>{result.rows_normalized}</strong></p>
          {result.warnings?.length > 0 && (
            <div className="mt-3">
              <p className="font-medium text-yellow-800">Warnings:</p>
              <ul className="list-disc list-inside text-sm text-yellow-700">
                {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-6 bg-red-50 border border-red-200 rounded-xl p-5">
          <p className="font-bold text-red-800">Error</p>
          <pre className="text-sm text-red-700 mt-2">
            {JSON.stringify(error, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}