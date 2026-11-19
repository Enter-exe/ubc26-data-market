"""Verify a seller's fixed-price Arc testnet offer and its full dataset payment."""
from arc_draw import ArcPending, CHAIN_ID, block_at, checked_transaction, hex_data, quantity, verify_listing_details


FULL_PRICE_BASE_UNITS = 10**17  # 0.1 native test USDC
OFFER_TAG = b"UBC26:offer:v1:"
PURCHASE_TAG = b"UBC26:purchase:v1:"


def _check_reference(rpc, transaction, previous_pos, previous_tx, tag):
    position, block_hash, data, _ = transaction
    payload = hex_data(data, len(tag) + 32, "transaction calldata")
    if payload != "0x" + tag.hex() + previous_tx[2:] or position <= previous_pos:
        raise ValueError("Transaction must reference and follow the expected prior transaction")
    height, final_hash, _ = block_at(rpc, "finalized")
    if position[0] > height:
        raise ArcPending("Transaction is not finalized on the canonical chain")
    if position[0] == height and block_hash != final_hash:
        raise ValueError("Transaction is not finalized on the canonical chain")


def verify_offer(rpc, seller, listing_tx, offer_tx):
    """Require the seller to opt a specific listing into the v1 full purchase price."""
    seller = hex_data(seller, 20, "seller")
    listing_tx = hex_data(listing_tx, 32, "listing transaction")
    offer_tx = hex_data(offer_tx, 32, "offer transaction")
    listing_pos, _, root, dataset = verify_listing_details(rpc, seller, listing_tx)
    offer = checked_transaction(rpc, offer_tx, seller, seller, 0)
    _check_reference(rpc, offer, listing_pos, listing_tx, OFFER_TAG)
    (height, index), block_hash, _, _ = offer
    terms = dict(version=1, chain_id=CHAIN_ID, seller=seller, root=root, listing_tx=listing_tx,
                offer_tx=offer_tx, offer_block=height, offer_index=index, offer_block_hash=block_hash,
                price_base_units=str(FULL_PRICE_BASE_UNITS))
    if dataset:
        terms["dataset"] = dataset
    return terms


def verify_purchase(rpc, seller, buyer, listing_tx, offer_tx, purchase_tx):
    """Validate the buyer's finalized payment before releasing the full listing."""
    buyer = hex_data(buyer, 20, "buyer")
    seller = hex_data(seller, 20, "seller")
    if buyer == seller:
        raise ValueError("Seller and buyer must have distinct addresses")
    purchase_tx = hex_data(purchase_tx, 32, "purchase transaction")
    offer = verify_offer(rpc, seller, listing_tx, offer_tx)
    purchase = checked_transaction(rpc, purchase_tx, buyer, seller, FULL_PRICE_BASE_UNITS)
    offer_pos = (offer["offer_block"], offer["offer_index"])
    _check_reference(rpc, purchase, offer_pos, offer["offer_tx"], PURCHASE_TAG)
    (height, _), block_hash, _, receipt = purchase
    gas_used = quantity(receipt.get("gasUsed"), "purchase gas used")
    gas_price = quantity(receipt.get("effectiveGasPrice"), "purchase effective gas price")
    network_fee = gas_used * gas_price
    return dict(offer, buyer=buyer, purchase_tx=purchase_tx, purchase_block=height,
                purchase_block_hash=block_hash, purchase_gas_fee_base_units=str(network_fee),
                buyer_total_base_units=str(FULL_PRICE_BASE_UNITS + network_fee))
