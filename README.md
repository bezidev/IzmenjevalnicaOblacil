# Spletna izmenjevalnica oblačil Gimnazije Bežigrad

Uporablja [FastAPI](https://fastapi.tiangolo.com/), [Jinja](https://jinja.palletsprojects.com/en/stable/) in [Pico CSS](https://picocss.com/).

## Namestitev razvijalskega okolja
> [!NOTE]
> Vse, kar je v
> 
> ```
> code blocku,
> ```
> 
> naj se poganja v terminalu.

### Kloniraj repozitorij
Poskrbi, da imaš nameščen Git. Če ga nimaš, ga namesti preko [spletne strani](https://git-scm.com/) ali ustreznega package managerja, če imaš Linux.
Pri postopku namestitve nujno preveri, da vklopiš možnost, da doda Git v "PATH", če te za to vpraša.

```
git clone https://github.com/bezidev/IzmenjevalnicaOblacil
```

Odpri kloniran direktorij (`IzmenjevalnicaOblacil`) v poljubnem urejevalniku kode.
Priporočam PyCharm ali pa Visual Studio Code.

### Okoljske spremenljivke
Da bi prijava z Microsoft računom ustrezno delovala, je potrebno v [Azure portalu](https://portal.azure.com) ustvariti OAUTH2 aplikacijo.

Če si se pridružil/-a uradni ekipi razvoja te aplikacije, boš že od nekoga dobil vrednosti, potrebne za razvoj in ti za to ni potrebno skrbeti.

V nasprotnem primeru moraš ustvariti Azure aplikacijo, česar pa zdaj ne bom opisoval.
Na koncu tega postopka moraš ustvariti `.env` datoteko v direktoriju s kodo (tj. v isti mapi kot `main.py`).
Vsebina te datoteke naj sledi formatu za okoljske spremenljivke, ki so sledeče (TEGA NE POGANJAJ V TERMINALU):

```
MICROSOFT_CLIENT_ID="..."
MICROSOFT_CLIENT_SECRET="..."
```

### Namestitev vsega potrebnega za razvijalsko okolje
Poskrbi, da imaš nameščen Python. Če ga nimaš, namesti najnovejšo stabilno različico preko [spletne strani](https://www.python.org/downloads/windows/).
V primeru, da uporabljaš Linux, ga namesti preko package managerja.
Pri postopku namestitve nujno preveri, da vklopiš možnost, da doda Python v "PATH", če te za to vpraša.

Nato lahko poženeš naslednji ukaz, ki bo namestil vse potrebno za spletno stran.

```
pip install -r requirements.txt
```

### Zagon programa
```
fastapi dev main.py
```

Zdaj se spletna stran poganja na http://127.0.0.1:8000.
Ko boš spreminjal kodo, se bo spletna stran sama posodabljala (a ne osveževala! To moraš sam/-a narediti.)

### Ustvarjanje administratorskega profila

> [!TIP]
> Vse v tem koraku je potrebno narediti največ enkrat. Če se odjaviš in znova prijaviš, boš še vedno administrator/-ka.

Pojdi na http://127.0.0.1:8000 in se prijavi preko Microsofta. Po prijavi se ustvari uporabniški profil v lokalni podatkovni bazi.
To podatkovno bazo je moč najti kot `database/database.sqlite3`.

Vsi naslednji ukazi naj se poženejo v ustreznem terminalu za ustrezno platformo, tj. PowerShell oz. Command Prompt za Windows ali ustrezen terminal (sh, bash, zsh, fish ...) za Linux.

#### Linux
Svetujem, da namestiš `sqlite3` kar preko ustreznega package managerja (tj. `dnf` za Fedoro/RHEL, `apt` za Debian/Ubuntu/PopOS oz. `pacman` za Arch).
V primeru, da to ni mogoče, imaš v `cmdline/` direktoriju na voljo `sqlite3` orodje.

Svoj uporabniški profil lahko povišaš z naslednjimi zaporedji ukazov (s tem, da `ime.priimek` zamenjaš s svojim imenom in priimkom oz. ustreznim šolskim e-naslovom):
```
sqlite3 database/database.sqlite3

UPDATE users SET is_admin=true WHERE email='ime.priimek@gimb.org';
```

#### Windows
V `cmdline/` direktoriju je na voljo `sqlite3.exe` orodje.

Svoj uporabniški profil lahko povišaš z naslednjimi zaporedji ukazov (s tem, da `ime.priimek` zamenjaš s svojim imenom in priimkom oz. ustreznim šolskim e-naslovom):
```
cmdline/sqlite3.exe database/database.sqlite3

UPDATE users SET is_admin=true WHERE email='ime.priimek@gimb.org';
```

#### MacOS
Po občutku.
