"""MGE controller (F0): Discord bot + scheduler + zagon agentov + odobritve."""
import asyncio
import datetime as dt
import json
import logging
import os
import traceback
from pathlib import Path

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands

from . import db, odoo
from .runner import AGENTS_DIR, load_agent, run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("controller")

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD = discord.Object(id=int(os.environ["DISCORD_GUILD_ID"]))
CHANNEL_ID = int(os.environ["DISCORD_APPROVAL_CHANNEL_ID"])
APPROVERS = {int(x) for x in os.environ["DISCORD_APPROVER_IDS"].split(",") if x.strip()}
TZ = os.environ.get("TZ", "Europe/Ljubljana")
LOG_DIR = Path("/logs")

client = discord.Client(intents=discord.Intents.default())
tree = app_commands.CommandTree(client)
scheduler = AsyncIOScheduler(timezone=TZ)
running: set[str] = set()


def save_error_log(run_id: int, agent: str, err: str) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"run-{run_id}-{agent}.log"
    path.write_text(f"{dt.datetime.now().isoformat()}\n{err}\n")
    return path


def approval_view(approval_id: int) -> discord.ui.View:
    # custom_id preživi restart bota; obdela ga on_interaction spodaj
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Odobri knjiženje", style=discord.ButtonStyle.success,
                                    custom_id=f"approve:{approval_id}"))
    view.add_item(discord.ui.Button(label="Zavrni", style=discord.ButtonStyle.danger,
                                    custom_id=f"reject:{approval_id}"))
    return view


def drafts_embed(run_id: int, agent: str, drafts: list[dict], summary: str) -> discord.Embed:
    total = sum(d["amount_total"] for d in drafts)
    emb = discord.Embed(title=f"Odobritev: {len(drafts)} osnutkov računov (run #{run_id})",
                        description=(summary or "")[:1500], color=0xF5A623)
    for d in drafts[:15]:   # Discord: embed max 6000 znakov
        partner = d["partner_id"][1] if d["partner_id"] else "?"
        emb.add_field(name=partner[:100],
                      value=f"{d['amount_total']:.2f} | datum {d['invoice_date']} | id {d['id']}",
                      inline=False)
    if len(drafts) > 15:
        emb.add_field(name="…", value=f"in še {len(drafts) - 15} računov (preveri v Odoo)", inline=False)
    emb.set_footer(text=f"Agent: {agent} · Skupaj z DDV: {total:.2f}")
    return emb


async def execute(agent: str, trigger: str, requested_by: str, extra: str = "") -> None:
    channel = client.get_channel(CHANNEL_ID)
    if agent in running:
        await channel.send(f"⏳ `{agent}` že teče, nov zagon preskočen.")
        return
    running.add(agent)
    since = dt.datetime.utcnow().replace(microsecond=0) - dt.timedelta(seconds=5)
    run_id = db.q("INSERT INTO runs(agent, trigger, requested_by) VALUES (%s,%s,%s) RETURNING id",
                  (agent, trigger, requested_by), one=True)["id"]
    db.audit(requested_by, "run.start", {"run_id": run_id, "agent": agent, "extra": extra})
    await channel.send(f"▶️ `{agent}` run #{run_id} zagnan ({trigger}, {requested_by})")

    try:
        cfg = load_agent(agent)
        res = await asyncio.wait_for(run_agent(agent, run_id, extra),
                                     timeout=cfg["limits"]["max_runtime_min"] * 60)
        if res["is_error"]:
            raise RuntimeError(f"Agent je končal z napako:\n{res['text']}")

        drafts = await asyncio.to_thread(odoo.agent_drafts_since, since.strftime("%Y-%m-%d %H:%M:%S"))
        status = "awaiting_approval" if drafts else "done"
        db.q("UPDATE runs SET status=%s, cost_usd=%s, summary=%s, finished_at=now() WHERE id=%s",
             (status, res["cost_usd"], res["text"], run_id))
        db.audit("agent:" + agent, "run.finish",
                 {"run_id": run_id, "drafts": [d["id"] for d in drafts], "cost_usd": res["cost_usd"]})

        cost = f"{res['cost_usd']:.2f} USD" if res["cost_usd"] is not None else "n/a"
        if drafts:
            appr_id = db.q("INSERT INTO approvals(run_id, action, payload) VALUES (%s,%s,%s::jsonb) RETURNING id",
                           (run_id, "odoo.post_invoices",
                            json.dumps({"invoice_ids": [d["id"] for d in drafts]})),
                           one=True)["id"]
            await channel.send(content=f"Strošek runa: {cost}",
                               embed=drafts_embed(run_id, agent, drafts, res["text"]),
                               view=approval_view(appr_id))
        else:
            await channel.send(f"✅ `{agent}` run #{run_id} končan brez novih osnutkov. Strošek: {cost}\n"
                               f"{res['text'][:1500]}")
    except Exception as e:
        err = traceback.format_exc()
        path = save_error_log(run_id, agent, err)
        db.q("UPDATE runs SET status='failed', error=%s, finished_at=now() WHERE id=%s", (err, run_id))
        db.audit("controller", "run.failed", {"run_id": run_id, "error": str(e)})
        log.error("Run %s failed: %s", run_id, err)
        await channel.send(f"❌ `{agent}` run #{run_id} ni uspel: `{str(e)[:300]}`\nLog: `{path}`")
    finally:
        running.discard(agent)


