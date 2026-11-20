/* Replay the BTC buyer's proof gate against the recorded draw and commitment. */
globalThis.Showdown = (() => {
  const encoder = new TextEncoder();
  const nodeTag = encoder.encode("node:");
  const hexHash = /^[0-9a-f]{64}$/;
  const digest = async bytes => new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));

  // Mirror btc_buyer.rehearse and arc_draw.draw_indices using the offline block fixture.
  async function replayDraw(root, seed) {
    if (typeof root !== "string" || !hexHash.test(root) || !Number.isSafeInteger(seed)) {
      throw Error("Invalid BTC replay draw inputs.");
    }
    const domain = encoder.encode("UBC26:draw:v1:");
    const request = await digest(encoder.encode("offline BTC preview " + seed));
    const block = await digest(encoder.encode("offline BTC draw block"));
    const input = new Uint8Array(domain.length + 3 * 32 + 4);
    input.set(domain);
    input.set(Uint8Array.from(root.match(/../g), byte => parseInt(byte, 16)), domain.length);
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

  async function evaluate(data, altered) {
    if (!globalThis.crypto?.subtle) throw Error("Proof checking requires a local file, localhost, or HTTPS.");
    const run = data.runs["0.20"];
    const draw = await replayDraw(run.root, run.seed);
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
    return {
      samples, verified, originalValue,
      changedIndex: altered ? first.index : null,
      run: verified.every(Boolean) ? run : null,
    };
  }
  return {evaluate};
})();
