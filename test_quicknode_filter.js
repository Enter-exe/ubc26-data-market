const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const receipt = require("./examples/arc-testnet-draw.json");

test("Streams keeps paid sample requests and retains the future block even when it has no requests", () => {
  const tag = Buffer.from("UBC26:sample:v1:").toString("hex");
  const tx = {hash:receipt.request_tx, from:receipt.buyer, to:receipt.seller,
    value:"0x" + BigInt(receipt.fee_base_units).toString(16), input:"0x" + tag + receipt.listing_tx.slice(2)};
  const stream = {
    metadata:{network:"arc-testnet", dataset:"block", stream_id:"local-filter-test"},
    data:[
      {number:"0x1", hash:receipt.request_block_hash, transactions:[tx, {...tx, value:"0x0"}, {...tx, input:"0x"}]},
      {number:"0x3", hash:receipt.draw_block_hash, transactions:[]},
    ],
  };
  const source = fs.readFileSync(path.join(__dirname, "quicknode_filter.js"), "utf8");
  const result = JSON.parse(JSON.stringify(vm.runInNewContext(source + "\nmain(stream)", {stream})));
  assert.deepEqual(result, {...stream.metadata, blocks:[
    {number:"0x1", hash:receipt.request_block_hash, requests:[{hash:receipt.request_tx,
      from:receipt.buyer, to:receipt.seller, listing_tx:receipt.listing_tx}]},
    {number:"0x3", hash:receipt.draw_block_hash, requests:[]},
  ]});
});
