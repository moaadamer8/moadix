// Integration test: needs the gate's PostgreSQL service (DATABASE_URL). Without it the run fails, never skips.
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { addTask, completeTask, createTable, openCount } from "../src/tasks.js";

let client;

beforeAll(async () => {
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL is not set: this test needs the gate's PostgreSQL service");
  }
  client = new pg.Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();
  await createTable(client);
});

afterAll(async () => {
  if (client) await client.end();
});

describe("US-002 tasks in PostgreSQL", () => {
  it("adds a task with a trimmed title, open", async () => {
    const t = await addTask(client, "  write notes  ");
    expect(t.title).toBe("write notes");
    expect(t.done).toBe(false);
    expect(typeof t.id).toBe("number");
  });

  it("refuses an empty or missing title", async () => {
    await expect(addTask(client, "   ")).rejects.toThrow("a task needs a title");
    await expect(addTask(client, undefined)).rejects.toThrow("a task needs a title");
  });

  it("completes a task and counts the open ones", async () => {
    const before = await openCount(client);
    const t = await addTask(client, "finish");
    expect(await openCount(client)).toBe(before + 1);
    const done = await completeTask(client, t.id);
    expect(done).toEqual({ id: t.id, done: true });
    expect(await openCount(client)).toBe(before);
  });

  it("refuses to complete a task that does not exist", async () => {
    await expect(completeTask(client, 999999)).rejects.toThrow("no such task");
  });
});
