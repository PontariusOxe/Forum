# Fårforum

Ett litet forum där användare kan skapa konto, logga in och skriva inlägg. Inläggen sparas i SQLite och visas på startsidan tillsammans med användarnamnet för den som skrev varje inlägg.

## Starta

Kräver Python 3.10 eller senare. Inga externa paket behövs.

```powershell
python server.py
```

Öppna <http://127.0.0.1:8000>. Databasen `forum.db` skapas automatiskt bredvid `server.py`.

## Funktioner

- Skapa konto och logga in.
- Skriva inlägg när du är inloggad.
- Läsa inlägg med tydlig författare och tidpunkt.

Lösenord lagras som PBKDF2-hashar, och text från användare HTML-escapas innan den visas.
