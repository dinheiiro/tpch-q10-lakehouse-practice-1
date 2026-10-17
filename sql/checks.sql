-- Each of these queries must return zero.
SELECT count(*) - count(DISTINCT custkey) AS duplicate_customer_keys FROM bronze.lab.customer;
SELECT count(*) - count(DISTINCT orderkey) AS duplicate_order_keys FROM bronze.lab.orders;
SELECT count(*) - count(DISTINCT ROW(orderkey, linenumber)) AS duplicate_lineitem_keys FROM bronze.lab.lineitem;
SELECT count(*) - count(DISTINCT nationkey) AS duplicate_nation_keys FROM bronze.lab.nation;
SELECT count(*) AS invalid_price_or_discount FROM bronze.lab.lineitem
WHERE extendedprice IS NULL OR extendedprice < 0 OR discount IS NULL OR discount < 0 OR discount > 1;
SELECT count(*) - count(DISTINCT custkey) AS duplicate_silver_customer_keys FROM silver.lab.customers_nation;
SELECT count(*) - count(DISTINCT ROW(orderkey, linenumber)) AS duplicate_silver_item_keys FROM silver.lab.returned_items_q4_1993;
