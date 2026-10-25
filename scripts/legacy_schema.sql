-- SQL Server 2016: read-only schema inventory for migration planning.
-- No customer/document rows or passwords are returned; no data is changed.
-- Execute in the old CRM database, not in master.
SET NOCOUNT ON;

SELECT DB_NAME() AS database_name,
       SERVERPROPERTY('ProductVersion') AS sql_server_version;

SELECT s.name AS schema_name, t.name AS table_name,
       COALESCE(p.estimated_rows,0) AS estimated_rows
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id=t.schema_id
LEFT JOIN (
    SELECT object_id,SUM(rows) AS estimated_rows
    FROM sys.partitions WHERE index_id IN (0,1) GROUP BY object_id
) AS p ON p.object_id=t.object_id
WHERE t.is_ms_shipped=0
ORDER BY s.name,t.name;

SELECT s.name AS schema_name,t.name AS table_name,c.column_id,
       c.name AS column_name,ty.name AS data_type,c.max_length,
       c.precision,c.scale,c.is_nullable,c.is_identity,c.is_computed,
       c.collation_name
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id=t.schema_id
JOIN sys.columns AS c ON c.object_id=t.object_id
JOIN sys.types AS ty ON ty.user_type_id=c.user_type_id
WHERE t.is_ms_shipped=0
ORDER BY s.name,t.name,c.column_id;

SELECT s.name AS schema_name,t.name AS table_name,
       i.name AS index_name,i.is_primary_key,i.is_unique,
       ic.key_ordinal,c.name AS column_name
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id=t.schema_id
JOIN sys.indexes AS i ON i.object_id=t.object_id
JOIN sys.index_columns AS ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
JOIN sys.columns AS c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
WHERE t.is_ms_shipped=0 AND i.is_unique=1 AND ic.key_ordinal>0
ORDER BY s.name,t.name,i.name,ic.key_ordinal;

SELECT fk.name AS foreign_key,
       ps.name AS parent_schema,pt.name AS parent_table,pc.name AS parent_column,
       rs.name AS referenced_schema,rt.name AS referenced_table,rc.name AS referenced_column,
       fkc.constraint_column_id,fk.is_disabled
FROM sys.foreign_keys AS fk
JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id=fk.object_id
JOIN sys.tables AS pt ON pt.object_id=fkc.parent_object_id
JOIN sys.schemas AS ps ON ps.schema_id=pt.schema_id
JOIN sys.columns AS pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id
JOIN sys.tables AS rt ON rt.object_id=fkc.referenced_object_id
JOIN sys.schemas AS rs ON rs.schema_id=rt.schema_id
JOIN sys.columns AS rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id
ORDER BY ps.name,pt.name,fk.name,fkc.constraint_column_id;
