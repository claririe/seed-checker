import { useState, useEffect, useRef } from "react"

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:5001"

const STATUS_COLORS = {
  GOOD: { bg: "#1a2e1a", text: "#4ade80", border: "#2d4a2d" },
  LIAR: { bg: "#2e1a1a", text: "#f87171", border: "#4a2d2d" },
  REVIEW: { bg: "#2a2618", text: "#fbbf24", border: "#44391f" },
}

function normalizeSeedTime(value) {
  const str = String(value || "").trim()
  if (!str) return null
  if (/^\d+$/.test(str)) {
    return `${parseInt(str, 10)}:00`
  }

  const parts = str.split(":").map(part => part.trim())
  if (parts.length < 2 || parts.length > 3 || parts.some(part => !/^\d+$/.test(part))) {
    return null
  }

  const nums = parts.map(part => parseInt(part, 10))
  if (nums.some(Number.isNaN)) return null

  if (parts.length === 3) {
    const [h, m, s] = nums
    if (m > 59 || s > 59) return null
    return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`
  }

  const [left, right] = nums
  if (right > 59) return null
  if (left <= 3 && parts[0].length === 1) {
    return `${left}:${String(right).padStart(2, "0")}:00`
  }
  return `${left}:${String(right).padStart(2, "0")}`
}

function fmtDisplay(t) {
  if (!t) return "—"
  return String(t).replace(/^0:/, "").replace(/^00:/, "")
}

function seedDisplay(t) {
  if (!t) return ""
  return fmtDisplay(t)
}

function locationStr(p) {
  if (p.city && p.state) return `${p.city}, ${p.state}`
  return p.city || p.state || "—"
}

export default function App() {
  const [participants, setParticipants] = useState([])
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importState, setImportState] = useState(null)
  const [resultsStatus, setResultsStatus] = useState({})
  const [leeway, setLeeway] = useState("300")
  const [leewayInput, setLeewayInput] = useState("300")
  const [filter, setFilter] = useState("ALL")
  const [enriched, setEnriched] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null)
  const fileRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => {
    fetch(`${API}/results-status`).then(r => r.json()).then(setResultsStatus).catch(() => { })
    fetch(`${API}/settings`).then(r => r.json()).then(d => {
      if (d.leeway_seconds) { setLeeway(d.leeway_seconds); setLeewayInput(d.leeway_seconds) }
    }).catch(() => { })
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  function loadParticipants() {
    setLoading(true)
    fetch(`${API}/participants`)
      .then(r => r.json())
      .then(data => { setParticipants(data); setLoading(false) })
      .catch(() => setLoading(false))
  }

  function handleUpload(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploadMsg("uploading...")
    const fd = new FormData()
    fd.append("file", file)
    fetch(`${API}/upload-csv`, { method: "POST", body: fd })
      .then(r => r.json())
      .then(d => { setUploadMsg(`${d.inserted} entries loaded`); setEnriched(false); loadParticipants() })
      .catch(() => setUploadMsg("upload failed"))
    e.target.value = ""
  }

  function handleImport() {
    if (importing) return
    setImporting(true)
    setImportState(null)
    fetch(`${API}/import-results`, { method: "POST" })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setImporting(false); return }
        pollRef.current = setInterval(() => {
          Promise.all([
            fetch(`${API}/import-status`).then(r => r.json()),
            fetch(`${API}/results-status`).then(r => r.json()),
          ]).then(([status, counts]) => {
            setImportState(status)
            setResultsStatus(counts)
            if (!status.running) {
              clearInterval(pollRef.current)
              setImporting(false)
            }
          }).catch(() => { })
        }, 2000)
      })
      .catch(() => setImporting(false))
  }

  function saveLeeway(val) {
    const n = parseInt(val)
    if (isNaN(n) || n < 0) return
    setLeeway(String(n))
    fetch(`${API}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leeway_seconds: String(n) })
    }).catch(() => { })
  }

  function loadEnriched() {
    setEnriched(true); setLoading(true)
    fetch(`${API}/enriched-participants?leeway=${leeway}`)
      .then(r => r.json())
      .then(data => { setParticipants(data); setLoading(false) })
      .catch(() => setLoading(false))
  }

  function updateParticipant(updated) {
    setParticipants(prev => prev.map(p =>
      p.registration_id === updated.registration_id ? { ...p, ...updated } : p
    ))
  }

  const importedYears = Object.keys(resultsStatus).sort().reverse()
  const hasResults = importedYears.length > 0
  const filtered = participants.filter(p => {
    if (filter === "ALL") return true
    if (filter === "OVERRIDDEN") return Boolean(p.override_status)
    return (p.override_status || p.status || "") === filter
  })
  const counts = {
    ALL: participants.length,
    OVERRIDDEN: participants.filter(p => p.override_status).length,
  }
  for (const k of ["GOOD", "LIAR", "REVIEW"]) {
    counts[k] = participants.filter(p => (p.override_status || p.status || "") === k).length
  }

  function importStatusText() {
    if (importing && importState) {
      const { current_year, completed_years, total_years, last_error_detail } = importState
      if (last_error_detail) return `error: ${last_error_detail}`
      return `importing ${current_year || "..."} (${completed_years.length}/${total_years})`
    }
    if (importing) return "starting..."
    if (importState?.errors?.length > 0) {
      const e = importState.errors[0]
      return `failed: ${e.error}`
    }
    if (hasResults) return `${importedYears.join(", ")} imported`
    return "not imported yet"
  }

  const importHasError = !importing && importState?.errors?.length > 0

  return (
    <div className="app">
      <header className="header">
        <div className="header-title">
          <h1>seed checker</h1>
        </div>
        <div className="controls">
          <div className="control-row">

            <div className="control-group">
              <label className="control-label">participants</label>
              <div className="control-items">
                <button className="btn" onClick={() => fileRef.current?.click()}>
                  upload
                </button>
                <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls"
                  onChange={handleUpload} style={{ display: "none" }} />
                {uploadMsg && <span className="status-text">{uploadMsg}</span>}
              </div>
            </div>

            <div className="control-group">
              <label className="control-label">past results</label>
              <div className="control-items">
                <button className="btn" onClick={handleImport} disabled={importing}>
                  {importing ? "importing..." : "import"}
                </button>
                <span className={`status-text ${importHasError ? "save-error" : !hasResults && !importing ? "muted" : ""}`}>
                  {importStatusText()}
                </span>
              </div>
            </div>

            <div className="control-group">
              <label className="control-label">leeway</label>
              <div className="control-items">
                <div className="leeway-wrap">
                  <input className="leeway-input" type="number" value={leewayInput}
                    onChange={e => setLeewayInput(e.target.value)}
                    onBlur={() => saveLeeway(leewayInput)}
                    onKeyDown={e => e.key === "Enter" && saveLeeway(leewayInput)}
                    min="0" />
                  <span className="leeway-unit">sec</span>
                </div>
              </div>
            </div>

            <div className="control-group control-group-action">
              <div className="control-items">
                <button className={`btn ${enriched ? "btn-active" : ""}`}
                  onClick={loadEnriched} disabled={loading}>
                  {loading ? "loading..." : "check"}
                </button>
              </div>
            </div>

          </div>

          {participants.length > 0 && (
            <div className="filter-row">
              {["ALL", "GOOD", "LIAR", "REVIEW", "OVERRIDDEN"].map(f => (
                <button key={f}
                  className={`filter-btn ${filter === f ? "filter-active" : ""} filter-${f}`}
                  onClick={() => setFilter(f)}>
                  {f}<span className="filter-count">{counts[f]}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      <main className="main">
        {loading && <div className="empty">matching entries...</div>}
        {!loading && participants.length === 0 && <div className="empty">upload a participant csv or xlsx</div>}
        {!loading && filtered.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>#</th><th>name</th><th>age</th><th>g</th><th>location</th>
                <th>seed <span className="th-note">H:MM:SS</span></th><th>1st</th>
                {enriched && <><th>status</th><th>past best</th><th>links</th></>}
                <th>runsignup</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
                <ParticipantRow key={`${p.registration_id}-${p.seed_time || ""}`} participant={p}
                  index={i + 1} enriched={enriched} onUpdate={updateParticipant} />
              ))}
            </tbody>
          </table>
        )}
        {!loading && enriched && filtered.length === 0 && participants.length > 0 && (
          <div className="empty">no entries match this filter</div>
        )}
      </main>
    </div>
  )
}

