import { useState, useEffect, useRef } from "react"

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:5001"
let runsignupCredentials = { apiKey: "", apiSecret: "" }

function setRunsignupCredentials(apiKey, apiSecret) {
  runsignupCredentials = { apiKey: apiKey.trim(), apiSecret: apiSecret.trim() }
}

function apiFetch(path, options = {}, withRunsignup = false) {
  const headers = new Headers(options.headers || {})
  if (withRunsignup && runsignupCredentials.apiKey) {
    headers.set("X-RSU-API-Key", runsignupCredentials.apiKey)
  }
  if (withRunsignup && runsignupCredentials.apiSecret) {
    headers.set("X-RSU-API-Secret", runsignupCredentials.apiSecret)
  }
  return fetch(`${API}${path}`, { ...options, headers })
}

async function responseData(response, fallbackMessage = "request failed") {
  let data
  try {
    data = await response.json()
  } catch {
    throw new Error(response.ok ? fallbackMessage : `request failed (${response.status})`)
  }
  if (!response.ok || data?.error) {
    throw new Error(data?.error || `${fallbackMessage} (${response.status})`)
  }
  return data
}

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

function seedSeconds(value) {
  const normalized = normalizeSeedTime(value)
  if (!normalized) return null
  const parts = normalized.split(":").map(Number)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  return parts[0] * 60 + parts[1]
}

function effectiveSeed(participant) {
  if (participant.runsignup_checked) return participant.runsignup_seed
  return participant.uploaded_seed
}

