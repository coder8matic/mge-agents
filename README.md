# MGE Agents: F0 na Macu

Cilj F0: **mesečni računi pripravljeni samodejno, knjiženje šele po odobritvi v Discordu.**

```
Discord (/run, gumbi)  ─┐
Scheduler (1. ob 7:00) ─┼─> controller ──> Claude (API) 
                        │       │
                        │       ├──MCP──> Executor ──MCP──> odoo-mcp ──JSON-2──> Odoo (agentov ključ: samo osnutki)
                        │       └──JSON-2 (odobritveni ključ, šele po kliku "Odobri")──> Odoo action_post
                        └─ Postgres (runs, approvals, audit_log)
```

**Ključna varnostna lastnost:** agent sploh nima orodja za knjiženje. Agentov Odoo ključ živi samo v `odoo-mcp`, ključ za knjiženje pa samo v `controller`. Knjiženje se zgodi deterministično v kodi, ne v LLM-u, in šele po tvojem kliku.

---

## 0. Preden začneš

| Preveri | Zakaj |
|---|---|
| **Odoo plan** | Pri Odoo Online je zunanji API (JSON-2) na voljo samo na planu **Custom** (ne na One App Free ali Standard). Pri Odoo.sh ali on-prem ta omejitev ne velja. |
| **Licenca za agenta** | Uporabnik "Invoicing Agent" je interni uporabnik, kar pomeni dodaten sedež v Odoo. |
| **Mac ne sme spati** | Če Mac 1. v mesecu ob 7:00 spi, se urnik ne izvede. V F0 je to sprejemljivo (zaženeš ročno z `/run`). Za stalen urnik je rešitev mini PC (korak 11). |
| **Testno okolje** | Prvi zagon izvedi na Odoo staging/testni bazi, če jo imaš. |

---

## 1. Orodja na Macu

```bash
# Homebrew (če ga še nimaš)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Docker runtime: OrbStack (lažji) ALI Docker Desktop
brew install --cask orbstack        # ali: brew install --cask docker

brew install git
```

Zaženi OrbStack ali Docker Desktop in preveri: `docker compose version`.
V Docker Desktop nastavi vsaj **4 GB RAM** (Settings → Resources).

---

## 2. Repo

```bash
mkdir -p ~/Projects && cd ~/Projects
unzip ~/Downloads/mge-agents.zip        # ali skopiraj mapo
cd mge-agents
git init && git add . && git commit -m "F0: temelj agentne platforme"
cp .env.example .env                    # .env je v .gitignore
```

Struktura:

```
mge-agents/
├── compose.yaml
├── .env.example
├── db/init.sql                       # runs, approvals, audit_log (append-only)
├── agents/odoo-invoicing/
│   ├── agent.yaml                    # model, urnik, limiti
│   ├── CLAUDE.md                     # navodila agentu
│   └── customers.yaml                # KDO in KAJ se fakturira
├── services/
│   ├── odoo-mcp/                     # MCP strežnik: samo branje + osnutki
│   └── controller/                   # Discord bot, scheduler, runner, odobritve
└── logs/                             # error logi neuspelih runov
```

Če želiš oddaljeni repo: ustvari zasebni `mge-agents` na GitHubu in `git remote add origin … && git push -u origin main`.

---

## 3. Anthropic API ključ

1. https://console.anthropic.com → **Workspaces** → ustvari `mge-agents` (za SunContract kasneje ločen workspace).
2. V workspace-u nastavi **spend limit** (npr. 50 USD/mesec za F0).
3. **API keys** → Create key v tem workspace-u → v `.env`: `ANTHROPIC_API_KEY=…`

---

## 4. Odoo

### 4.1 Uporabnik agenta
1. Settings → Users → **New**: ime `Invoicing Agent`, e-pošta npr. `invoicing-agent@suncontract.org`.
2. Pravice: **Invoicing: Billing** (ustvarjanje računov). Nič drugega (brez Settings, brez Sales/CRM admin).
3. Shrani in iz URL-ja (`…/odoo/users/42`) prepiši ID v `.env` → `ODOO_AGENT_USER_ID=42`.