function SeedInput({ value, onChange, onSave }) {
  const [text, setText] = useState(seedDisplay(value))
  const normalized = normalizeSeedTime(text)

  function handleChange(val) {
    if (!/^[\d:]*$/.test(val)) return
    setText(val)
    onChange(val)
  }

  function commitDisplay() {
    if (!normalized) return false
    const display = fmtDisplay(normalized)
    setText(display)
    onChange(normalized)
    return true
  }

  function handleKeyDown(e) {
    if (e.key !== "Enter") return
    if (commitDisplay()) onSave()
  }

  return (
    <input
      className={`seed-input ${text && !normalized ? "seed-invalid" : ""}`}
      value={text}
      onChange={e => handleChange(e.target.value)}
      onBlur={commitDisplay}
      onKeyDown={handleKeyDown}
      placeholder="46:00"
      inputMode="numeric"
    />
  )
}

function ParticipantRow({ participant: p, index, enriched, onUpdate }) {
  const [currentSeed, setCurrentSeed] = useState(p.seed_time)
  const [pendingSeed, setPendingSeed] = useState(p.seed_time)
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState(null)

  const built = normalizeSeedTime(pendingSeed)
  const currentBuilt = normalizeSeedTime(currentSeed)
  const dirty = built !== null && built !== currentBuilt
  const canUpdate = built !== null
  const label = p.override_status || p.status || ""
  const sc = STATUS_COLORS[label] || {}
  const colSpan = enriched ? 11 : 8

  function handleRowClick(e) {
    if (e.target.closest("input") || e.target.closest("button") || e.target.closest("a")) return
    setExpanded(x => !x)
  }

  function handleSave() {
    const normalized = normalizeSeedTime(pendingSeed)
    if (!normalized) return
    setSaving(true); setSaveMsg(null)
    fetch(`${API}/update-seed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registration_id: p.registration_id, seed_time: normalized })
    })
      .then(async r => {
        const data = await r.json()
        if (!r.ok || data.error) {
          throw new Error(data.error || "update failed")
        }
        return data
      })
      .then(() => {
        setSaving(false); setSaveMsg("saved")
        setCurrentSeed(normalized); setPendingSeed(normalized)
        setTimeout(() => setSaveMsg(null), 2000)
        onUpdate({ ...p, seed_time: normalized })
        if (enriched) {
          fetch(`${API}/enrich-one`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ registration_id: p.registration_id, seed_time: normalized })
          }).then(r => r.json()).then(onUpdate).catch(() => { })
        }
      })
      .catch(() => { setSaving(false); setSaveMsg("error") })
  }

  function handleOverride(newStatus) {
    const send = label === newStatus ? null : newStatus
    fetch(`${API}/override-status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registration_id: p.registration_id, override_status: send })
    }).then(r => r.json()).then(d => onUpdate({ ...p, override_status: d.override_status })).catch(() => { })
  }

  const athlinksUrl = `https://www.athlinks.com/search/unclaimed?category=unclaimed&term=${encodeURIComponent(p.first_name + " " + p.last_name)}`
  const googleUrl = `https://www.google.com/search?q=${encodeURIComponent(p.first_name + " " + p.last_name + " race results")}`

  return (
    <>
      <tr className={`row ${expanded ? "row-expanded" : ""}`} onClick={handleRowClick}>
        <td className="col-num">{index}</td>
        <td className="col-name">
          <span className="row-name">{p.first_name} {p.last_name}</span>
        </td>
        <td>{p.age}</td>
        <td className="col-gender">{p.gender}</td>
        <td className="col-city">{locationStr(p)}</td>
        <td className="col-seed">
          <SeedInput value={pendingSeed} onChange={setPendingSeed} onSave={handleSave} />
        </td>
        <td className="col-fb">
          {p.first_boilermaker === "Yes" ? <span className="tag-first">1st</span> : ""}
        </td>
        {enriched && <>
          <td className="col-status">
            {label ? (
              <span className="status-badge" style={{ background: sc.bg, color: sc.text, borderColor: sc.border }}>
                {label}
              </span>
            ) : "—"}
            {p.override_status && (
              <>
                <span className="override-marker">manual</span>
                <button className="clear-override" onClick={e => { e.stopPropagation(); handleOverride(null) }} title="clear override">×</button>
              </>
            )}
          </td>
          <td className="col-best">
            {p.past_best
              ? <span className="past-best">{fmtDisplay(p.past_best)} <span className="past-year">'{String(p.past_best_year).slice(2)}</span></span>
              : <span className="muted">—</span>}
          </td>
          <td className="col-links">
            <a href={athlinksUrl} target="_blank" rel="noreferrer" className="link-btn" onClick={e => e.stopPropagation()}>ath</a>
            <a href={googleUrl} target="_blank" rel="noreferrer" className="link-btn" onClick={e => e.stopPropagation()}>goo</a>
          </td>
        </>}
        <td className="col-action">
          <div className="action-wrap">
            <button className={`btn btn-save ${dirty ? "btn-dirty" : ""}`}
              onClick={e => { e.stopPropagation(); if (canUpdate) handleSave() }}
              disabled={saving || !canUpdate}>
              {saving ? "..." : "update"}
            </button>
            {saveMsg && <span className={`save-msg ${saveMsg === "error" ? "save-error" : ""}`}>{saveMsg}</span>}
          </div>
        </td>
      </tr>

      {expanded && (
        <tr className="row-detail">
          <td colSpan={colSpan}>
            <div className="detail-wrap">
              {enriched && p.past_results?.length > 0 ? (
                <>
                  {p.reason && <div className="detail-reason">{p.reason}</div>}
                  <table className="history-table">
                    <thead><tr><th>year</th><th>time</th><th>bib</th><th>age</th><th>city</th></tr></thead>
                    <tbody>
                      {p.past_results.map((r, i) => (
                        <tr key={i}>
                          <td>{r.year}</td>
                          <td className="history-time">{fmtDisplay(r.net_time)}</td>
                          <td>{r.bib_number || "—"}</td>
                          <td>{r.age}</td>
                          <td>{r.city}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : enriched ? (
                <div className="detail-empty">no past boilermaker results found</div>
              ) : (
                <div className="detail-empty">run check to see past results</div>
              )}
              {enriched && (
                <div className="override-row">
                  <span className="override-label">override:</span>
                  {["GOOD", "LIAR", "REVIEW"].map(s => (
                    <button key={s}
                      className={`override-btn override-${s} ${label === s ? "override-active" : ""}`}
                      onClick={() => handleOverride(s)}>{s}</button>
                  ))}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
