// Paste this function into the Quicknode Streams JavaScript filter editor.
function main(stream) {
  const {network, dataset, stream_id} = stream.metadata;
  if (network !== "arc-testnet" || dataset !== "block") {
    throw new Error("Select Arc Testnet and the Block dataset.");
  }
  // "UBC26:sample:v1:" followed by the seller's 32-byte listing transaction.
  const requestData = /^0x55424332363a73616d706c653a76313a([0-9a-f]{64})$/i;
  const blocks = stream.data.map(block => {
    const requests = [];
    for (const tx of block.transactions) {
      const match = requestData.exec(tx.input);
      if (match && tx.to && BigInt(tx.value) === 10000000000000000n) {
        requests.push({hash:tx.hash, from:tx.from, to:tx.to, listing_tx:"0x" + match[1]});
      }
    }
    // The block two heights after payment supplies randomness even when empty.
    return {number:block.number, hash:block.hash, requests};
  });
  return {network, dataset, stream_id, blocks};
}