### 4.2 API ključa
- **Agent:** prijavi se kot Invoicing Agent (v zasebnem oknu) → My Preferences → Account Security → **New API Key** → `ODOO_AGENT_API_KEY`.
- **Odobritelj (ti):** isto na svojem uporabniku → `ODOO_APPROVER_API_KEY`.
- Odoo ne dovoli ključev, daljših od **3 mesecev**. Vnesi si opomnik za rotacijo.
- `ODOO_URL` (npr. `https://suncontract.odoo.com`) in `ODOO_DB` (ime baze).

### 4.3 Test ključa
```bash
source .env
curl -sS "$ODOO_URL/json/2/res.partner/search_read" \
  -H "Authorization: bearer $ODOO_AGENT_API_KEY" \
  -H "X-Odoo-Database: $ODOO_DB" \
  -H "Content-Type: application/json" \
  -d '{"domain":[["is_company","=",true]],"fields":["name"],"limit":3}'
```
Pričakovano: JSON s tremi strankami. `401 Invalid apikey` pomeni napačen ključ, 403/404 pa težavo s planom ali URL-jem.

### 4.4 customers.yaml
Uredi `agents/odoo-invoicing/customers.yaml`: točna imena strank in izdelkov, kot so v Odoo, ter količine in cene.

---

## 5. Discord

1. https://discord.com/developers/applications → **New Application** `MGE Agents`.
2. **Bot** → Reset Token → `DISCORD_BOT_TOKEN`. Privileged intenti niso potrebni.
3. **OAuth2 → URL Generator**: scopes `bot`, `applications.commands`; permissions `Send Messages`, `Embed Links`, `Read Message History`. Odpri URL in dodaj bota na strežnik **MGE**.
4. Na strežniku ustvari kanal `#odobritve`.
5. Discord → Settings → Advanced → **Developer Mode** ON, nato desni klik → *Copy ID*:
   - strežnik → `DISCORD_GUILD_ID`
   - kanal `#odobritve` → `DISCORD_APPROVAL_CHANNEL_ID`
   - tvoj profil → `DISCORD_APPROVER_IDS`

---

## 6. Zagon Postgres, Executor, odoo-mcp

V `.env` nastavi še `POSTGRES_PASSWORD`, nato:

```bash
docker compose up -d --build postgres executor odoo-mcp
docker compose ps                     # vse "running"/"healthy"
docker compose logs odoo-mcp --tail 20
```

---

## 7. Executor: integracija, politike, ključ

Odpri **http://localhost:4788**.

1. **Dodaj integracijo → MCP server**
   - namespace/ime: `odoo`
   - URL: `http://odoo-mcp:8000/mcp` (ime servisa v Docker omrežju, ne `localhost`)
   - Brez avtentikacije, ker je odoo-mcp dosegljiv samo znotraj Docker omrežja.
2. **Politike** (za vsako orodje integracije `odoo`):

   | Orodje | Politika |
   |---|---|
   | `find_partners`, `find_products`, `list_invoices`, `get_invoice_lines` | allow |
   | `create_draft_invoice` | allow (ustvari samo osnutek, človeška kontrola je v Discordu) |

   Ne nastavljaj "require approval": odobritev v Executorju bi ustavila run in čakala v Executorjevem UI-ju, ne v Discordu.
3. **Ključ za MCP odjemalca:** v nastavitvah workspace-a ustvari API ključ/token za MCP clienta → `.env`: `EXECUTOR_TOKEN=…`
   Controller ga pošlje kot `Authorization: Bearer <token>`. Če UI za self-host zahteva drugačno glavo, popravi `headers` v `services/controller/app/runner.py`.
4. Preizkus: v Executor UI poženi `odoo.find_partners` z `{"name": "d.o.o."}` in preveri, da vrne stranke.