export default function App() {
  const [apiKey, setApiKey] = useState("")
  const [apiSecret, setApiSecret] = useState("")
  const [participants, setParticipants] = useState([])
  const [population, setPopulation] = useState([])
  const [workspace, setWorkspace] = useState({})
  const [raceIdInput, setRaceIdInput] = useState("13089")
  const [raceData, setRaceData] = useState(null)
  const [selectedEventId, setSelectedEventId] = useState("")
  const [selectedQuestionId, setSelectedQuestionId] = useState("")
  const [configMsg, setConfigMsg] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [historyEvents, setHistoryEvents] = useState([])
  const [fastestCount, setFastestCount] = useState("300")
  const [checkScope, setCheckScope] = useState("all")
  const [checkRange, setCheckRange] = useState({ start: "40:00", end: "55:00" })
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importState, setImportState] = useState(null)
  const [resultsStatus, setResultsStatus] = useState({})
  const [leeway, setLeeway] = useState("300")
  const [leewayInput, setLeewayInput] = useState("300")
  const [filter, setFilter] = useState("ALL")
  const [enriched, setEnriched] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null)
  const [checkMsg, setCheckMsg] = useState(null)
  const [seedRanges, setSeedRanges] = useState([
    { id: 1, start: "40:00", end: "55:00" },
  ])
  const [activeRangeId, setActiveRangeId] = useState(null)
  const [displayLimit, setDisplayLimit] = useState(300)
  const fileRef = useRef(null)
  const pollRef = useRef(null)
  const credentialsReady = Boolean(apiKey.trim() && apiSecret.trim())

  useEffect(() => {
    apiFetch("/workspace").then(r => responseData(r, "workspace failed")).then(data => {
      setWorkspace(data)
      if (data.race_id) setRaceIdInput(String(data.race_id))
    }).catch(() => { })
    apiFetch("/participants").then(r => responseData(r, "participants failed")).then(data => {
      if (!Array.isArray(data)) throw new Error("invalid participant response")
      setParticipants(data)
      setPopulation(data)
    }).catch(() => { })
    apiFetch("/results-status").then(r => responseData(r)).then(setResultsStatus).catch(() => { })
    apiFetch("/settings").then(r => responseData(r)).then(d => {
      if (d.leeway_seconds) { setLeeway(d.leeway_seconds); setLeewayInput(d.leeway_seconds) }
    }).catch(() => { })
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  function changeApiKey(value) {
    setApiKey(value)
    setRunsignupCredentials(value, apiSecret)
  }

  function changeApiSecret(value) {
    setApiSecret(value)
    setRunsignupCredentials(apiKey, value)
  }

  function discoverRace() {
    if (!credentialsReady || !raceIdInput.trim()) return
    setConfigMsg("loading...")
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 35000)
    apiFetch("/discover-race", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ race_id: raceIdInput.trim() }),
      signal: controller.signal,
    }, true)
      .then(r => responseData(r, "race lookup failed"))
      .then(data => {
        setRaceData(data)
        const eventId = data.events.some(e => e.event_id === workspace.event_id)
          ? workspace.event_id : data.events[0]?.event_id
        setSelectedEventId(String(eventId || ""))
        const questions = applicableQuestions(data.questions, eventId)
        const questionId = questions.some(q => q.question_id === workspace.question_id)
          ? workspace.question_id : questions[0]?.question_id
        setSelectedQuestionId(String(questionId || ""))
        setConfigMsg(data.name)
      })
      .catch(error => setConfigMsg(
        error.name === "AbortError"
          ? "race lookup timed out"
          : error instanceof TypeError
            ? "backend unavailable"
            : error.message
      ))
      .finally(() => clearTimeout(timeout))
  }

  function applicableQuestions(questions, eventId) {
    return (questions || []).filter(question =>
      question.question_type_code === "T"
      && !question.skip_for_event_ids.includes(Number(eventId))
    )
  }

  function changeEvent(value) {
    setSelectedEventId(value)
    const questions = applicableQuestions(raceData?.questions, value)
    setSelectedQuestionId(String(questions[0]?.question_id || ""))
  }

  function loadHistoricalEvents() {
    apiFetch("/historical-events", { method: "POST" }, true)
      .then(r => responseData(r, "past-event lookup failed"))
      .then(data => {
        if (!Array.isArray(data)) throw new Error("invalid past-event response")
        setHistoryEvents(data)
      })
      .catch(error => {
        setHistoryEvents([])
        setConfigMsg(error.message)
      })
  }

  function useWorkspace() {
    const event = raceData?.events.find(e => e.event_id === Number(selectedEventId))
    const question = raceData?.questions.find(q => q.question_id === Number(selectedQuestionId))
    if (!event || !question) return
    const eventChanged = workspace.race_id !== raceData.race_id
      || workspace.event_id !== event.event_id
    setConfigMsg("saving...")
    apiFetch("/workspace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        race_id: raceData.race_id,
        event_id: event.event_id,
        question_id: question.question_id,
        race_name: raceData.name,
        event_name: event.name,
        event_distance: event.distance,
      }),
    }, true)
      .then(r => responseData(r, "save failed"))
      .then(data => {
        setWorkspace(data)
        if (eventChanged) {
          setParticipants([])
          setPopulation([])
        } else {
          loadParticipants()
        }
        setEnriched(false)
        setConfigMsg("ready")
        loadHistoricalEvents()
        apiFetch("/results-status").then(r => responseData(r)).then(setResultsStatus)
      })
      .catch(() => setConfigMsg("save failed"))
  }

  function loadParticipants() {
    setLoading(true)
    apiFetch("/participants")
      .then(r => responseData(r, "participants failed"))
      .then(data => {
        if (!Array.isArray(data)) throw new Error("invalid participant response")
        setParticipants(data)
        setPopulation(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  function handleUpload(e) {
    const file = e.target.files[0]
    if (!file || !credentialsReady) return
    setUploadMsg("uploading...")
    const fd = new FormData()
    fd.append("file", file)
    apiFetch("/upload-csv", { method: "POST", body: fd }, true)
      .then(r => responseData(r, "upload failed"))
      .then(d => {
        setUploadMsg(`${d.inserted} entries loaded`)
        setWorkspace(prev => ({ ...prev, participant_source: "upload" }))
        setEnriched(false)
        loadParticipants()
      })
      .catch(error => setUploadMsg(error.message))
    e.target.value = ""
  }

  function handleSync() {
    if (!credentialsReady || !workspace.event_id || syncing) return
    setSyncing(true)
    setUploadMsg("syncing...")
    apiFetch("/sync-participants", { method: "POST" }, true)
      .then(r => responseData(r, "sync failed"))
      .then(data => {
        setUploadMsg(`${data.synced} entries synced`)
        setWorkspace(prev => ({ ...prev, participant_source: "sync" }))
        setEnriched(false)
        loadParticipants()
      })
      .catch(error => setUploadMsg(error.message))
      .finally(() => setSyncing(false))
  }

  function handleImport() {
    if (importing || !credentialsReady || historyEvents.length === 0) return
    const events = historyEvents.map(event => ({
      event_id: event.event_id,
      year: event.year,
      name: event.name,
      distance: event.distance,
    }))
    setImporting(true)
    setImportState(null)
    apiFetch("/import-results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    }, true)
      .then(r => responseData(r, "import failed"))
      .then(() => {
        pollRef.current = setInterval(() => {
          Promise.all([
            apiFetch("/import-status").then(r => responseData(r)),
            apiFetch("/results-status").then(r => responseData(r)),
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
      .catch(error => {
        setImporting(false)
        setImportState({ errors: [{ error: error.message }] })
      })
  }

  function saveLeeway(val) {
    const n = parseInt(val)
    if (isNaN(n) || n < 0 || !credentialsReady) return
    setLeeway(String(n))
    apiFetch("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leeway_seconds: String(n) })
    }, true).catch(() => { })
  }

  function loadEnriched() {
    if (!credentialsReady || participants.length === 0) return
    setLoading(true)
    setCheckMsg(null)
    apiFetch("/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        leeway,
        limit: checkScope === "fastest"
          ? Math.max(1, parseInt(fastestCount, 10) || 300)
          : null,
        range_start: checkScope === "range" ? checkRange.start || null : null,
        range_end: checkScope === "range" ? checkRange.end || null : null,
      }),
    }, true)
      .then(r => responseData(r, "check failed"))
      .then(data => {
        setParticipants(data)
        setFilter("ALL")
        setActiveRangeId(null)
        setDisplayLimit(300)
        setEnriched(true)
        setLoading(false)
      })
      .catch(error => {
        setCheckMsg(
          error instanceof TypeError
            ? "server connection lost; retry after the backend restarts"
            : error.message
        )
        setLoading(false)
      })
  }

  function updateParticipant(updated) {
    setParticipants(prev => prev.map(p =>
      p.registration_id === updated.registration_id ? { ...p, ...updated } : p
    ))
    setPopulation(prev => prev.map(p =>
      p.registration_id === updated.registration_id ? { ...p, ...updated } : p
    ))
  }

  const importedYears = Object.keys(resultsStatus).sort().reverse()
  const hasResults = importedYears.length > 0
  const activeRange = seedRanges.find(range => range.id === activeRangeId)
  const rangeIncludes = (participant, range) => {
    const seed = seedSeconds(effectiveSeed(participant))
    const start = seedSeconds(range.start)
    const end = seedSeconds(range.end)
    return seed !== null && start !== null && end !== null && start <= seed && seed <= end
  }
  const filtered = participants.filter(p => {
    const statusMatches = filter === "ALL"
      || (filter === "NULL_SEED" && seedSeconds(effectiveSeed(p)) === null)
      || (filter === "OVERRIDDEN" && Boolean(p.override_status))
      || (filter === "DONE" && Boolean(p.reviewed))
      || (filter === "NOT_DONE" && !p.reviewed)
      || (p.override_status || p.status || "") === filter
    return statusMatches && (!activeRange || rangeIncludes(p, activeRange))
  })
  const visibleParticipants = filtered
  const displayedParticipants = visibleParticipants.slice(0, displayLimit)
  const counts = {
    ALL: participants.length,
    OVERRIDDEN: participants.filter(p => p.override_status).length,
    DONE: participants.filter(p => p.reviewed).length,
    NOT_DONE: participants.filter(p => !p.reviewed).length,
    NULL_SEED: participants.filter(p => seedSeconds(effectiveSeed(p)) === null).length,
  }
  for (const k of ["GOOD", "LIAR", "REVIEW"]) {
    counts[k] = participants.filter(p => (p.override_status || p.status || "") === k).length
  }

  function changeRange(id, field, value) {
    setSeedRanges(ranges => ranges.map(range =>
      range.id === id ? { ...range, [field]: value } : range
    ))
  }

  function addRange() {
    setSeedRanges(ranges => [
      ...ranges,
      { id: Math.max(0, ...ranges.map(range => range.id)) + 1, start: "", end: "" },
    ])
  }

  function removeRange(id) {
    setSeedRanges(ranges => ranges.filter(range => range.id !== id))
    if (activeRangeId === id) setActiveRangeId(null)
  }

  function selectFilter(nextFilter) {
    setFilter(nextFilter)
    setDisplayLimit(300)
  }

  function selectRange(id) {
    setActiveRangeId(activeRangeId === id ? null : id)
    setDisplayLimit(300)
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
  const eventQuestions = applicableQuestions(raceData?.questions, selectedEventId)
  const workspaceReady = Boolean(workspace.race_id && workspace.event_id && workspace.question_id)
  const showUploadedSeed = workspace.participant_source === "upload"
  const checkRangeValid = (
    seedSeconds(checkRange.start) !== null
    && seedSeconds(checkRange.end) !== null
  )
  const rangeScopeReady = checkScope !== "range" || checkRangeValid
  const checkRangeCount = population.filter(p => rangeIncludes(p, checkRange)).length

  return (
    <div className="app">
      <header className="header">
        <div className="header-title">
          <h1>seed checker</h1>
        </div>
        <div className="controls">
          <div className="control-row workspace-row">

            <div className="control-group credential-group">
              <label className="control-label">RunSignup info</label>
              <div className="control-items credential-fields">
                <input className="credential-input" value={apiKey}
                  onChange={e => changeApiKey(e.target.value)}
                  placeholder="API key" autoComplete="off" spellCheck="false" />
                <input className="credential-input" type="password" value={apiSecret}
                  onChange={e => changeApiSecret(e.target.value)}
                  placeholder="API secret" autoComplete="off" spellCheck="false" />
              </div>
            </div>

            <div className="control-group">
              <label className="control-label">race</label>
              <div className="control-items">
                <input className="config-input race-id-input" value={raceIdInput}
                  onChange={e => setRaceIdInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && discoverRace()}
                  placeholder="race ID" inputMode="numeric" />
                <button className="btn" onClick={discoverRace}
                  disabled={!credentialsReady}>load</button>
              </div>
            </div>

            {raceData && <>
              <div className="control-group event-group">
                <label className="control-label">event</label>
                <select className="config-select" value={selectedEventId}
                  onChange={e => changeEvent(e.target.value)}>
                  {raceData.events.map(event => (
                    <option key={event.event_id} value={event.event_id}>
                      {event.name} · {event.start_time.split(" ")[0]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="control-group question-group">
                <label className="control-label">seed question</label>
                <select className="config-select" value={selectedQuestionId}
                  onChange={e => setSelectedQuestionId(e.target.value)}>
                  {eventQuestions.map(question => (
                    <option key={question.question_id} value={question.question_id}>
                      {question.question_text}
                    </option>
                  ))}
                </select>
              </div>
              <div className="control-group control-group-action">
                <div className="control-items">
                  <button className="btn" onClick={useWorkspace}
                    disabled={!selectedEventId || !selectedQuestionId}>use event</button>
                </div>
              </div>
            </>}
            {configMsg && <span className="workspace-status">{configMsg}</span>}
          </div>

          <div className="control-row">

            <div className="control-group">
              <label className="control-label">participants</label>
              <div className="control-items">
                <button className="btn" onClick={handleSync}
                  disabled={!credentialsReady || !workspaceReady || syncing}>
                  {syncing ? "syncing..." : "sync"}
                </button>
                <button className="btn" onClick={() => fileRef.current?.click()}
                  disabled={!credentialsReady}>
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
                <button className="btn" onClick={handleImport}
                  disabled={importing || !credentialsReady || historyEvents.length === 0}>
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

          </div>

          {participants.length > 0 && (
            <div className="scope-tools">
              <span className="control-label">check pool</span>
              <div className="scope-options">
                <button className={`scope-option ${checkScope === "all" ? "scope-active" : ""}`}
                  onClick={() => setCheckScope("all")}>
                  all <span className="filter-count">{population.length}</span>
                </button>
                <label className={`scope-option fastest-control ${checkScope === "fastest" ? "scope-active" : ""}`}
                  onClick={() => setCheckScope("fastest")}>
                  <span>fastest</span>
                  <input value={fastestCount} onChange={e => {
                    setFastestCount(e.target.value)
                    setCheckScope("fastest")
                  }}
                    onClick={e => e.stopPropagation()} inputMode="numeric" />
                </label>
                <div className={`range-item ${checkScope === "range" ? "range-active" : ""}`}
                  onClick={() => setCheckScope("range")}>
                  <span className="scope-range-label">range</span>
                  <input className="range-input" value={checkRange.start}
                    onChange={e => {
                      setCheckRange(range => ({ ...range, start: e.target.value }))
                      setCheckScope("range")
                    }}
                    onFocus={() => setCheckScope("range")}
                    onClick={e => e.stopPropagation()}
                    placeholder="H:MM:SS" inputMode="numeric" />
                  <span className="range-separator">to</span>
                  <input className="range-input" value={checkRange.end}
                    onChange={e => {
                      setCheckRange(range => ({ ...range, end: e.target.value }))
                      setCheckScope("range")
                    }}
                    onFocus={() => setCheckScope("range")}
                    onClick={e => e.stopPropagation()}
                    placeholder="H:MM:SS" inputMode="numeric" />
                  <span className="range-count">{checkRangeValid ? checkRangeCount : "—"}</span>
                </div>
                <button className={`btn check-btn ${enriched ? "btn-active" : ""}`}
                  onClick={loadEnriched}
                  disabled={loading || !credentialsReady || participants.length === 0 || !rangeScopeReady}>
                  {loading ? "loading..." : "check"}
                </button>
                {checkMsg && <span className="status-text save-error">{checkMsg}</span>}
              </div>
            </div>
          )}

          {enriched && participants.length > 0 && (
            <div className="review-tools">
              <span className="control-label">filters</span>
              <div className="filter-row">
                {["ALL", "GOOD", "LIAR", "REVIEW", "OVERRIDDEN", "DONE", "NOT_DONE", "NULL_SEED"].map(f => (
                  <button key={f}
                    className={`filter-btn ${filter === f ? "filter-active" : ""} filter-${f}`}
                    onClick={() => selectFilter(f)}>
                    {f === "NULL_SEED" ? "NULL SEED" : f === "NOT_DONE" ? "NOT DONE" : f}
                    <span className="filter-count">{counts[f]}</span>
                  </button>
                ))}
              </div>
              <div className="range-tools">
                {seedRanges.map(range => {
                  const count = participants.filter(p => rangeIncludes(p, range)).length
                  const valid = seedSeconds(range.start) !== null && seedSeconds(range.end) !== null
                  return (
                    <div className={`range-item ${activeRangeId === range.id ? "range-active" : ""}`}
                      key={range.id}
                      onClick={() => valid && selectRange(range.id)}>
                      <input className="range-input" value={range.start}
                        onChange={e => changeRange(range.id, "start", e.target.value)}
                        onClick={e => e.stopPropagation()}
                        placeholder="H:MM:SS" inputMode="numeric" />
                      <span className="range-separator">to</span>
                      <input className="range-input" value={range.end}
                        onChange={e => changeRange(range.id, "end", e.target.value)}
                        onClick={e => e.stopPropagation()}
                        placeholder="H:MM:SS" inputMode="numeric" />
                      <span className="range-count">{valid ? count : "—"}</span>
                      <button className="range-remove" onClick={e => {
                        e.stopPropagation()
                        removeRange(range.id)
                      }} title="remove range" aria-label="remove range">×</button>
                    </div>
                  )
                })}
                <button className="btn range-add" onClick={addRange}>add range</button>
              </div>
            </div>
          )}
        </div>
      </header>

      <main className="main">
        {loading && <div className="empty">matching entries...</div>}
        {!loading && participants.length === 0 && <div className="empty">sync or upload participants</div>}
        {!loading && visibleParticipants.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>#</th><th>name</th><th>age</th><th>g</th><th>location</th>
                {showUploadedSeed && <th>uploaded seed</th>}
                <th>RunSignup seed <span className="th-note">H:MM:SS</span></th>
                {enriched && <><th>status</th><th>past best</th><th>links</th></>}
                {enriched && <th>done</th>}
                <th>runsignup</th>
              </tr>
            </thead>
            <tbody>
              {displayedParticipants.map((p, i) => (
                <ParticipantRow key={`${p.registration_id}-${p.runsignup_checked}-${p.runsignup_seed || ""}`} participant={p}
                  index={i + 1} enriched={enriched} onUpdate={updateParticipant}
                  credentialsReady={credentialsReady} showUploadedSeed={showUploadedSeed} />
              ))}
            </tbody>
          </table>
        )}
        {!loading && visibleParticipants.length > displayLimit && (
          <div className="table-more">
            <span>{displayedParticipants.length} of {visibleParticipants.length}</span>
            <button className="btn" onClick={() => setDisplayLimit(limit => limit + 300)}>
              show more
            </button>
          </div>
        )}
        {!loading && visibleParticipants.length === 0 && participants.length > 0 && (
          <div className="empty">no entries match this filter</div>
        )}
      </main>
    </div>
  )
}

function SeedInput({ value, onChange, onSave, disabled }) {
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
    if (commitDisplay()) onSave(normalized)
  }

  return (
    <input
      className={`seed-input ${text && !normalized ? "seed-invalid" : ""}`}
      value={text}
      onChange={e => handleChange(e.target.value)}
      onBlur={commitDisplay}
      onKeyDown={handleKeyDown}
      placeholder="H:MM:SS"
      inputMode="numeric"
      disabled={disabled}
    />
  )
}

function ParticipantRow({ participant: p, index, enriched, onUpdate, credentialsReady, showUploadedSeed }) {
  const fetchedSeed = p.runsignup_checked ? p.runsignup_seed : null
  const [currentSeed, setCurrentSeed] = useState(fetchedSeed)
  const [pendingSeed, setPendingSeed] = useState(fetchedSeed)
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState(null)
  const [detail, setDetail] = useState(
    p.past_results !== undefined
      ? { past_results: p.past_results, reason: p.reason }
      : null
  )
  const [detailLoading, setDetailLoading] = useState(false)

  const built = normalizeSeedTime(pendingSeed)
  const currentBuilt = normalizeSeedTime(currentSeed)
  const dirty = built !== null && built !== currentBuilt
  const canUpdate = built !== null
  const label = p.override_status || p.status || ""
  const sc = STATUS_COLORS[label] || {}
  const colSpan = (enriched ? 11 : 7) + (showUploadedSeed ? 1 : 0)

  function handleRowClick(e) {
    if (e.target.closest("input") || e.target.closest("button") || e.target.closest("a")) return
    const opening = !expanded
    setExpanded(opening)
    if (opening && enriched && detail === null && !detailLoading) {
      setDetailLoading(true)
      apiFetch("/enrich-one", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ registration_id: p.registration_id }),
      })
        .then(r => responseData(r, "history failed"))
        .then(data => setDetail(data))
        .catch(() => setDetail({ past_results: [], reason: "Unable to load history" }))
        .finally(() => setDetailLoading(false))
    }
  }

  function handleSave(seedValue = pendingSeed) {
    const normalized = normalizeSeedTime(seedValue)
    if (!normalized || !credentialsReady) return
    setSaving(true); setSaveMsg(null)
    apiFetch("/update-seed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registration_id: p.registration_id, seed_time: normalized })
    }, true)
      .then(r => responseData(r, "update failed"))
      .then(() => {
        setSaving(false); setSaveMsg("saved")
        setCurrentSeed(normalized); setPendingSeed(normalized)
        setTimeout(() => setSaveMsg(null), 2000)
        onUpdate({
          ...p,
          runsignup_seed: normalized,
          runsignup_checked: 1,
        })
        if (enriched) {
          apiFetch("/enrich-one", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ registration_id: p.registration_id, seed_time: normalized })
          }).then(r => responseData(r, "refresh failed")).then(data => {
            setDetail(data)
            onUpdate(data)
          }).catch(() => { })
        }
      })
      .catch(() => { setSaving(false); setSaveMsg("error") })
  }

  function handleOverride(newStatus) {
    const send = label === newStatus ? null : newStatus
    apiFetch("/override-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registration_id: p.registration_id, override_status: send })
    }, true).then(r => responseData(r, "override failed"))
      .then(d => onUpdate({ ...p, override_status: d.override_status }))
      .catch(() => { })
  }

  function handleReviewed() {
    const reviewed = !p.reviewed
    apiFetch("/reviewed-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registration_id: p.registration_id, reviewed })
    }, true).then(r => responseData(r, "done failed"))
      .then(d => onUpdate({ ...p, reviewed: d.reviewed }))
      .catch(() => { })
  }

  const athlinksUrl = `https://www.athlinks.com/search/unclaimed?category=unclaimed&term=${encodeURIComponent(p.first_name + " " + p.last_name)}`
  const googleUrl = `https://www.google.com/search?q=${encodeURIComponent(p.first_name + " " + p.last_name + " race results")}`
  const mileSplitUrl = `https://www.google.com/search?q=${encodeURIComponent(`site:milesplit.com "${p.first_name} ${p.last_name}"`)}`
  const athleticNetUrl = `https://www.google.com/search?q=${encodeURIComponent(`site:athletic.net "${p.first_name} ${p.last_name}"`)}`

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
        {showUploadedSeed && (
          <td className="col-uploaded-seed">{fmtDisplay(p.uploaded_seed)}</td>
        )}
        <td className="col-seed">
          {p.runsignup_checked ? (
            <SeedInput value={pendingSeed} onChange={setPendingSeed} onSave={handleSave} />
          ) : (
            <span className="seed-unchecked">check first</span>
          )}
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
            <a href={athlinksUrl} target="_blank" rel="noreferrer" className="link-btn"
              title="Search Athlinks" onClick={e => e.stopPropagation()}>ath</a>
            <a href={googleUrl} target="_blank" rel="noreferrer" className="link-btn"
              title="Search the web" onClick={e => e.stopPropagation()}>web</a>
            <a href={mileSplitUrl} target="_blank" rel="noreferrer" className="link-btn"
              title="Search MileSplit via Google" onClick={e => e.stopPropagation()}>ms</a>
            <a href={athleticNetUrl} target="_blank" rel="noreferrer" className="link-btn"
              title="Search Athletic.net via Google" onClick={e => e.stopPropagation()}>anet</a>
          </td>
          <td className="col-done">
            <button className={`done-btn ${p.reviewed ? "done-active" : ""}`}
              onClick={e => { e.stopPropagation(); handleReviewed() }}>
              {p.reviewed ? "done" : "mark"}
            </button>
          </td>
        </>}
        <td className="col-action">
          <div className="action-wrap">
            <button className={`btn btn-save ${dirty ? "btn-dirty" : ""}`}
              onClick={e => { e.stopPropagation(); if (canUpdate) handleSave() }}
              disabled={saving || !canUpdate || !credentialsReady || !p.runsignup_checked}>
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
              {enriched && detailLoading ? (
                <div className="detail-empty">loading history...</div>
              ) : enriched && detail?.past_results?.length > 0 ? (
                <>
                  {detail.reason && <div className="detail-reason">{detail.reason}</div>}
                  <table className="history-table">
                    <thead><tr><th>year</th><th>race</th><th>time</th><th>bib</th><th>age</th><th>city</th></tr></thead>
                    <tbody>
                      {detail.past_results.map((r, i) => (
                        <tr key={i}>
                          <td>{r.year}</td>
                          <td>{r.race_name || r.event_name || "—"}</td>
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
                <div className="detail-empty">no matching past results found</div>
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
