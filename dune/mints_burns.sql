-- Mint and Burn events, for approach A of the fee-accrual calculation
-- (Stage 2.2): replaying the full tick liquidity map from pool creation.
--
-- Liquidity is added at tick_lower and removed at tick_upper, so active
-- liquidity at any tick is the running sum of these deltas up to it.
SELECT evt_block_number, evt_block_time, evt_index, 'mint' AS event_type,
       tickLower AS tick_lower, tickUpper AS tick_upper,
       CAST(amount AS DECIMAL(38,0)) AS liquidity_delta, amount0, amount1
FROM uniswap_v3_ethereum.Pool_evt_Mint
WHERE contract_address = {{pool_address}}
  AND evt_block_time >= TIMESTAMP {{start_date}}
  AND evt_block_time <  TIMESTAMP {{end_date}}

UNION ALL

SELECT evt_block_number, evt_block_time, evt_index, 'burn' AS event_type,
       tickLower, tickUpper,
       -CAST(amount AS DECIMAL(38,0)) AS liquidity_delta, amount0, amount1
FROM uniswap_v3_ethereum.Pool_evt_Burn
WHERE contract_address = {{pool_address}}
  AND evt_block_time >= TIMESTAMP {{start_date}}
  AND evt_block_time <  TIMESTAMP {{end_date}}

ORDER BY evt_block_number, evt_index
