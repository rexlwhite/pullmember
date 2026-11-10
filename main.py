import os, time, asyncio, requests, discord, uvicorn
from discord.ext import commands
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from supabase import create_client

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
app = FastAPI()

def get_cfg(k): 
    r = supabase.table("discord_config").select("value").eq("key", k).execute()
    return r.data["value"] if r.data else ""

def set_cfg(k, v): supabase.table("discord_config").upsert({"key": k, "value": str(v)}).execute()

def save_tok(uid, at, rt, exp): supabase.table("discord_tokens").upsert({"discord_id": str(uid), "access_token": at, "refresh_token": rt, "expires_at": int(time.time()) + exp}).execute()

def refresh_tok(u):
    if u["expires_at"] - int(time.time()) > 300: return u["access_token"]
    res = requests.post("https://discord.com", data={"grant_type": "refresh_token", "refresh_token": u["refresh_token"], "client_id": get_cfg("client_id"), "client_secret": get_cfg("client_secret")}, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if res.status_code == 200:
        t = res.json()
        save_tok(u["discord_id"], t["access_token"], t["refresh_token"], t["expires_in"])
        return t["access_token"]
    return None

class LinkButtonView(discord.ui.View):
    def __init__(self, url):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="เชื่อมต่อบัญชีตรงนี้", url=url, style=discord.ButtonStyle.link))

@bot.event
async def on_ready(): print(f"บอท {bot.user} ออนไลน์แล้ว")

@bot.command()
@commands.has_permissions(administrator=True)
async def setclient(ctx, cid: str, sec: str): set_cfg("client_id", cid); set_cfg("client_secret", sec); await ctx.send("บันทึก Client ID/Secret แล้ว")

@bot.command()
@commands.has_permissions(administrator=True)
async def seturi(ctx, url: str): set_cfg("redirect_uri", url); await ctx.send("บันทึก URI แล้ว")

@bot.command()
@commands.has_permissions(administrator=True)
async def setguild(ctx): set_cfg("guild_id", ctx.guild.id); await ctx.send("บันทึกเซิร์ฟเวอร์ปัจจุบันเรียบร้อยแล้ว")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    cid, uri = get_cfg("client_id"), get_cfg("redirect_uri")
    if not cid or not uri: return await ctx.send("กรุณาตั้งค่า Client ID และ URI ก่อนใช้งาน")
    url = f"https://discord.com{cid}&redirect_uri={uri}&response_type=code&scope=identify%20guilds.join"
    embed = discord.Embed(title="ระบบยืนยันตัวตนสมาชิก", description="กรุณากดปุ่มลิงก์ด้านล่างเพื่อทำการผูกบัญชีเข้ากับระบบส่วนกลาง", color=0x5865F2)
    await ctx.send(embed=embed, view=LinkButtonView(url))
    await ctx.message.delete()

@bot.command()
@commands.has_permissions(administrator=True)
async def pullmembers(ctx):
    gid = get_cfg("guild_id")
    if not gid: return await ctx.send("กรุณาตั้งค่าเซิร์ฟเวอร์ก่อนด้วยคำสั่ง !setguild")
    await ctx.send("กำลังเริ่มดึงสมาชิกเข้าเซิร์ฟเวอร์")
    users = supabase.table("discord_tokens").select("*").execute().data or []
    g = bot.get_guild(int(gid))
    s, f, a = 0, 0, 0
    for u in users:
        if g and g.get_member(int(u["discord_id"])): a += 1; continue
        tok = refresh_tok(u)
        if not tok: f += 1; continue
        res = requests.put(f"https://discord.com{gid}/members/{u['discord_id']}", json={"access_token": tok}, headers={"Authorization": f"Bot {os.environ.get('DISCORD_TOKEN')}", "Content-Type": "application/json"})
        if res.status_code == 201: s += 1
        elif res.status_code == 204: a += 1
        else: f += 1
        await asyncio.sleep(1.0)
    await ctx.send(f"ดึงเสร็จสิ้น สำเร็จ: {s} คน, อยู่แล้ว: {a} คน, ล้มเหลว: {f} คน")

@app.get("/", response_class=HTMLResponse)
def index():
    url = f"https://discord.com{get_cfg('client_id')}&redirect_uri={get_cfg('redirect_uri')}&response_type=code&scope=identify%20guilds.join"
    return f"<html><body style='font-family:sans-serif;text-align:center;margin-top:100px;background:#23272a;color:white;'><div style='background:#2c2f33;padding:40px;border-radius:10px;display:inline-block;'><h2>ระบบยืนยันตัวตนเพื่อเข้าเซิร์ฟเวอร์</h2><p>กรุณากดปุ่มเพื่อผูกบัญชี Discord ของคุณ</p><a style='background:#5865F2;color:white;padding:15px 30px;text-decoration:none;border-radius:5px;font-weight:bold;display:inline-block;' href='{url}'>เชื่อมต่อบัญชี Discord</a></div></body></html>"

@app.get("/callback", response_class=HTMLResponse)
async def callback(code: str = Query(None)):
    if not code: return "<h3 style='color:red;'>ไม่พบรหัสยืนยันสิทธิ์</h3>"
    gid = get_cfg("guild_id")
    res = requests.post("https://discord.com", data={"client_id": get_cfg("client_id"), "client_secret": get_cfg("client_secret"), "grant_type": "authorization_code", "code": code, "redirect_uri": get_cfg("redirect_uri")}, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if res.status_code != 200: return "<h3 style='color:red;'>แลกโทเค็นไม่สำเร็จ</h3>"
    t = res.json()
    u_res = requests.get("https://discord.com", headers={"Authorization": f"Bearer {t['access_token']}"})
    if u_res.status_code != 200: return "<h3 style='color:red;'>ดึงโปรไฟล์ล้มเหลว</h3>"
    uid, uname = u_res.json()["id"], u_res.json()["username"]
    try: save_tok(uid, t["access_token"], t["refresh_token"], t["expires_in"])
    except: pass
    g = bot.get_guild(int(gid or 0))
    if not g: return "<h3 style='color:red;'>ไม่พบเซิร์ฟเวอร์เป้าหมาย</h3>"
    m = g.get_member(int(uid))
    if m: return f"<h3 style='color:green;'>คุณ {uname} อยู่ในเซิร์ฟเวอร์อยู่แล้วเรียบร้อยครับ</h3>"
    else:
        res = requests.put(f"https://discord.com{gid}/members/{uid}", json={"access_token": t["access_token"]}, headers={"Authorization": f"Bot {os.environ.get('DISCORD_TOKEN')}", "Content-Type": "application/json"})
        if res.status_code in: return f"<h3 style='color:green;'>ยินดีต้อนรับ ดึงคุณ {uname} เข้าสู่เซิร์ฟเวอร์สำเร็จแล้วครับ</h3>"
        return "<h3 style='color:red;'>ไม่สามารถดึงตัวเข้าเซิร์ฟเวอร์ได้</h3>"

async def main():
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning"))
    asyncio.create_task(server.serve())
    await bot.start(os.environ.get("TOKEN"))

if __name__ == "__main__": asyncio.run(main())
