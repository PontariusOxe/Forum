# Fårforum

Ett litet forum där användare kan skapa konto, logga in och skriva inlägg. Inläggen visas på startsidan tillsammans med användarnamnet för den som skrev varje inlägg.

## Starta

Kräver Python 3.10 eller senare, XAMPP med MySQL/MariaDB startad och Python-paketet `mysql-connector-python`.

```powershell
python -m pip install -r requirements.txt
python server.py
```

Öppna <http://127.0.0.1:8000>.

## Koppla till XAMPP

1. Starta **MySQL** i XAMPP Control Panel.
2. Öppna phpMyAdmin och skapa en databas som heter `farforum` (eller ändra `DB_NAME` i `server.py`).
3. I `server.py`, fyll i `DB_HOST`, `DB_PORT`, `DB_USER` och `DB_PASSWORD` med värden från din XAMPP-installation. Standardporten är ofta `3306`. Om du använder en annan MySQL-användare än `root`, se till att användaren har rättigheter till forumdatabasen.
4. Starta forumet. Tabellerna skapas automatiskt i den valda databasen.

Anslutningsuppgifterna står samlade nära början av `server.py`.

### SQLite som alternativ

Om XAMPP inte är igång kan du tillfälligt välja SQLite i PowerShell:

```powershell
$env:FORUM_DB_BACKEND = "sqlite"
python server.py
```

Då skapas `forum.db` bredvid `server.py`. SQLite- och MySQL-databaserna är separata; befintliga SQLite-inlägg kopieras inte automatiskt.

## Funktioner

- Skapa konto och logga in.
- Skriva inlägg när du är inloggad.
- Läsa inlägg med tydlig författare och tidpunkt.

Lösenord lagras som PBKDF2-hashar, och text från användare HTML-escapas innan den visas.
