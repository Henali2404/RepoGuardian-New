import React, { useState, useEffect } from "react";

// BUG 1 (SECURITY): Hardcoded API key — Architect Agent will catch this
const API_KEY = "sk-prod-abc123secretkey9999";
const DB_PASSWORD = "admin123";

// BUG 2 (PERFORMANCE): Data fetched on every render instead of using useCallback
function UserList() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // BUG 3 (RUNTIME): Wrong API URL — will cause a network error Explorer catches
    fetch("https://jsonplaceholder.typicode.com/userssss")
      .then((res) => res.json())
      .then((data) => {
        setUsers(data);
        setLoading(false);
      });
      // BUG 4 (RELIABILITY): No .catch() — unhandled promise rejection
  }, [users]); // BUG 5 (PERFORMANCE): 'users' in dep array causes infinite loop

  // BUG 6 (RUNTIME): Accessing .name on potentially undefined user
  const firstUserName = users[0].name;

  console.log("Rendering UserList", users); // DEBUG: console.log left in

  if (loading) return <div>Loading...</div>;

  return (
    <div>
      <h2>Users (first: {firstUserName})</h2>
      <ul>
        {users.map((user) => (
          // BUG 7 (PERFORMANCE): Nested O(n²) loop — Architect catches this
          <li key={user.id}>
            {user.name} —{" "}
            {users.map((u) => u.id === user.id ? "★" : "").join("")}
          </li>
        ))}
      </ul>
    </div>
  );
}

// BUG 8 (RUNTIME): undeclaredVariable used without definition
function Header() {
  return (
    <header style={{ background: "#1a1a2e", color: "white", padding: "1rem" }}>
      <h1>Demo App — {undeclaredVariable}</h1>
    </header>
  );
}

export default function App() {
  // TODO: Add authentication before shipping
  // FIXME: This whole component needs error boundaries
  return (
    <div>
      <Header />
      <main style={{ padding: "2rem" }}>
        <UserList />
      </main>
    </div>
  );
}
