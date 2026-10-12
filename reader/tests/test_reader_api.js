const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../content/javascripts/reader-api.js"), "utf8");
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "Content-Type": "application/json" }
});
const invalidToken = () => json({ error: "expired", code: "invalid_token" }, 403);
function client(fetch) {
  const window = {};
  vm.runInNewContext(source, { window, fetch });
  return window.ReaderApi.request;
}

test("expired token refreshes once for concurrent requests and preserves POST payload", async () => {
  let bootstraps = 0;
  let writes = 0;
  let rejected = 0;
  const body = JSON.stringify({ instruction: "keep this draft" });
  const api = client(async (url, options) => {
    if (url === "/api/bootstrap") {
      bootstraps++;
      return json({ token: bootstraps === 1 ? "old" : "new", task_id: "task" });
    }
    assert.equal(options.method, "POST");
    assert.equal(options.body, body);
    if (options.headers["X-Reader-Token"] === "old") {
      rejected++;
      return invalidToken();
    }
    assert.equal(options.headers["X-Reader-Token"], "new");
    writes++;
    return json({ id: "candidate" });
  });
  await api("/api/bootstrap");
  const results = await Promise.all([1, 2].map(() => api("/api/revision/propose", { method: "POST", body })));
  assert.equal(results.length, 2);
  assert.equal(rejected, 2);
  assert.equal(bootstraps, 2);
  assert.equal(writes, 2);
});

test("a repeated token rejection stops after one retry", async () => {
  let attempts = 0;
  const api = client(async url => {
    if (url === "/api/bootstrap") return json({ token: "new", task_id: "task" });
    attempts++;
    return invalidToken();
  });
  await assert.rejects(api("/api/revision/propose", { method: "POST", body: "{}" }), /expired/);
  assert.equal(attempts, 2);
});

test("other failures are never replayed and HTML does not leak a JSON parser error", async () => {
  for (const response of [
    () => json({ error: "bad origin" }, 403),
    () => json({ error: "generation failed" }, 502),
    () => new Response("<!DOCTYPE html><title>Bad Request</title>", { status: 400 }),
    () => { throw new Error("network failed"); },
  ]) {
    let calls = 0;
    const api = client(async () => { calls++; return response(); });
    await assert.rejects(api("/api/revision/propose", { method: "POST", body: "{}" }), error => {
      assert.doesNotMatch(error.message, /Unexpected token|DOCTYPE/);
      return /bad origin|generation failed|HTTP 400|network failed/.test(error.message);
    });
    assert.equal(calls, 1);
  }
});

test("switching tasks during restart does not replay the old edit", async () => {
  let bootstraps = 0;
  let attempts = 0;
  const api = client(async url => {
    if (url === "/api/bootstrap") return json({ token: "token", task_id: String(++bootstraps) });
    attempts++;
    return invalidToken();
  });
  await api("/api/bootstrap");
  await assert.rejects(api("/api/revision/propose", { method: "POST", body: "{}" }), /其他任务/);
  assert.equal(attempts, 1);
});
