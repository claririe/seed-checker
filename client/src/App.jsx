import { useState, useEffect } from "react"

function App() {
  const [participants, setParticipants] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)

  useEffect(() => {
    fetch("http://127.0.0.1:5001/participants")
      .then(res => res.json())
      .then(data => {
        setParticipants(data)
        setLoading(false)
      })
  }, [])

  function handleUpload(e) {
    const file = e.target.files[0]
    if (!file) return

    setUploading(true)
    const formData = new FormData()
    formData.append("file", file)

    fetch("http://127.0.0.1:5001/upload-csv", {
      method: "POST",
      body: formData
    })
      .then(res => res.json())
      .then(data => {
        setUploadResult(data.inserted)
        setUploading(false)
        fetch("http://127.0.0.1:5001/participants")
          .then(res => res.json())
          .then(data => setParticipants(data))
      })
  }

  if (loading) return <p>Loading...</p>

  return (
    <div style={{ padding: "20px" }}>
      <h1>Seed Checker</h1>
      <div>
        <input type="file" accept=".csv" onChange={handleUpload} />
        {uploading && <p>Uploading...</p>}
        {uploadResult && <p>Loaded {uploadResult} participants</p>}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Age</th>
            <th>Gender</th>
            <th>City</th>
            <th>State</th>
            <th>Seed Time</th>
            <th>First Boilermaker</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {participants.map(p => (
            <ParticipantRow key={p.registration_id} participant={p} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ParticipantRow({ participant }) {
  const [seedTime, setSeedTime] = useState(participant.seed_time)

  return (
    <tr>
      <td>{participant.first_name} {participant.last_name}</td>
      <td>{participant.age}</td>
      <td>{participant.gender}</td>
      <td>{participant.city}</td>
      <td>{participant.state}</td>
      <td>
        <input
          value={seedTime}
          onChange={e => setSeedTime(e.target.value)}
        />
      </td>
      <td>{participant.first_boilermaker}</td>
      <td>
        <button onClick={() => {
          fetch("http://127.0.0.1:5001/update-seed", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              registration_id: participant.registration_id,
              seed_time: seedTime
            })
          })
            .then(res => res.json())
            .then(data => console.log(data))
        }}>
          Update
        </button>
      </td>
    </tr>
  )
}

export default App