---

## 8. Zagon controllerja

```bash
docker compose up -d --build controller
docker compose logs -f controller
```
Pričakovano v logu:
```
Urnik: odoo-invoicing -> 0 7 1 * *
Controller pripravljen kot MGE Agents#1234
```

---

## 9. Prvi test

1. V Discordu: `/run agent:odoo-invoicing`
   (opcijsko `navodilo: samo stranka Primer d.o.o.` za ozek prvi test)
2. V `#odobritve` se pojavi:
   - `▶️ odoo-invoicing run #1 zagnan`
   - po nekaj minutah embed z osnutki (stranka, znesek, id), agentovim poročilom, stroškom in gumboma **Odobri knjiženje** / **Zavrni**
3. Preveri osnutke v Odoo (Invoicing → Customers → Invoices → filter *Draft*). Odpri vsaj enega.
4. Klikni **Odobri knjiženje** → `✅ Knjiženo N računov: INV/2026/…`
5. **Test idempotence:** ponovno `/run`. Agent mora vse stranke preskočiti ("že obstaja").

Pregled v bazi:
```bash
docker compose exec postgres psql -U mge -d mge -c \
 "select id, agent, status, cost_usd, started_at from runs order by id desc limit 5;"
docker compose exec postgres psql -U mge -d mge -c \
 "select at, actor, event from audit_log order by id desc limit 10;"
```

---

## 10. Odpravljanje težav

| Simptom | Vzrok / rešitev |
|---|---|
| `/run` se ne pojavi v Discordu | Napačen `DISCORD_GUILD_ID` ali bot ni povabljen s scope `applications.commands`. Restart controllerja. |
| Agent ne vidi orodij | Napačen `EXECUTOR_TOKEN` ali URL. `docker compose logs executor`. V Executor UI preveri, da je integracija `odoo` aktivna. |
| `Odoo … HTTP 401` | Ključ je potekel (max 3 meseci) ali je napačen. |
| Osnutki obstajajo, embeda ni | `ODOO_AGENT_USER_ID` se ne ujema z uporabnikom, katerega ključ uporablja odoo-mcp. |
| `❌ run ni uspel` | Celoten traceback je v `logs/run-<id>-<agent>.log` in v tabeli `runs.error`. |
| Gumbi ne delujejo po restartu | Morajo delovati (custom_id se obdela ob vsakem kliku). Če ne, preveri, da je tvoj ID v `DISCORD_APPROVER_IDS`. |

Ustavitev ali nadgradnja:
```bash
docker compose down                       # podatki ostanejo v volumnih
git pull && docker compose up -d --build  # nadgradnja
```

---

## 11. Selitev na mini PC (ko F0 deluje)

```bash
# na Macu: backup Executorja (SQLite + šifrirni ključi!) in Postgresa
mkdir -p backups
docker run --rm -v mge-agents_executor-data:/data -v "$PWD/backups":/b alpine \
  tar czf /b/executor-data.tgz -C /data .
docker compose exec -T postgres pg_dump -U mge mge > backups/mge.sql

# na mini PC-ju (Linux + Docker): git clone, prenesi .env in backups/, nato:
docker compose up -d postgres
docker run --rm -v mge-agents_executor-data:/data -v "$PWD/backups":/b alpine \
  tar xzf /b/executor-data.tgz -C /data
docker compose exec -T postgres psql -U mge mge < backups/mge.sql
docker compose up -d --build
```
Na Macu nato `docker compose down`. Hkrati sme teči **samo en** controller, sicer imaš dvojne urnike.

---

## Kaj F0 namerno še nima (pride v F1)

- runner teče znotraj controllerja (F1: efemeren container na run)
- secreti v `.env` (F1: Infisical/Vault)
- brez Langfuse/Grafana (F1)
- vrsta je in-memory `running` set, en run na agenta hkrati (F1: Postgres vrsta)
