const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
require("./showdown-core.js");

const page = readFileSync(join(__dirname, "demo.html"), "utf8");
const replay = JSON.parse(page.split('<script type="application/json" id="recorded-runs">')[1].split("</script>")[0]);

test("the intact sample unlocks the recorded valuation after eight independent proofs", async () => {
  const result = await Showdown.evaluate(replay, false);
  assert.deepEqual(result.verified, Array(8).fill(true));
  assert.deepEqual(result.samples.map(s => s.index), replay.runs["0.20"].indices.toSorted((a, b) => a - b));
  assert.equal(result.run.valuation.decision, "buy");
  assert.equal(result.changedIndex, null);
});

test("changing one delivered range invalidates precisely that row and withholds valuation", async () => {
  const before = JSON.stringify(replay);
  const result = await Showdown.evaluate(replay, true);
  assert.deepEqual(result.verified, [false, true, true, true, true, true, true, true]);
  assert.equal(result.changedIndex, result.samples[0].index);
  assert.equal(result.originalValue, replay.samples.find(s => s.index === result.changedIndex).row[2]);
  assert.equal(result.samples[0].row[2], result.originalValue + 100);
  assert.equal(result.run, null);
  assert.equal(JSON.stringify(replay), before);
});

test("editing a chosen row verifies its displayed range against the original proof", async () => {
  const row = replay.samples.toSorted((a, b) => a.index - b.index).at(-1);
  const rangeBps = row.row[2] - 1;
  const edited = await Showdown.evaluate(replay, {index: row.index, rangeBps: rangeBps + 1});
  assert.equal(edited.changedIndex, row.index);
  assert.equal(edited.originalValue, rangeBps + 1);
  assert.equal(edited.samples.at(-1).row[2], rangeBps + 2);
  assert.deepEqual(edited.verified, [true, true, true, true, true, true, true, false]);
  assert.equal(edited.run, null);
  const restored = await Showdown.evaluate(replay, {index: row.index, rangeBps});
  assert.equal(restored.changedIndex, null);
  assert.equal(restored.run.valuation.decision, "buy");
});

test("edits require a delivered index and an encodable whole number of basis points", async () => {
  const index = replay.samples[0].index;
  for (const edit of [{index: -1, rangeBps: 0}, {index, rangeBps: -1}, {index, rangeBps: 3.5},
    {index, rangeBps: Number.MAX_SAFE_INTEGER}, {index, rangeBps: "1"}]) {
    await assert.rejects(Showdown.evaluate(replay, edit), /delivered row|basis points/i);
  }
});

test("a damaged proof or different commitment also blocks the intact scenario", async () => {
  const modified = structuredClone(replay);
  modified.samples[0].proof[1] = "0".repeat(64);
  const result = await Showdown.evaluate(modified, false);
  assert.equal(result.run, null);
  assert.equal(result.verified.filter(Boolean).length, 7);
  modified.runs["0.20"].root = "1".repeat(64);
  await assert.rejects(Showdown.evaluate(modified, false), /draw/i);
});

test("a missing, duplicated or substituted draw position stops the replay", async () => {
  for (const edit of [
    data => data.samples.pop(),
    data => { data.samples[0] = data.samples[1]; },
    data => { data.runs["0.20"].indices[0] = 0; },
  ]) {
    const data = structuredClone(replay);
    edit(data);
    await assert.rejects(Showdown.evaluate(data, false), /draw/i);
  }
});

test("the simulated seed and draw order must reproduce the Python buyer's selection", async () => {
  for (const edit of [
    data => { data.runs["0.20"].seed += 1; },
    data => {
      data.runs["0.20"].indices.reverse();
      data.samples.reverse();
    },
  ]) {
    const data = structuredClone(replay);
    edit(data);
    await assert.rejects(Showdown.evaluate(data, false), /draw/i);
  }
});

test("valid proofs for inconsistent BTC hours or adjacent ranges cannot release a valuation", async () => {
  // Use the Python seller and draw so the committed rows have genuine proofs.
  const build = `
import sys, json, hashlib
from arc_draw import draw_indices
from market import tree
from sample_delivery import package
rows = json.load(sys.stdin)
root = tree(rows)[-1][0]
seed = 0
request = hashlib.sha256(f"offline BTC preview {seed}".encode()).digest()
block = hashlib.sha256(b"offline BTC draw block").digest()
indices = draw_indices(root, request, block)
draw = dict(indices=indices, root=root.hex(), request_tx=request.hex())
snapshot = dict(rows=rows, manifest={"root": root.hex()})
print(json.dumps(dict(runs={"0.20": dict(draw, seed=seed)}, samples=package(snapshot, draw)["samples"])))
`;
  const { execFileSync } = require("node:child_process");
  for (const [step, offset, next, reason] of [
    [3600, 0, 3, /adjacent.*range/i],
    [3600, 1, 2, /UTC hour/i],
    [7200, 0, 2, /drawn positions/i],
  ]) {
    const rows = Array.from({length: 64}, (_, i) => [
      "BTC-USD:1h:" + (1704067200 + i * step + offset), i + 1, i + next,
    ]);
    const data = JSON.parse(execFileSync("python3", ["-B", "-c", build], {
      cwd: __dirname, input: JSON.stringify(rows), encoding: "utf8",
    }));
    const rejected = await Showdown.evaluate(data, false);
    assert.deepEqual(rejected.verified, Array(8).fill(true));
    assert.match(rejected.qualityError, reason);
    assert.equal(rejected.run, null);
    const damaged = await Showdown.evaluate(data, true);
    assert.equal(damaged.run, null);
    assert.equal(damaged.qualityError, null);
    assert.equal(damaged.verified.filter(Boolean).length, 7);
  }
});

test("the streamed replay derives positions from the recorded Arc hashes and preserves a pass", async () => {
  const data = structuredClone(replay);
  const run = data.runs["0.20"];
  const hash = text => "0x" + require("node:crypto").createHash("sha256").update(text).digest("hex");
  data.btc_draw = {
    dataset: "btc-usd-hourly", root: run.root, request_tx: hash("offline BTC preview " + run.seed),
    draw_block_hash: hash("offline BTC draw block"), request_block: 72, draw_block: 74,
  };
  run.mode = "modeled";
  delete run.seed;
  run.valuation.decision = "pass";
  assert.equal((await Showdown.evaluate(data, false)).run.valuation.decision, "pass");
  assert.equal((await Showdown.evaluate(data, true)).run, null);
  for (const edit of [
    draw => { draw.request_tx = hash("different payment"); },
    draw => { draw.draw_block_hash = hash("different block"); },
    draw => { draw.root = "11".repeat(32); },
    draw => { draw.dataset = "taxi"; },
    draw => { draw.draw_block++; },
  ]) {
    const modified = structuredClone(data);
    edit(modified.btc_draw);
    await assert.rejects(Showdown.evaluate(modified, false), /draw/i);
  }
});
