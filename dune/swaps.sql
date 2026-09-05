-- Uniswap v3 swap events for the universe pools.
--
-- The pipeline reads these events from `eth_getLogs` against an archive node
-- rather than from Dune (see DECISIONS.md 0.4: exact integers, native log
-- ordering, no API key). This query is published as the readable statement of
-- exactly what is extracted, and as an independent cross-check anyone with a
-- free Dune account can run.
--
-- evt_index is the within-block ordering that sandwich classification depends
-- on. It is never dropped.
SELECT
    evt_block_number,
    evt_block_time,
    evt_tx_hash,
    evt_index,
    amount0,
    amount1,
    sqrtPriceX96,
    liquidity,
    tick,
    sender,
    recipient
FROM uniswap_v3_ethereum.Pool_evt_Swap
WHERE contract_address = {{pool_address}}
  AND evt_block_time >= TIMESTAMP {{start_date}}
  AND evt_block_time <  TIMESTAMP {{end_date}}
ORDER BY evt_block_number, evt_index
