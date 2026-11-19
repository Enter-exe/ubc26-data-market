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

test("a damaged proof or different commitment also blocks the intact scenario", async () => {
  const modified = structuredClone(replay);
  modified.samples[0].proof[1] = "0".repeat(64);
  const result = await Showdown.evaluate(modified, false);
  assert.equal(result.run, null);
  assert.equal(result.verified.filter(Boolean).length, 7);
  modified.runs["0.20"].root = "1".repeat(64);
  assert.deepEqual((await Showdown.evaluate(modified, false)).verified, Array(8).fill(false));
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
