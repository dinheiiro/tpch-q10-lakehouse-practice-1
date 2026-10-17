# Практическая № 1: TPC-H Q10 в локальном Lakehouse

Работа Бикбулатовой Динары Фануровны, вариант 2, `tpch.sf1`. Сырые таблицы хранятся в Bronze, подготовленные данные — в Silver, ответ Q10 — в Gold. У каждого слоя отдельный бакет RustFS и warehouse Lakekeeper.

## Что понадобится

Windows 11 с Docker Desktop (Linux containers, WSL 2) и Python 3.12. На этом компьютере рабочая папка находится на диске D; частные настройки, база PostgreSQL и состояние Superset хранятся в `D:\lakehouse-tpch-q10-runtime`, вне Git. Данные RustFS находятся в Docker-томе `s3-data`; том, образы и WSL-диск Docker Desktop размещены на D.

Используется Trino 476. Технологии и результаты собственного прогона описаны в [отчёте](отчет.md), исходные числа — в [измерениях](results/measurements.json).

## Поднять стек

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

`prepare` генерирует случайные пароли и каталог Trino в частной папке. Параметр `--accept-lakekeeper-terms` используют после ознакомления с условиями Lakekeeper. Для другого расположения частной папки задайте переменную окружения `LAKEHOUSE_RUNTIME` перед первым шагом. Скрипт выбирает свободные порты; действительные значения напечатаны после `prepare` и сохранены в частном `runtime.env`.

| Интерфейс | Порт в проверенном прогоне |
|---|---:|
| RustFS S3 API | 9000 |
| RustFS Console | 9001 |
| PostgreSQL | 5432 |
| Lakekeeper | 8181 |
| Trino | 8080 |
| Superset | 8088 |

Адреса интерфейсов имеют вид `http://localhost:<порт>`. При конфликте портов используйте значения, напечатанные `prepare`. Пароли RustFS и Superset берутся из частного `runtime.env`; публиковать этот файл нельзя.

## Загрузить данные и повторить измерения

На новом, пустом стенде выполните:

```powershell
py scripts/run.py
```

Скрипт загружает все строки четырёх таблиц `tpch.sf1`, строит Silver и Gold, проверяет ключи и денежные поля, запускает Q10 по четырём сочетаниям формата и кодека. У каждого сочетания один прогрев и пять измерений. Время берётся по часам клиента от отправки SQL до получения всех страниц результата. Размер — сумма `file_size_in_bytes` из `$files` текущего Iceberg-снапшота; это размер файлов данных без исторических и служебных файлов. Каждый шаг сохраняет прогресс в `results/measurements.json`.

Контрольный запрос преподавателя — [q10_control.sql](sql/q10_control.sql). Построение слоёв — [layers.sql](sql/layers.sql), проверки — [checks.sql](sql/checks.sql). Вариант `parquet_zstd` создаёт таблицы `bronze.lab.customer`, `orders`, `lineitem`, `nation`; остальные варианты получают суффиксы в том же бакете. Витрина — `gold.lab.q10_top20`.

`run.py` рассчитан на чистые схемы. Это исключает случайное повторное использование старых таблиц и измерений. Для нового прогона создайте отдельную частную папку и удалите прежние контейнеры и данные только после сохранения нужного результата.

## Superset и подтверждения

В Superset добавьте базу Trino с SQLAlchemy URI `trino://student@trino:8080/bronze`. В SQL Lab выполните:

```sql
SELECT custkey, name, nationkey FROM bronze.lab.customer ORDER BY custkey LIMIT 10;
```

Скриншоты этого запуска: [Docker Desktop](evidence/docker-services.jpg), [три бакета RustFS](evidence/rustfs-three-buckets.jpg), [Parquet-файл Bronze customer](evidence/rustfs-bronze-customer-file.jpg), [Trino 476](evidence/trino-476-overview.jpg), [запрос Bronze в Superset SQL Lab](evidence/superset-sql-lab-bronze-customer.jpg). Числовые подтверждения: [список бакетов](evidence/buckets.txt), [файл Bronze customer](evidence/bronze-customer-files.txt), [ответы Trino](evidence/trino-query-results.txt), [результат SQL Lab](evidence/superset-sql-lab-result.json). Запрос в SQL Lab вернул 10 строк; ранее тот же запрос через API SQL Lab выполнился со статусом `success`.

## Файлы и секреты

В Git попадают только Compose, Dockerfile Superset, два основных Python-скрипта, SQL, отчёт, измерения и доказательства запуска. Данные контейнеров, пароли, токены и конфигурация каталога Trino остаются в частной папке на D. Перед публикацией проверьте `docker compose config`, `py_compile`, ссылки и содержимое индекса Git.
