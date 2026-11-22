// 0.8.0: the app starts only once its database accepts connections, as the product's app does. A missing
// DATABASE_URL is a configuration error: the app names the variable on stderr and exits 1 (task-tracker MF-56).
import net from "node:net";

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set");
  process.exit(1);
}
const { hostname, port } = new URL(url);

function once() {
  return new Promise((done) => {
    const s = net.connect({ host: hostname, port: Number(port) || 5432 }, () => { s.end(); done(true); });
    s.on("error", () => done(false));
  });
}

for (let i = 0; i < 120; i++) {
  if (await once()) {
    console.log("the database at " + hostname + " accepts connections");
    await import("/app/server.mjs");
    break;
  }
  if (i === 119) {
    console.error("the database at " + hostname + " never accepted connections");
    process.exit(1);
  }
  await new Promise((r) => setTimeout(r, 1000));
}
