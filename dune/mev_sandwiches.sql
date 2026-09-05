-- Sandwich attacks touching the universe pools (Stage 4.1).
--
-- Dune's pre-classified MEV tables are the PRIMARY source for MEV; the
-- same-address classifier in `src/build/mev.py` is the robustness arm.
-- Verify the current schema before use — these tables are renamed periodically.
--
-- Note on attribution: a sandwich primarily harms the TRADER, not the LP. The
-- LP earns fees on all three legs. The LP cost is indirect, through the
-- toxicity of the resulting flow. See DECISIONS.md Q1.
SELECT
    block_number,
    block_time,
    tx_hash_frontrun,
    tx_hash_victim,
    tx_hash_backrun,
    contract_address AS pool_address,
    amount_usd,
    profit_usd,
    searcher_address
FROM mev.sandwiches
WHERE blockchain = 'ethereum'
  AND contract_address = {{pool_address}}
  AND block_time >= TIMESTAMP {{start_date}}
  AND block_time <  TIMESTAMP {{end_date}}
ORDER BY block_number
