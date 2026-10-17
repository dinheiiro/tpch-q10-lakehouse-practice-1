# Практическая работа № 1: TPC-H Q10

Бикбулатова Динара Фануровна, вариант 2, масштаб `sf1`. Здесь лежат файлы для запуска Lakehouse и мой отчёт по запросу Q10 «Returned Item Reporting».

## Что нужно для запуска

Windows 11, Docker Desktop с WSL 2 и Python 3.12. Сам репозиторий находится на диске D. Пароли, настройки сервисов и данные контейнеров хранятся отдельно, в `D:\lakehouse-tpch-q10-runtime` и томах Docker.

В стенде используется Trino 476. Результаты моего запуска есть в [отчёте](отчет.md), подробные замеры — в [measurements.json](results/measurements.json).

## Запуск

Команды PowerShell из корня репозитория:

```powershell
py scripts/setup.py prepare
$runtime = 'D:\lakehouse-tpch-q10-runtime\runtime.env'
docker compose --env-file $runtime config
docker compose --env-file $runtime up -d s3 postgres lakekeeper
py scripts/setup.py bootstrap --accept-lakekeeper-terms
docker compose --env-file $runtime up -d --build trino superset
docker compose --env-file $runtime ps
```

`prepare` создаёт пароли и настройки Trino в папке вне Git. Команда `bootstrap --accept-lakekeeper-terms` подтверждает условия Lakekeeper; перед её запуском нужно с ними ознакомиться. Если папка на D не подходит, перед первым шагом можно задать `LAKEHOUSE_RUNTIME`. Занятый порт скрипт заменит свободным и запишет выбор в локальный `runtime.env`.

| Сервис | Порт в моём запуске |
|---|---:|
| RustFS S3 API | 9000 |
| RustFS Console | 9001 |
| PostgreSQL | 5432 |
| Lakekeeper | 8181 |
| Trino | 8080 |
| Superset | 8088 |

Веб-интерфейсы открываются по адресу `http://127.0.0.1:<порт>`. Если `prepare` выбрал другие порты, берите их из локального `runtime.env`.

## Данные и замеры

На новом, пустом стенде запустите:

```powershell
py scripts/run.py
```

`run.py` переносит полные таблицы `customer`, `orders`, `lineitem`, `nation` из `tpch.sf1`, строит Silver и Gold, выполняет проверки и сравнивает Q10 для Parquet/GZIP, Parquet/ZSTD, ORC/GZIP и ORC/ZSTD. Для каждого варианта есть один прогрев и пять замеров. Время измеряется от отправки SQL до получения всего ответа. Размер берётся из Iceberg `$files` текущего снапшота. Числа записываются в `results/measurements.json`.

Контрольный запрос — [q10_control.sql](sql/q10_control.sql). Создание слоёв — [layers.sql](sql/layers.sql), проверки — [checks.sql](sql/checks.sql). Основные таблицы Bronze записаны в Parquet/ZSTD. Остальные наборы получили суффиксы в названиях таблиц. Готовая витрина — `gold.lab.q10_top20`.

`run.py` рассчитан на пустые схемы, чтобы новый прогон не использовал старые таблицы. Перед повторным запуском нужен новый стенд с пустыми warehouse.

## Superset

В Superset добавьте подключение `trino://student@trino:8080/bronze`. Проверочный запрос в SQL Lab:

```sql
SELECT custkey, name, nationkey
FROM bronze.lab.customer
ORDER BY custkey
LIMIT 10;
```

## Скриншоты

- [Работающие контейнеры Docker](evidence/docker-services.jpg)
- [Бакеты Bronze, Silver и Gold](evidence/rustfs-three-buckets.jpg)
- [Parquet-файл таблицы Bronze customer](evidence/rustfs-bronze-customer-file.jpg)
- [Trino 476](evidence/trino-476-overview.jpg)
- [Запрос к Bronze в Superset SQL Lab](evidence/superset-sql-lab-bronze-customer.jpg)
