-- Canonical Bronze is PARQUET/ZSTD. The runner creates it before executing this file.
CREATE TABLE silver.lab.customers_nation AS
SELECT c.custkey, c.name, c.acctbal, c.nationkey, n.name AS nation,
       c.address, c.phone, c.comment
FROM bronze.lab.customer c
JOIN bronze.lab.nation n ON c.nationkey = n.nationkey;

CREATE TABLE silver.lab.returned_items_q4_1993 AS
SELECT o.orderkey, o.custkey, l.linenumber, l.extendedprice, l.discount
FROM bronze.lab.orders o
JOIN bronze.lab.lineitem l ON o.orderkey = l.orderkey
WHERE o.orderdate >= DATE '1993-10-01'
  AND o.orderdate < DATE '1994-01-01'
  AND l.returnflag = 'R';

CREATE TABLE gold.lab.q10_top20 AS
SELECT c.custkey, c.name,
       sum(r.extendedprice * (1 - r.discount)) AS revenue,
       c.acctbal, c.nation, c.address, c.phone, c.comment
FROM silver.lab.customers_nation c
JOIN silver.lab.returned_items_q4_1993 r ON c.custkey = r.custkey
GROUP BY c.custkey, c.name, c.acctbal, c.nation, c.address, c.phone, c.comment
ORDER BY revenue DESC
LIMIT 20;
