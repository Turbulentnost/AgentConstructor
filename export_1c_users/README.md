# Экспорт пользователей 1С из erp_pm (только чтение)

Одноразовая утилита: читает таблицу `v8users` из SQL Server базы **erp_pm** (1С:ERP) и пишет логин, отображаемое имя, email (если найден), OSName и **hex-хэш/блок Data** в текстовый файл.

## Важно

- **Никаких записей в БД** — только `SELECT`.
- Открытых паролей в 1С нет: в файле — hex поля `Data` (проприетарный хэш и настройки).
- Email в `v8users` нет; в ERP контактные email чаще привязаны к контрагентам, а не к учётным записям — колонка Email может быть пустой.
- Файл экспорта содержит секреты — **не коммитить**.
- База `erp_pm` **не** является БД ConstructorAI.

## Запуск

```powershell
cd c:\Users\testii\Downloads\AIConstructor\scripts\export_1c_users
copy .env.example .env
# при необходимости отредактируйте .env (сервер, TrustedConnection / логин)

python -m pip install pyodbc python-dotenv
python export_users.py
```

Результат: `Instruct/exports/erp_pm_users_export.txt` (UTF-8 BOM, TSV).

## Проверка пароля (сравнение с хэшем)

Поле `Data` в 1С — это не «голый» SHA-1: сначала XOR-обёртка, внутри структура с двумя Base64(SHA-1): пароль и пароль в UPPER.

Алгоритм вынесен в общий модуль [`ai-service/tools/onec/password.py`](../../ai-service/tools/onec/password.py).  
`verify_password.py` — CLI-обёртка над ним. Тот же модуль использует `ai-service` при `POST /api/v1/auth/login`.

```powershell
python verify_password.py --sql --user "Мангасарян" --password "md641236"
# или из файла экспорта:
python verify_password.py --export ..\..\Instruct\exports\erp_pm_users_export.txt --user "Мангасарян" --password "md641236"
```

Скрипт только **проверяет известный кандидат**, пароль из хэша не восстанавливает.

## Права

Рекомендуется учётная запись с ролью `db_datareader` на `erp_pm`.
