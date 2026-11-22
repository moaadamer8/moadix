// The database-backed module (task-tracker MF-51): only the integration test, against the gate's PostgreSQL
// service, covers it. Each caller passes its own client, so each test session has its own temporary table.
export async function createTable(client) {
  await client.query("CREATE TEMP TABLE IF NOT EXISTS tasks (id serial PRIMARY KEY, title text NOT NULL, done boolean NOT NULL DEFAULT false)");
}

export async function addTask(client, title) {
  if (typeof title !== "string" || title.trim() === "") {
    throw new Error("a task needs a title");
  }
  const r = await client.query("INSERT INTO tasks (title) VALUES ($1) RETURNING id, title, done", [title.trim()]);
  return r.rows[0];
}

export async function completeTask(client, id) {
  const r = await client.query("UPDATE tasks SET done = true WHERE id = $1 RETURNING id, done", [id]);
  if (r.rowCount === 0) {
    throw new Error("no such task");
  }
  return r.rows[0];
}

export async function openCount(client) {
  const r = await client.query("SELECT count(*)::int AS n FROM tasks WHERE NOT done");
  return r.rows[0].n;
}
