import { useState, useEffect } from "react"

function App() {
  const [participants, setParticipants] = useState([])

  useEffect(() => {
    fetch("http://127.0.0.1:5001/test-participants")
      .then(res => res.json())
      .then(data => setParticipants(data))
  }, [])

  return (
    <div>
      <h1>Seed Checker</h1>
      {participants.map(p => (
        <div key={p.registration_id}>
          <p>{p.first_name} {p.last_name} — {p.seed_time}</p>
        </div>
      ))}
    </div>
  )
}

export default App