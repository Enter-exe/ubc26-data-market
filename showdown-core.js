/* Replay the BTC buyer's proof gate against the recorded draw and commitment. */
globalThis.Showdown = (() => {
  const encoder = new TextEncoder();
  const nodeTag = encoder.encode("node:");
  const hexHash = /^[0-9a-f]{64}$/;
  const digest = async bytes => new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));

  const fromHex = hex => Uint8Array.from(hex.match(/../g), byte => parseInt(byte, 16));

  async function replayDraw({root, seed, mode}, draw) {
    if (typeof root !== "string" || !hexHash.test(root)) {
      throw Error("Invalid BTC replay draw inputs.");
    }
    const domain = encoder.encode("UBC26:draw:v1:");
    let request, block;
    if (mode === "modeled" || mode === "recorded" || draw) {
      if (draw?.dataset !== "btc-usd-hourly" || draw.root !== root ||
          !Number.isSafeInteger(draw.request_block) || draw.request_block < 0 ||
          draw.draw_block !== draw.request_block + 2 ||
          ![draw.request_tx, draw.draw_block_hash].every(s => /^0x[0-9a-f]{64}$/i.test(s))) {
        throw Error("Invalid Arc BTC draw inputs.");
      }
      request = fromHex(draw.request_tx.slice(2));
      block = fromHex(draw.draw_block_hash.slice(2));
    } else {
      if (!Number.isSafeInteger(seed)) throw Error("Invalid simulated BTC draw seed.");
      request = await digest(encoder.encode("offline BTC preview " + seed));
      block = await digest(encoder.encode("offline BTC draw block"));
    }
    const input = new Uint8Array(domain.length + 3 * 32 + 4);
    input.set(domain);
    input.set(fromHex(root), domain.length);
    input.set(request, domain.length + 32);
    input.set(block, domain.length + 64);
    const view = new DataView(input.buffer);
    const indices = [];
    for (let counter = 0; indices.length < 8; counter++) {
      view.setUint32(input.length - 4, counter, false);
      const bytes = await digest(input);
      const index = bytes[31] % 64;
      if (!indices.includes(index)) indices.push(index);
    }
    return indices;
  }

  async function matchesRoot({index, row, proof}, root) {
    if (!Array.isArray(row) || row.length !== 3 || !/^BTC-USD:1h:[0-9]{10}$/.test(row[0]) ||
        !row.slice(1).every(value => Number.isSafeInteger(value) && value > 0) ||
        !Array.isArray(proof) || proof.length !== 6) return false;
    let node = await digest(encoder.encode("row:" + JSON.stringify([index, ...row])));
    let position = index;
    for (const hash of proof) {
      if (typeof hash !== "string" || !hexHash.test(hash)) return false;
      const sibling = Uint8Array.from(hash.match(/../g), byte => parseInt(byte, 16));
      const parent = new Uint8Array(69);
      parent.set(nodeTag);
      parent.set(node, position % 2 ? 37 : 5);
      parent.set(sibling, position % 2 ? 5 : 37);
      node = await digest(parent);
      position = Math.floor(position / 2);
    }
    return Array.from(node, byte => byte.toString(16).padStart(2, "0")).join("") === root;
  }

  function sampleQualityError(samples) {
    let listingStart;
    let previous;
    for (const sample of samples) {
      const hour = Number(sample.row[0].split(":").pop());
      if (hour % 3600 !== 0) return "A BTC timestamp falls outside a UTC hour boundary.";
      const start = hour - sample.index * 3600;
      if (listingStart !== undefined && start !== listingStart) {
        return "The BTC hours disagree with their drawn positions.";
      }
      if (previous && previous.index + 1 === sample.index && previous.row[2] !== sample.row[1]) {
        return "Adjacent rows #" + previous.index + " and #" + sample.index +
          " disagree on the same hour’s range.";
      }
      listingStart = start;
      previous = sample;
    }
    return null;
  }

  async function evaluate(data, altered) {
    if (!globalThis.crypto?.subtle) throw Error("Proof checking requires a local file, localhost, or HTTPS.");
    const run = data.runs["0.20"];
    const draw = await replayDraw(run, data.btc_draw);
    if (!Array.isArray(run.indices) || run.indices.length !== draw.length ||
        !Array.isArray(data.samples) || data.samples.length !== draw.length ||
        !draw.every((index, i) => run.indices[i] === index && data.samples[i]?.index === index)) {
      throw Error("Recorded selection or delivery differs from the independently reproduced draw.");
    }
    const samples = structuredClone(data.samples).sort((a, b) => a.index - b.index);
    const first = samples[0];
    const originalValue = first.row[2];
    if (altered) first.row[2] += 100;
    const verified = await Promise.all(samples.map(sample => matchesRoot(sample, run.root)));
    const valid = verified.every(Boolean);
    const qualityError = valid ? sampleQualityError(samples) : null;
    return {
      samples, verified, originalValue,
      changedIndex: altered ? first.index : null,
      qualityError, run: valid && !qualityError ? run : null,
    };
  }
  return {evaluate};
})();