@client.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    cid = (interaction.data or {}).get("custom_id", "")
    if not cid.startswith(("approve:", "reject:")):
        return
    if interaction.user.id not in APPROVERS:
        await interaction.response.send_message("Nimaš pravice odobritve.", ephemeral=True)
        return

    action, appr_id = cid.split(":")
    appr = db.q("SELECT * FROM approvals WHERE id=%s", (int(appr_id),), one=True)
    if not appr or appr["status"] != "pending":
        await interaction.response.send_message("Ta odobritev je že obdelana.", ephemeral=True)
        return

    await interaction.response.defer()
    who = f"{interaction.user} ({interaction.user.id})"
    await interaction.message.edit(view=None)

    if action == "reject":
        db.q("UPDATE approvals SET status='rejected', decided_by=%s, decided_at=now() WHERE id=%s", (who, appr["id"]))
        db.q("UPDATE runs SET status='rejected' WHERE id=%s", (appr["run_id"],))
        db.audit(who, "approval.rejected", {"approval_id": appr["id"]})
        await interaction.followup.send(f"🛑 Zavrnjeno ({interaction.user.mention}). Osnutki ostanejo v Odoo za ročni pregled.")
        return

    db.q("UPDATE approvals SET status='approved', decided_by=%s, decided_at=now() WHERE id=%s", (who, appr["id"]))
    db.audit(who, "approval.approved", {"approval_id": appr["id"], "payload": appr["payload"]})
    try:
        posted = await asyncio.to_thread(odoo.post_invoices, appr["payload"]["invoice_ids"])
        db.q("UPDATE approvals SET status='executed', result=%s::jsonb WHERE id=%s",
             (json.dumps(posted), appr["id"]))
        db.q("UPDATE runs SET status='done' WHERE id=%s", (appr["run_id"],))
        db.audit("controller", "odoo.posted", {"approval_id": appr["id"], "result": posted})
        names = ", ".join(p["name"] for p in posted)
        await interaction.followup.send(f"✅ Knjiženo {len(posted)} računov: {names}")
    except Exception as e:
        err = traceback.format_exc()
        path = save_error_log(appr["run_id"], "approval", err)
        db.q("UPDATE approvals SET status='failed' WHERE id=%s", (appr["id"],))
        db.audit("controller", "odoo.post_failed", {"approval_id": appr["id"], "error": str(e)})
        await interaction.followup.send(f"❌ Knjiženje ni uspelo: `{str(e)[:300]}`\nLog: `{path}`")


@tree.command(name="run", description="Zaženi agenta", guild=GUILD)
@app_commands.describe(agent="Ime agenta (mapa v agents/)", navodilo="Dodatno navodilo (opcijsko)")
async def run_cmd(interaction: discord.Interaction, agent: str, navodilo: str = ""):
    if interaction.user.id not in APPROVERS:
        await interaction.response.send_message("Nimaš pravice zagona.", ephemeral=True)
        return
    if not (AGENTS_DIR / agent / "agent.yaml").exists():
        await interaction.response.send_message(f"Agent `{agent}` ne obstaja.", ephemeral=True)
        return
    await interaction.response.send_message(f"Zaganjam `{agent}` …", ephemeral=True)
    asyncio.create_task(execute(agent, "discord", f"{interaction.user} ({interaction.user.id})", navodilo))


_started = False


@client.event
async def on_ready():
    global _started
    if _started:
        return
    _started = True
    await tree.sync(guild=GUILD)
    for f in sorted(AGENTS_DIR.glob("*/agent.yaml")):
        name = f.parent.name
        expr = (load_agent(name).get("trigger") or {}).get("schedule")
        if expr:
            scheduler.add_job(execute, CronTrigger.from_crontab(expr, timezone=TZ),
                              args=[name, "schedule", "scheduler"], id=name, replace_existing=True)
            log.info("Urnik: %s -> %s", name, expr)
    scheduler.start()
    log.info("Controller pripravljen kot %s", client.user)


if __name__ == "__main__":
    client.run(TOKEN)
